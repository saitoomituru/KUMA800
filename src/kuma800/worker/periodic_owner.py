"""periodic ownerの排他をprocess生存期間で保証するfile lock契約。

macOS/Windows双方で複数worker processが同時に稼働しうる（複数MCP client、
複数user環境）前提のため、「未指定workerはownerにならない」という既定値
だけでなく、明示的に`--periodic-owner`を渡すprocessが複数あっても
periodic schedulerを持つのは一つに強制する。lockを取れなかったprocessは
起動失敗にせず、non-ownerへ縮退してconsumerとしては動き続ける。
"""

from __future__ import annotations

import logging

from filelock import FileLock, Timeout

from kuma800.runtime import RuntimePaths

_LOGGER = logging.getLogger(__name__)


class PeriodicOwnerLock:
    """`data_dir`ごとに一つだけ確定するperiodic owner file lock。"""

    def __init__(self, paths: RuntimePaths) -> None:
        """lock対象pathを`paths.data_dir`配下へ固定する。"""
        self._lock = FileLock(str(paths.data_dir / "periodic-owner.lock"))

    def try_acquire(self) -> bool:
        """即時取得できた場合だけTrueを返す。

        取得できない場合は例外にせず、そのprocessをnon-ownerとして継続させる
        （複数workerが同時に`--periodic-owner`を要求しても、どちらもconsumer
        としては生存し続ける）。
        """
        try:
            self._lock.acquire(timeout=0)
        except Timeout:
            _LOGGER.warning(
                "periodic ownerは既に別processが保持しているためnon-ownerとして起動する"
            )
            return False
        return True

    def release(self) -> None:
        """保持中のlockを明示的に解放する（主にtest用）。"""
        self._lock.release()
