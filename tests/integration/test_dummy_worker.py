"""DUMMY-KUMA workerのprocess境界を検証する。"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kuma800.runtime import RuntimePaths
from kuma800.worker import execute_scrape


def test_execute_scrape_is_idempotent_across_runs(tmp_path: Path) -> None:
    """別runで同じDUMMY観測を取得しても正本は一件に保つ。"""
    paths = RuntimePaths(tmp_path)
    first = execute_scrape("dummy-kuma", paths=paths, now=datetime(2026, 8, 11, 14, 0, tzinfo=UTC))
    second = execute_scrape("dummy-kuma", paths=paths, now=datetime(2026, 8, 11, 14, 1, tzinfo=UTC))

    assert first.inserted_count == 1
    assert second.inserted_count == 0
    connection = sqlite3.connect(paths.observation_database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM sightings").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM fetch_runs").fetchone() == (2,)
        assert connection.execute(
            "SELECT COUNT(*) FROM fetch_runs "
            "WHERE final_url IS NOT NULL AND content_hash IS NOT NULL"
        ).fetchone() == (2,)
    finally:
        connection.close()


def test_execute_scrape_preserves_requested_run_id(tmp_path: Path) -> None:
    """MCPが先に発行したIDをfetch logの追跡IDとして保存する。"""
    paths = RuntimePaths(tmp_path)

    result = execute_scrape("dummy-kuma", paths=paths, run_id="requested-run")

    assert result.run_id == "requested-run"
    connection = sqlite3.connect(paths.observation_database)
    try:
        assert connection.execute(
            "SELECT run_id, status FROM fetch_runs WHERE run_id = 'requested-run'"
        ).fetchone() == ("requested-run", "SUCCEEDED")
    finally:
        connection.close()


@pytest.mark.process_smoke
def test_huey_consumer_process_moves_queue_to_observation_store(tmp_path: Path) -> None:
    """別processのthread consumerが永続queueからDUMMY観測を処理する。"""
    environment = os.environ.copy()
    environment["KUMA800_DATA_DIR"] = str(tmp_path)
    enqueue = subprocess.run(
        [
            sys.executable,
            "-c",
            "from kuma800.worker.huey_app import scrape_source; "
            "scrape_source('dummy-kuma', 'process-run')",
        ],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert enqueue.returncode == 0, enqueue.stderr
    assert (tmp_path / "queue.sqlite3").exists()

    consumer = subprocess.Popen(
        [sys.executable, "-m", "kuma800.worker.cli", "-w", "1", "-k", "thread"],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 10
    try:
        while time.monotonic() < deadline:
            if consumer.poll() is not None:
                stdout, stderr = consumer.communicate(timeout=1)
                pytest.fail(f"consumer exited early: {stdout}\n{stderr}")
            database_path = tmp_path / "kuma.sqlite3"
            if database_path.exists():
                connection = sqlite3.connect(database_path)
                try:
                    try:
                        row = connection.execute("SELECT COUNT(*) FROM sightings").fetchone()
                    except sqlite3.OperationalError as error:
                        if "no such table" not in str(error):
                            raise
                        row = None
                finally:
                    connection.close()
                if row == (1,):
                    break
            time.sleep(0.1)
        else:
            pytest.fail("consumer did not ingest DUMMY-KUMA before timeout")
    finally:
        consumer.terminate()
        try:
            consumer.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            consumer.kill()
            consumer.communicate(timeout=5)

    connection = sqlite3.connect(tmp_path / "kuma.sqlite3")
    try:
        assert connection.execute(
            "SELECT run_id, status FROM fetch_runs WHERE run_id = 'process-run'"
        ).fetchone() == ("process-run", "SUCCEEDED")
    finally:
        connection.close()
