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
from kuma800.scrapers import DummyKumaAdapter
from kuma800.storage import ObservationIngestStore, migrate_database
from kuma800.worker import execute_scrape

_HARD_KILL_FIXTURE = Path(__file__).parent / "_hard_kill_fixture.py"


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


@pytest.mark.process_smoke
def test_hard_kill_leaves_started_run_for_next_consumer_to_recover(tmp_path: Path) -> None:
    """consumer相当processをSTARTED保存直後にSIGKILLし、STARTEDのまま残ることを確認する。"""
    paths = RuntimePaths(tmp_path)
    environment = os.environ.copy()
    environment["KUMA800_DATA_DIR"] = str(tmp_path)

    process = subprocess.Popen(
        [sys.executable, str(_HARD_KILL_FIXTURE), "hard-kill-fixture", "killed-run", "30"],
        env=environment,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail(f"fixture process exited early with code {process.returncode}")
            connection = sqlite3.connect(paths.observation_database)
            try:
                try:
                    status = connection.execute(
                        "SELECT status FROM fetch_runs WHERE run_id = 'killed-run'"
                    ).fetchone()
                except sqlite3.OperationalError as error:
                    if "no such table" not in str(error):
                        raise
                    status = None
            finally:
                connection.close()
            if status == (FetchRunStatus.STARTED.value,):
                break
            time.sleep(0.1)
        else:
            pytest.fail("fixture process did not persist STARTED before timeout")

        process.kill()  # SIGKILL相当。graceful shutdownを経ずに強制終了する。
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    connection = sqlite3.connect(paths.observation_database)
    try:
        assert connection.execute(
            "SELECT status FROM fetch_runs WHERE run_id = 'killed-run'"
        ).fetchone() == (FetchRunStatus.STARTED.value,)
    finally:
        connection.close()


@pytest.mark.process_smoke
def test_consumer_restart_retries_stale_run_and_converges_sightings(tmp_path: Path) -> None:
    """stale回収後の自動retryが新runとしてSUCCEEDEDし、観測が一件へ収束する。"""
    paths = RuntimePaths(tmp_path)
    migrate_database(paths.observation_database)
    store = ObservationIngestStore(paths.observation_database)
    abandoned_at = datetime(2026, 8, 11, 1, 0, tzinfo=UTC)
    store.register_source(DummyKumaAdapter().source, created_at=abandoned_at)
    old_run_id = "abandoned-dummy-run"
    store.start_fetch("dummy-kuma", started_at=abandoned_at, run_id=old_run_id)

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
                row = connection.execute("SELECT COUNT(*) FROM sightings").fetchone()
            finally:
                connection.close()
            if row == (1,):
                break
            time.sleep(0.1)
        else:
            pytest.fail("consumer did not converge retried run to a single sighting")
    finally:
        consumer.terminate()
        try:
            consumer.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            consumer.kill()
            consumer.communicate(timeout=5)

    connection = sqlite3.connect(paths.observation_database)
    try:
        assert connection.execute(
            "SELECT status FROM fetch_runs WHERE run_id = ?", (old_run_id,)
        ).fetchone() == (FetchRunStatus.STALE.value,)
        retried = connection.execute(
            "SELECT run_id, status FROM fetch_runs WHERE retry_of_run_id = ?", (old_run_id,)
        ).fetchall()
        assert len(retried) == 1
        assert retried[0][1] == FetchRunStatus.SUCCEEDED.value
        assert connection.execute("SELECT COUNT(*) FROM sightings").fetchone() == (1,)
    finally:
        connection.close()


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
