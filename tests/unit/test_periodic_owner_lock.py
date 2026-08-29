"""PeriodicOwnerLockの単一process内での排他挙動を検証する。"""

from __future__ import annotations

from pathlib import Path

from kuma800.runtime import RuntimePaths
from kuma800.worker.periodic_owner import PeriodicOwnerLock


def test_second_lock_fails_while_first_is_held(tmp_path: Path) -> None:
    """同じdata_dirへの二つ目のlock要求は、一つ目が保持中の間は失敗する。"""
    paths = RuntimePaths(tmp_path)
    first = PeriodicOwnerLock(paths)
    second = PeriodicOwnerLock(paths)

    assert first.try_acquire() is True
    assert second.try_acquire() is False


def test_lock_is_reacquirable_after_release(tmp_path: Path) -> None:
    """lockはprocess終了相当（解放）後は別holderへ再取得できる。"""
    paths = RuntimePaths(tmp_path)
    first = PeriodicOwnerLock(paths)
    second = PeriodicOwnerLock(paths)

    assert first.try_acquire() is True
    first.release()

    assert second.try_acquire() is True
