"""queueと観測正本の分離・起動時回収を検証する。"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from huey import SqliteHuey  # type: ignore[import-untyped]

from kuma800.domain import FetchRunStatus, SourceDescriptor
from kuma800.runtime import RuntimePaths
from kuma800.storage import ObservationIngestStore, migrate_database
from kuma800.worker import execute_scrape


@pytest.mark.process_smoke
def test_worker_startup_recovers_abandoned_fetch_run(tmp_path: Path) -> None:
    """worker相当processが残した古いSTARTEDを次consumer起動時にSTALEへする。"""
    paths = RuntimePaths(tmp_path)
    migrate_database(paths.observation_database)
    store = ObservationIngestStore(paths.observation_database)
    abandoned_at = datetime(2026, 8, 11, 1, 0, tzinfo=UTC)
    store.register_source(
        SourceDescriptor(
            source_id="abandoned",
            source_kind="fixture",
            source_url="https://example.invalid/kuma800/abandoned",
        ),
        created_at=abandoned_at,
    )
    store.start_fetch("abandoned", started_at=abandoned_at, run_id="abandoned-run")

    environment = os.environ.copy()
    environment["KUMA800_DATA_DIR"] = str(tmp_path)
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
            connection = sqlite3.connect(paths.observation_database)
            try:
                status = connection.execute(
                    "SELECT status FROM fetch_runs WHERE run_id = 'abandoned-run'"
                ).fetchone()
            finally:
                connection.close()
            if status == (FetchRunStatus.STALE.value,):
                break
            time.sleep(0.1)
        else:
            pytest.fail("consumer did not recover abandoned fetch run")
    finally:
        consumer.terminate()
        try:
            consumer.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            consumer.kill()
            consumer.communicate(timeout=5)


def test_queue_recreation_does_not_delete_observation_store(tmp_path: Path) -> None:
    """再作成可能queueを失っても追記済み観測正本を保持する。"""
    paths = RuntimePaths(tmp_path)
    execute_scrape("dummy-kuma", paths=paths)
    queue = SqliteHuey("test", filename=str(paths.queue_database), results=True)
    assert queue.pending_count() == 0
    paths.queue_database.unlink()
    recreated = SqliteHuey("test", filename=str(paths.queue_database), results=True)
    assert recreated.pending_count() == 0

    connection = sqlite3.connect(paths.observation_database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM sightings").fetchone() == (1,)
    finally:
        connection.close()
