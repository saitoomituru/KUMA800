"""公開source HTTP fetcherのoffline制限試験。"""

import hashlib

import httpx
import pytest

from kuma800.scrapers.http import PublicFetchError, fetch_public_artifact

_HOSTS = frozenset({"www.pref.yamagata.jp"})
_TYPES = frozenset({"text/csv"})
_URL = "https://www.pref.yamagata.jp/data.csv"


def _fetch(handler: httpx.MockTransport) -> bytes:
    """test transportでCSV artifactを取得する。"""
    return fetch_public_artifact(
        _URL,
        allowed_hosts=_HOSTS,
        expected_content_types=_TYPES,
        transport=handler,
    ).content


def test_fetch_accepts_allowed_redirect_and_hashes_decoded_body() -> None:
    """同一allowlist host内redirectとCSV media typeを許可する。"""
    content = b"a,b\n1,2\n"

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/data.csv":
            return httpx.Response(302, headers={"location": "/latest.csv"})
        return httpx.Response(
            200, headers={"content-type": "text/csv; charset=utf-8"}, content=content
        )

    artifact = fetch_public_artifact(
        _URL,
        allowed_hosts=_HOSTS,
        expected_content_types=_TYPES,
        transport=httpx.MockTransport(respond),
    )

    assert artifact.final_url == "https://www.pref.yamagata.jp/latest.csv"
    assert artifact.content == content
    assert artifact.content_hash == f"sha256:{hashlib.sha256(content).hexdigest()}"


def test_fetch_rejects_url_outside_allowlist_before_request() -> None:
    """外部hostと平文HTTPをrequest前に拒否する。"""
    transport = httpx.MockTransport(lambda _: pytest.fail("request must not be sent"))
    with pytest.raises(PublicFetchError, match="allowlist") as first:
        fetch_public_artifact(
            "https://evil.invalid/data.csv",
            allowed_hosts=_HOSTS,
            expected_content_types=_TYPES,
            transport=transport,
        )
    assert first.value.reason == "disallowed_host"
    with pytest.raises(PublicFetchError, match="allowlist") as second:
        fetch_public_artifact(
            "http://www.pref.yamagata.jp/data.csv",
            allowed_hosts=_HOSTS,
            expected_content_types=_TYPES,
            transport=transport,
        )
    assert second.value.reason == "disallowed_host"


def test_fetch_rejects_redirect_outside_allowlist() -> None:
    """初期URLが安全でも最終redirect hostが違えば拒否する。"""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            302,
            headers={"location": "https://evil.invalid/data.csv"},
        )
        if request.url.host == "www.pref.yamagata.jp"
        else httpx.Response(200, headers={"content-type": "text/csv"}, content=b"x")
    )
    with pytest.raises(PublicFetchError, match="allowlist") as captured:
        _fetch(transport)
    assert captured.value.reason == "disallowed_host"


@pytest.mark.parametrize(
    ("headers", "content", "message", "reason"),
    [
        ({"content-type": "text/html"}, b"x", "Content-Type", "unexpected_content_type"),
        (
            {"content-type": "text/csv", "content-length": "1048577"},
            b"x",
            "Content-Length",
            "content_length_exceeded",
        ),
        ({"content-type": "text/csv"}, b"xx", "body exceeds", "body_size_exceeded"),
    ],
)
def test_fetch_rejects_type_and_size_limits(
    headers: dict[str, str], content: bytes, message: str, reason: str
) -> None:
    """media type、宣言長、実body長をそれぞれ制限し、failure分類用reasonを残す。"""

    def respond(_: httpx.Request) -> httpx.Response:
        if message == "body exceeds":
            return httpx.Response(200, headers=headers, stream=httpx.ByteStream(content))
        return httpx.Response(200, headers=headers, content=content)

    transport = httpx.MockTransport(respond)
    with pytest.raises(PublicFetchError, match=message) as captured:
        fetch_public_artifact(
            _URL,
            allowed_hosts=_HOSTS,
            expected_content_types=_TYPES,
            max_bytes=1 if message == "body exceeds" else 1_048_576,
            transport=transport,
        )
    assert captured.value.reason == reason


def test_fetch_wraps_http_failure_without_response_body() -> None:
    """HTTP失敗を上流本文ごと例外へ流さず、status codeはfailure分類用に保持する。"""
    transport = httpx.MockTransport(lambda _: httpx.Response(503, content=b"internal details"))
    with pytest.raises(PublicFetchError, match="503") as captured:
        _fetch(transport)
    assert "internal details" not in str(captured.value)
    assert captured.value.reason == "http_status"
    assert captured.value.status_code == 503


def test_fetch_reports_timeout_reason_for_classification() -> None:
    """timeoutはfailure分類がRETRYABLEへ倒せるようreason="timeout"を残す。"""

    def respond(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout")

    with pytest.raises(PublicFetchError) as captured:
        _fetch(httpx.MockTransport(respond))
    assert captured.value.reason == "timeout"
