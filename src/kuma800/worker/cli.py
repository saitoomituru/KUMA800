"""cross-platform thread workerを既定にするHuey consumer入口。"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

from huey.bin.huey_consumer import consumer_main  # type: ignore[import-untyped]

from kuma800.runtime import RuntimePaths
from kuma800.storage import migrate_database
from kuma800.worker.periodic_owner import PeriodicOwnerLock
from kuma800.worker.service import recover_and_retry_stale

_HUEY_IMPORT_PATH = "kuma800.worker.huey_app.huey"


def build_consumer_argv(supplied: list[str], *, periodic_owner: bool) -> list[str]:
    """huey_consumerへ渡すargvを組み立てる。

    `periodic_owner`は`PeriodicOwnerLock`で実際に確定した結果を渡す。`--periodic-
    owner`が指定されただけでは足りない。file lockを取れなかったprocessは、
    複数workerが同時に指定していてもnon-ownerへ縮退させる。
    """
    remaining = [argument for argument in supplied if argument != "--periodic-owner"]

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
    recover_and_retry_stale(paths, before=now - timedelta(minutes=15), recovered_at=now)

    supplied = sys.argv[1:]
    requested_owner = "--periodic-owner" in supplied
    # lock objectをここで変数保持する。try_acquire()の戻り値（bool）だけを
    # 束縛すると、lock objectの参照が即座に切れてGCでfdが閉じ、flockが解放
    # されてしまう。consumer_main()はforegroundでblockし続けるため、この
    # 変数への参照は保持され続ける。
    periodic_owner_lock = PeriodicOwnerLock(paths)
    periodic_owner = periodic_owner_lock.try_acquire() if requested_owner else False

    sys.argv = [sys.argv[0], *build_consumer_argv(supplied, periodic_owner=periodic_owner)]
    consumer_main()


if __name__ == "__main__":
    main()
