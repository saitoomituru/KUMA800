"""cross-platform thread workerを既定にするHuey consumer入口。"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

from huey.bin.huey_consumer import consumer_main  # type: ignore[import-untyped]

from kuma800.runtime import RuntimePaths
from kuma800.storage import ObservationIngestStore, migrate_database

_HUEY_IMPORT_PATH = "kuma800.worker.huey_app.huey"


def build_consumer_argv(supplied: list[str]) -> list[str]:
    """huey_consumerへ渡すargvを組み立てる。

    periodic taskのenqueue元を増やさないため、既定ではperiodic schedulerを無効化
    する（huey_consumerの`-n`相当）。ownerにする場合だけ`--periodic-owner`を明示
    する。
    """
    remaining = list(supplied)
    periodic_owner = "--periodic-owner" in remaining
    if periodic_owner:
        remaining = [argument for argument in remaining if argument != "--periodic-owner"]

    defaults: list[str] = []
    if "-k" not in remaining and "--worker-type" not in remaining:
        defaults.extend(("-k", "thread"))
    if "-w" not in remaining and "--workers" not in remaining:
        defaults.extend(("-w", "2"))
    if not periodic_owner and "-n" not in remaining and "--no-periodic" not in remaining:
        defaults.append("-n")
    return [*defaults, *remaining, _HUEY_IMPORT_PATH]


def main() -> None:
    """stale回収後、thread workerのHuey consumerをforeground起動する。"""
    paths = RuntimePaths.resolve()
    migrate_database(paths.observation_database)
    now = datetime.now(UTC)
    ObservationIngestStore(paths.observation_database).recover_stale(
        before=now - timedelta(minutes=15),
        recovered_at=now,
    )

    sys.argv = [sys.argv[0], *build_consumer_argv(sys.argv[1:])]
    consumer_main()


if __name__ == "__main__":
    main()
