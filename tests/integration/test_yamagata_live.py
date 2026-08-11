"""山形県公開面へ接続する明示live probe。"""

from datetime import UTC, datetime

import pytest

from kuma800.scrapers import YamagataCsvAdapter


@pytest.mark.live
def test_yamagata_csv_live_contract() -> None:
    """県ページから最新CSVを発見して現行schemaを候補化する。"""
    batch = YamagataCsvAdapter().fetch(fetched_at=datetime.now(UTC))

    assert batch.final_url.startswith("https://www.pref.yamagata.jp/")
    assert batch.content_hash.startswith("sha256:")
    assert len(batch.candidates) > 0
