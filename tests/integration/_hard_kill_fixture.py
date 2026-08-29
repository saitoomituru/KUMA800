"""hard-kill再現専用のsubprocess entry point。

productionのscraper registry（`kuma800.worker.service._adapters`）へは公開しない
test専用fixtureで、STARTEDを保存した直後に呼出元がSIGKILLできるよう待機する。
"""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime

from kuma800.domain import SourceDescriptor
from kuma800.runtime import RuntimePaths
from kuma800.storage import ObservationIngestStore, migrate_database


def main() -> None:
    """`source_id run_id block_seconds`を受け取り、STARTED保存後に待機する。"""
    source_id, run_id, block_seconds = sys.argv[1], sys.argv[2], float(sys.argv[3])
    paths = RuntimePaths.resolve()
    migrate_database(paths.observation_database)
    store = ObservationIngestStore(paths.observation_database)
    started_at = datetime.now(UTC)
    store.register_source(
        SourceDescriptor(
            source_id=source_id,
            source_kind="fixture",
            source_url="https://example.invalid/kuma800/hard-kill-fixture",
        ),
        created_at=started_at,
    )
    store.start_fetch(source_id, started_at=started_at, run_id=run_id)
    time.sleep(block_seconds)


if __name__ == "__main__":
    main()
