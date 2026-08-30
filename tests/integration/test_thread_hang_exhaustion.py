"""hangしたadapterが全workerを枯渇させる負例を再現する（Issue #8、比較材料）。

これは採用案の実装ではない。#8のUser Gate（subprocess runner／別worker
service／cooperative timeoutのどれを採るか）を判断するための、現状の
実際の失敗形を証拠として残す試験。
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from kuma800.runtime import RuntimePaths

_FIXTURE = Path(__file__).parent / "_thread_hang_fixture.py"


@pytest.mark.process_smoke
def test_two_hung_tasks_starve_all_thread_workers(tmp_path: Path) -> None:
    """`-w 2`の全threadがhangしたtaskへ奪われると、後続の速いtaskが進めない。"""
    paths = RuntimePaths(tmp_path)
    environment = os.environ.copy()
    environment["KUMA800_DATA_DIR"] = str(tmp_path)

    # queue.sqlite3の初回schema作成をconsumer起動前に確定させる。consumerと
    # enqueueが同時に初回作成へ入ると、huey内部で`database is locked`になる
    # 既知の競合があるため、既存testと同じ順序（先にenqueue、後でconsumer
    # 起動）にする。
    for index in range(2):
        enqueue = subprocess.run(
            [sys.executable, str(_FIXTURE), "enqueue", "300", f"started-{index}.marker"],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert enqueue.returncode == 0, enqueue.stderr
    assert (tmp_path / "queue.sqlite3").exists()

    consumer = subprocess.Popen(
        [sys.executable, str(_FIXTURE)],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if consumer.poll() is not None:
                stdout, stderr = consumer.communicate(timeout=1)
                pytest.fail(f"consumer exited early: {stdout}\n{stderr}")
            markers = [(tmp_path / f"started-{index}.marker").exists() for index in range(2)]
            if all(markers):
                break
            time.sleep(0.1)
        else:
            pytest.fail("both worker threads did not start the blocking task in time")

        quick_enqueue = subprocess.run(
            [
                sys.executable,
                "-c",
                "from kuma800.worker.huey_app import scrape_source; "
                "scrape_source('dummy-kuma', 'quick-run')",
            ],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert quick_enqueue.returncode == 0, quick_enqueue.stderr

        # 全threadがhang中のため、速いtaskは短い猶予内では実行されない
        # （timeoutで所有権を強制回収する仕組みが現状ないことの再現）。
        time.sleep(3)
        if not paths.observation_database.exists():
            return
        connection = sqlite3.connect(paths.observation_database)
        try:
            row = connection.execute(
                "SELECT status FROM fetch_runs WHERE run_id = 'quick-run'"
            ).fetchone()
        finally:
            connection.close()
        assert row is None, "全thread枯渇下でも速いtaskが実行されてしまった（再現できず）"
    finally:
        consumer.terminate()
        try:
            consumer.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            consumer.kill()
            consumer.communicate(timeout=5)
