"""出典付き冪等ingestの回帰試験。"""

import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kuma800.domain import (
    AssertionKind,
    CandidateObservation,
    FetchRunStatus,
    ReviewState,
    SourceDescriptor,
    StaleRecovery,
)
from kuma800.storage import FetchAlreadyRunning, ObservationIngestStore, migrate_database

_NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def _hash(value: str) -> str:
    """test入力から正規SHA-256表記を作る。"""
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _candidate() -> CandidateObservation:
    """正常なDUMMY-KUMA候補を作る。"""
    return CandidateObservation(
        source_id="fake",
        source_event_id="event-1",
        source_url="https://example.invalid/kuma",
        fetched_at=_NOW,
        event_time=None,
        latitude=38.0,
        longitude=140.0,
        location_precision="point",
        input_kind="fixture",
        review_state=ReviewState.UNKNOWN,
        assertion_kind=AssertionKind.REPORTED,
        animal_kind="bear",
        count=1,
        original_text="DUMMY-KUMA",
        content_hash=_hash("DUMMY-KUMA"),
    )


def _prepared_store(tmp_path: Path) -> tuple[ObservationIngestStore, Path, str]:
    """migration・source・fetch runを準備する。"""
    database_path = tmp_path / "kuma.sqlite3"
    migrate_database(database_path)
    store = ObservationIngestStore(database_path)
    store.register_source(
        SourceDescriptor(
            source_id="fake",
            source_kind="fixture",
            source_url="https://example.invalid/kuma",
        ),
        created_at=_NOW,
    )
    run_id = store.start_fetch("fake", started_at=_NOW, run_id="run-1")
    return store, database_path, run_id


def test_candidate_validation_rejects_unsafe_ambiguity() -> None:
    """片側座標、naive時刻、不正hashを保存前に拒否する。"""
    base = _candidate()
    with pytest.raises(ValueError, match="provided together"):
        replace(base, longitude=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(base, fetched_at=datetime(2026, 8, 11, 12, 0))
    with pytest.raises(ValueError, match="sha256"):
        replace(base, content_hash="dummy")


def test_ingest_is_idempotent_and_keeps_changed_source_record(tmp_path: Path) -> None:
    """完全重複は一件に保ち、同じsource IDの内容変化は別観測で残す。"""
    store, database_path, run_id = _prepared_store(tmp_path)
    candidate = _candidate()

    first = store.append_candidate(candidate, fetch_run_id=run_id, created_at=_NOW)
    duplicate = store.append_candidate(candidate, fetch_run_id=run_id, created_at=_NOW)
    changed = store.append_candidate(
        replace(
            candidate,
            original_text="DUMMY-KUMA corrected upstream payload",
            content_hash=_hash("DUMMY-KUMA corrected upstream payload"),
        ),
        fetch_run_id=run_id,
        created_at=_NOW,
    )

    assert first.sighting_inserted is True
    assert first.assertion_inserted is True
    assert duplicate.sighting_id == first.sighting_id
    assert duplicate.sighting_inserted is False
    assert duplicate.assertion_inserted is False
    assert changed.sighting_id != first.sighting_id

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM sightings").fetchone() == (2,)
        assert connection.execute("SELECT COUNT(*) FROM sighting_assertions").fetchone() == (2,)
    finally:
        connection.close()


def test_ingest_rejects_fetch_run_from_another_source(tmp_path: Path) -> None:
    """別sourceのfetch runへ候補を混入できない。"""
    store, _, run_id = _prepared_store(tmp_path)

    with pytest.raises(ValueError, match="does not match"):
        store.append_candidate(
            replace(_candidate(), source_id="villain"),
            fetch_run_id=run_id,
            created_at=_NOW,
        )


def test_terminal_fetch_run_cannot_be_finished_twice(tmp_path: Path) -> None:
    """fetch runの終端状態を後発都合で書き換えない。"""
    store, database_path, run_id = _prepared_store(tmp_path)
    store.finish_fetch(
        run_id,
        status=FetchRunStatus.SUCCEEDED,
        finished_at=_NOW,
        final_url="https://example.invalid/kuma",
        content_hash=_hash("artifact"),
    )

    with pytest.raises(ValueError, match="already terminal"):
        store.finish_fetch(
            run_id,
            status=FetchRunStatus.FAILED,
            finished_at=_NOW,
            error_code="LATE_REVISION",
        )

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT status FROM fetch_runs WHERE run_id = ?", (run_id,)
        ).fetchone() == (FetchRunStatus.SUCCEEDED.value,)
    finally:
        connection.close()


def test_source_single_flight_and_stale_recovery(tmp_path: Path) -> None:
    """同じsourceの並行STARTEDを拒否し、期限切れだけ回収する。"""
    store, database_path, run_id = _prepared_store(tmp_path)

    with pytest.raises(FetchAlreadyRunning) as captured:
        store.start_fetch("fake", started_at=_NOW, run_id="run-2")
    assert captured.value.run_id == run_id

    assert store.recover_stale(before=_NOW, recovered_at=_NOW) == ()
    assert store.recover_stale(
        before=datetime(2026, 8, 11, 12, 1, tzinfo=UTC),
        recovered_at=datetime(2026, 8, 11, 12, 2, tzinfo=UTC),
    ) == (StaleRecovery(run_id=run_id, source_id="fake", retryable=True),)

    replacement = store.start_fetch("fake", started_at=_NOW, run_id="run-2")
    assert replacement == "run-2"
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT status, error_code FROM fetch_runs WHERE run_id = ?", (run_id,)
        ).fetchone() == (FetchRunStatus.STALE.value, "STALE_RECOVERY")
    finally:
        connection.close()


def test_start_fetch_records_retry_lineage(tmp_path: Path) -> None:
    """再実行runは旧runへ`retry_of_run_id`で追跡できる。"""
    store, database_path, run_id = _prepared_store(tmp_path)
    store.recover_stale(
        before=datetime(2026, 8, 11, 12, 1, tzinfo=UTC),
        recovered_at=datetime(2026, 8, 11, 12, 2, tzinfo=UTC),
    )

    retry_run_id = store.start_fetch(
        "fake", started_at=_NOW, run_id="run-2", retry_of_run_id=run_id
    )

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT retry_of_run_id FROM fetch_runs WHERE run_id = ?", (retry_run_id,)
        ).fetchone() == (run_id,)
    finally:
        connection.close()


def test_recover_stale_does_not_mark_retry_of_a_retry_as_retryable(tmp_path: Path) -> None:
    """再実行run自身がstaleになっても、無制限retryにならないよう再enqueue対象にしない。"""
    store, _, run_id = _prepared_store(tmp_path)
    store.recover_stale(
        before=datetime(2026, 8, 11, 12, 1, tzinfo=UTC),
        recovered_at=datetime(2026, 8, 11, 12, 2, tzinfo=UTC),
    )
    retry_run_id = store.start_fetch(
        "fake", started_at=_NOW, run_id="run-2", retry_of_run_id=run_id
    )

    recoveries = store.recover_stale(
        before=datetime(2026, 8, 11, 12, 1, tzinfo=UTC),
        recovered_at=datetime(2026, 8, 11, 12, 3, tzinfo=UTC),
    )

    assert recoveries == (StaleRecovery(run_id=retry_run_id, source_id="fake", retryable=False),)
