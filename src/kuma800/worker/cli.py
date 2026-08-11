"""cross-platform thread workerを既定にするHuey consumer入口。"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

from huey.bin.huey_consumer import consumer_main  # type: ignore[import-untyped]

from kuma800.runtime import RuntimePaths
from kuma800.storage import ObservationIngestStore, migrate_database

_HUEY_IMPORT_PATH = "kuma800.worker.huey_app.huey"


def main() -> None:
    """stale回収後、thread workerのHuey consumerをforeground起動する。"""
    paths = RuntimePaths.resolve()
    migrate_database(paths.observation_database)
    now = datetime.now(UTC)
    ObservationIngestStore(paths.observation_database).recover_stale(
        before=now - timedelta(minutes=15),
        recovered_at=now,
    )

    supplied = sys.argv[1:]
    defaults: list[str] = []
    if "-k" not in supplied and "--worker-type" not in supplied:
        defaults.extend(("-k", "thread"))
    if "-w" not in supplied and "--workers" not in supplied:
        defaults.extend(("-w", "2"))
    sys.argv = [sys.argv[0], *defaults, *supplied, _HUEY_IMPORT_PATH]
    consumer_main()


if __name__ == "__main__":
    main()
