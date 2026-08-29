"""複数workerが同時にperiodic ownerを要求しても排他され、双方生存し続けることを検証する。"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from filelock import FileLock, Timeout

from kuma800.runtime import RuntimePaths


def _start_consumer(environment: dict[str, str]) -> subprocess.Popen[str]:
    """`--periodic-owner`付きでconsumer processを起動する。"""
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "kuma800.worker.cli",
            "-w",
            "1",
            "-k",
            "thread",
            "--periodic-owner",
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _terminate(process: subprocess.Popen[str]) -> None:
    """テスト終了時にconsumer processを片付ける。"""
    process.terminate()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=5)


@pytest.mark.process_smoke
def test_two_periodic_owner_requests_yield_exactly_one_lock_holder(tmp_path: Path) -> None:
    """二つのworkerへ明示的に`--periodic-owner`を渡しても、lockは一つだけが保持し、両方とも生存し続ける。"""
    environment = os.environ.copy()
    environment["KUMA800_DATA_DIR"] = str(tmp_path)
    lock_path = RuntimePaths(tmp_path).data_dir / "periodic-owner.lock"

    first = _start_consumer(environment)
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not lock_path.exists():
            if first.poll() is not None:
                stdout, stderr = first.communicate(timeout=1)
                pytest.fail(f"first consumer exited early: {stdout}\n{stderr}")
            time.sleep(0.1)
        if not lock_path.exists():
            pytest.fail("first consumer did not create the periodic owner lock in time")
        time.sleep(0.5)  # firstのacquire()完了を待つ猶予

        second = _start_consumer(environment)
        try:
            time.sleep(1.0)  # secondのlock試行が完了する猶予

            assert first.poll() is None, "lockを保持したprocessは生存し続ける"
            assert second.poll() is None, "lockを取れなかったprocessもnon-ownerとして生存し続ける"

            probe = FileLock(str(lock_path))
            with pytest.raises(Timeout):
                probe.acquire(timeout=0)
        finally:
            _terminate(second)
    finally:
        _terminate(first)
