"""山形県cleaned CSV adapter contractのoffline回帰試験。"""

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from kuma800.domain import ReviewState
from kuma800.scrapers.yamagata_csv import discover_latest_csv, parse_yamagata_csv

_NOW = datetime(2026, 8, 11, 20, 0, tzinfo=UTC)
_SOURCE_URL = "https://www.pref.yamagata.jp/documents/2414/20260802_kemonote-cleaned.csv"


def _fixture() -> bytes:
    """個人・実観測を含まない架空CSV fixtureを読む。"""
    path = Path(__file__).parents[1] / "fixtures" / "yamagata_cleaned_minimal.csv"
    return path.read_bytes()


def test_discover_latest_csv_uses_newest_dated_prefecture_link() -> None:
    """県hostのdated cleaned CSVだけから最新を選ぶ。"""
    page = b"""
    <a href="/documents/2414/20260719_kemonote-cleaned.csv">old</a>
    <a href="https://evil.invalid/20269999_kemonote-cleaned.csv">evil</a>
    <a href="/documents/2414/20260802_kemonote-cleaned.csv">new</a>
    """
    assert discover_latest_csv(page, page_url="https://www.pref.yamagata.jp/page.html") == (
        _SOURCE_URL
    )


def test_parse_csv_excludes_publisher_identity_and_handles_24_hour() -> None:
    """公開者識別欄を焼かず、24:00を翌日0時として候補化する。"""
    candidates = parse_yamagata_csv(_fixture(), source_url=_SOURCE_URL, fetched_at=_NOW)

    assert len(candidates) == 2
    assert candidates[0].review_state is ReviewState.REVIEWED_CANDIDATE
    assert candidates[0].latitude == 38.0
    assert candidates[0].count == 1
    assert "架空ユーザ" not in candidates[0].original_text
    assert "架空グループ" not in candidates[0].original_text
    assert candidates[1].event_time == datetime(2026, 8, 2, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))


def test_identity_columns_do_not_change_event_or_content_hash() -> None:
    """group/user名だけの変更を観測内容の改訂として扱わない。"""
    original = parse_yamagata_csv(_fixture(), source_url=_SOURCE_URL, fetched_at=_NOW)[0]
    changed_bytes = (
        _fixture()
        .replace("架空ユーザ".encode(), "公開者変更".encode())
        .replace("架空グループ".encode(), "公開組織変更".encode())
    )
    changed = parse_yamagata_csv(changed_bytes, source_url=_SOURCE_URL, fetched_at=_NOW)[0]

    assert changed.source_event_id == original.source_event_id
    assert changed.content_hash == original.content_hash


def test_parse_rejects_schema_drift_and_non_finite_coordinate() -> None:
    """header driftとNaN座標を黙って保存しない。"""
    with pytest.raises(ValueError, match="schema changed"):
        parse_yamagata_csv(
            _fixture().replace("投稿日".encode(), "投稿日時".encode(), 1),
            source_url=_SOURCE_URL,
            fetched_at=_NOW,
        )
    with pytest.raises(ValueError, match="latitude"):
        parse_yamagata_csv(
            _fixture().replace(b"38.000000", b"NaN", 1),
            source_url=_SOURCE_URL,
            fetched_at=_NOW,
        )
