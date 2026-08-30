"""公開情報源を制限付きで読むHTTP fetcher。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


class PublicFetchError(RuntimeError):
    """公開sourceの取得が安全制約またはHTTPで失敗した。

    `reason`はfailure分類（Issue #7）が読む固定語彙。`status_code`は
    `reason == "http_status"`の場合だけ設定される。
    """

    def __init__(self, message: str, *, reason: str, status_code: int | None = None) -> None:
        """分類可能な理由と、あれば HTTP status code を保持する。"""
        super().__init__(message)
        self.reason = reason
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class FetchedArtifact:
    """上限内で取得したartifact。"""

    final_url: str
    content_type: str
    content: bytes
    content_hash: str


def _validate_url(url: str, allowed_hosts: frozenset[str]) -> None:
    """HTTPSとhost allowlistを検証する。"""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
        raise PublicFetchError(
            f"URL is outside the HTTPS host allowlist: {url}", reason="disallowed_host"
        )


def fetch_public_artifact(
    url: str,
    *,
    allowed_hosts: frozenset[str],
    expected_content_types: frozenset[str],
    max_bytes: int = 1_048_576,
    timeout_seconds: float = 15.0,
    transport: httpx.BaseTransport | None = None,
) -> FetchedArtifact:
    """redirect先を含めて検査し、展開後byte数上限まで取得する。"""
    _validate_url(url, allowed_hosts)
    headers = {"User-Agent": "KUMA800/0.0.1 (+https://github.com/saitoomituru/KUMA800)"}
    try:
        with httpx.Client(
            follow_redirects=True,
            max_redirects=5,
            timeout=timeout_seconds,
            headers=headers,
            transport=transport,
        ) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                for hop in (*response.history, response):
                    _validate_url(str(hop.request.url), allowed_hosts)
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type not in expected_content_types:
                    raise PublicFetchError(
                        f"unexpected Content-Type: {content_type or 'missing'}",
                        reason="unexpected_content_type",
                    )
                declared_length = response.headers.get("content-length")
                if declared_length is not None and int(declared_length) > max_bytes:
                    raise PublicFetchError(
                        "declared Content-Length exceeds limit", reason="content_length_exceeded"
                    )
                chunks: list[bytes] = []
                received = 0
                for chunk in response.iter_bytes():
                    received += len(chunk)
                    if received > max_bytes:
                        raise PublicFetchError(
                            "decoded response body exceeds limit", reason="body_size_exceeded"
                        )
                    chunks.append(chunk)
                content = b"".join(chunks)
                return FetchedArtifact(
                    final_url=str(response.url),
                    content_type=content_type,
                    content=content,
                    content_hash=f"sha256:{hashlib.sha256(content).hexdigest()}",
                )
    except httpx.HTTPStatusError as error:
        status_code = error.response.status_code
        raise PublicFetchError(
            f"public fetch failed: HTTP {status_code}",
            reason="http_status",
            status_code=status_code,
        ) from error
    except httpx.TimeoutException as error:
        raise PublicFetchError(
            f"public fetch failed: {type(error).__name__}", reason="timeout"
        ) from error
    except httpx.TransportError as error:
        raise PublicFetchError(
            f"public fetch failed: {type(error).__name__}", reason="connection_error"
        ) from error
    except (httpx.HTTPError, UnicodeError, ValueError) as error:
        raise PublicFetchError(
            f"public fetch failed: {type(error).__name__}", reason="transport_error"
        ) from error
