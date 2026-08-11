"""山形県ページから現行CSV snapshotを発見・正規化するadapter。"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import datetime, time, timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

from kuma800.domain import (
    AssertionKind,
    CandidateObservation,
    ReviewState,
    ScrapeBatch,
    SourceDescriptor,
)

from .http import fetch_public_artifact

YAMAGATA_PAGE_URL = (
    "https://www.pref.yamagata.jp/050011/kurashi/shizen/seibutsu/about_kuma/kuma_yamagata_top.html"
)
_ALLOWED_HOSTS = frozenset({"www.pref.yamagata.jp"})
_CSV_PATH = re.compile(r"/(\d{8})_kemonote-cleaned\.csv$")
_TOKYO = ZoneInfo("Asia/Tokyo")
_HEADERS = (
    "投稿日",
    "グループ名",
    "ユーザ名",
    "緯度",
    "経度",
    "第 1 次地域区画(80km)",
    "第 2 次地域区画(10km)",
    "2 倍地域メッシュ(2km)",
    "基準地域メッシュ(1km)",
    "2 分の 1 地域メッシュ(500m)",
    "4 分の 1 地域メッシュ(250m)",
    "8 分の 1 地域メッシュ(125m)",
    "目撃した日付",
    "目撃した時間帯（0:00～24:00）",
    "地名等",
    "市街地（半径200m以内に人家が10軒以上）かどうか",
    "周辺環境",
    "目撃頭数",
    "個体の大きさ等",
    "備考",
)
_EXCLUDED_IDENTITY_FIELDS = frozenset({"グループ名", "ユーザ名"})


class _LinkCollector(HTMLParser):
    """HTMLからhrefだけを収集する。"""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """anchorのhrefを保存する。"""
        if tag.lower() != "a":
            return
        href = next((value for key, value in attrs if key.lower() == "href"), None)
        if href:
            self.links.append(href)


def discover_latest_csv(page_content: bytes, *, page_url: str) -> str:
    """県ページ内の日付付きcleaned CSVから最新URLを選ぶ。"""
    parser = _LinkCollector()
    parser.feed(page_content.decode("utf-8-sig"))
    candidates: list[tuple[str, str]] = []
    for href in parser.links:
        absolute = urljoin(page_url, href)
        parsed = urlparse(absolute)
        match = _CSV_PATH.search(parsed.path)
        if parsed.scheme == "https" and parsed.hostname in _ALLOWED_HOSTS and match:
            candidates.append((match.group(1), absolute))
    if not candidates:
        raise ValueError("Yamagata page does not contain a dated cleaned CSV link")
    return max(candidates)[1]


def _parse_event_time(date_text: str, hour_text: str) -> datetime:
    """日付と0:00–24:00の時間帯をAsia/Tokyo datetimeへ変換する。"""
    event_date = datetime.strptime(date_text, "%Y/%m/%d").date()
    hour, minute = (int(part) for part in hour_text.split(":", 1))
    if hour == 24 and minute == 0:
        return datetime.combine(event_date + timedelta(days=1), time(), tzinfo=_TOKYO)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"invalid sighting time: {hour_text}")
    return datetime.combine(event_date, time(hour, minute), tzinfo=_TOKYO)


def _canonical_hash(value: object) -> str:
    """JSON化可能値の安定SHA-256を返す。"""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def parse_yamagata_csv(
    content: bytes,
    *,
    source_url: str,
    fetched_at: datetime,
) -> tuple[CandidateObservation, ...]:
    """現行schemaを検証し、公開者識別欄を除外して候補へ変換する。"""
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""))
    if tuple(reader.fieldnames or ()) != _HEADERS:
        raise ValueError("Yamagata CSV schema changed")
    candidates: list[CandidateObservation] = []
    for index, row in enumerate(reader, start=2):
        if index > 10_001:
            raise ValueError("Yamagata CSV row count exceeds limit")
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"malformed Yamagata CSV row: {index}")
        retained = {
            key: value for key, value in row.items() if key not in _EXCLUDED_IDENTITY_FIELDS
        }
        event_identity = {
            key: retained[key]
            for key in (
                "投稿日",
                "緯度",
                "経度",
                "目撃した日付",
                "目撃した時間帯（0:00～24:00）",
                "地名等",
            )
        }
        safety_text = {
            key: retained[key]
            for key in (
                "地名等",
                "市街地（半径200m以内に人家が10軒以上）かどうか",
                "周辺環境",
                "目撃頭数",
                "個体の大きさ等",
                "備考",
            )
        }
        candidates.append(
            CandidateObservation(
                source_id="yamagata-r8-csv",
                source_event_id=_canonical_hash(event_identity).removeprefix("sha256:"),
                source_url=source_url,
                fetched_at=fetched_at,
                event_time=_parse_event_time(
                    retained["目撃した日付"],
                    retained["目撃した時間帯（0:00～24:00）"],
                ),
                latitude=float(retained["緯度"]),
                longitude=float(retained["経度"]),
                location_precision="published-point",
                input_kind="yamagata-prefecture-cleaned-csv",
                review_state=ReviewState.REVIEWED_CANDIDATE,
                assertion_kind=AssertionKind.REPORTED,
                animal_kind="bear",
                count=int(retained["目撃頭数"]),
                original_text=json.dumps(safety_text, ensure_ascii=False, separators=(",", ":")),
                content_hash=_canonical_hash(retained),
            )
        )
    return tuple(candidates)


class YamagataCsvAdapter:
    """県ページから最新CSVを毎回発見する非公式公開情報adapter。"""

    @property
    def source(self) -> SourceDescriptor:
        """固定feedではなく発見元の県ページをsourceとして返す。"""
        return SourceDescriptor(
            source_id="yamagata-r8-csv",
            source_kind="administrative-reviewed-snapshot-candidate",
            source_url=YAMAGATA_PAGE_URL,
        )

    def fetch(self, *, fetched_at: datetime) -> ScrapeBatch:
        """県ページ→最新CSVを制限付きで取得して正規化する。"""
        page = fetch_public_artifact(
            self.source.source_url,
            allowed_hosts=_ALLOWED_HOSTS,
            expected_content_types=frozenset({"text/html"}),
        )
        csv_url = discover_latest_csv(page.content, page_url=page.final_url)
        artifact = fetch_public_artifact(
            csv_url,
            allowed_hosts=_ALLOWED_HOSTS,
            expected_content_types=frozenset({"text/csv", "application/octet-stream"}),
        )
        return ScrapeBatch(
            final_url=artifact.final_url,
            content_hash=artifact.content_hash,
            candidates=parse_yamagata_csv(
                artifact.content,
                source_url=artifact.final_url,
                fetched_at=fetched_at,
            ),
        )
