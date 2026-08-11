"""クマ観測SQLiteのmigrationと不変条件を検証する。"""

import sqlite3
from pathlib import Path

import pytest

from kuma800.storage import migrate_database, open_readonly_database


def _seed_observation(database_path: Path) -> None:
    """trigger検査用の出典付き観測を一件作る。"""
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            connection.execute(
                """
                INSERT INTO sources(source_id, source_kind, source_url, created_at)
                VALUES ('fake', 'fixture', 'https://example.invalid/kuma', '2026-08-11T00:00:00Z')
                """
            )
            connection.execute(
                """
                INSERT INTO fetch_runs(run_id, source_id, status, started_at, finished_at)
                VALUES (
                    'run-1',
                    'fake',
                    'SUCCEEDED',
                    '2026-08-11T00:00:00Z',
                    '2026-08-11T00:00:01Z'
                )
                """
            )
            cursor = connection.execute(
                """
                INSERT INTO sightings(
                    source_id,
                    source_event_id,
                    source_url,
                    fetched_at,
                    location_precision,
                    input_kind,
                    review_state,
                    animal_kind,
                    original_text,
                    content_hash,
                    fetch_run_id,
                    created_at
                ) VALUES (
                    'fake',
                    'event-1',
                    'https://example.invalid/kuma',
                    '2026-08-11T00:00:01Z',
                    'unknown',
                    'fixture',
                    'unknown',
                    'bear',
                    'DUMMY-KUMA',
                    'sha256:dummy',
                    'run-1',
                    '2026-08-11T00:00:01Z'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO sighting_assertions(
                    sighting_id,
                    assertion_kind,
                    source_url,
                    content_hash,
                    asserted_at,
                    fetch_run_id
                ) VALUES (?, 'reported', 'https://example.invalid/kuma', 'sha256:dummy',
                          '2026-08-11T00:00:01Z', 'run-1')
                """,
                (cursor.lastrowid,),
            )
    finally:
        connection.close()


def test_migration_is_idempotent(tmp_path: Path) -> None:
    """初回だけmigrationが適用され、再実行でschemaを作り直さない。"""
    database_path = tmp_path / "kuma.sqlite3"

    assert migrate_database(database_path) == (1, 2)
    assert migrate_database(database_path) == ()

    connection = sqlite3.connect(database_path)
    try:
        versions = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        connection.close()

    assert versions == [
        (1, "initial_observation_store"),
        (2, "single_flight_fetch_runs"),
    ]
    assert {
        "sources",
        "fetch_runs",
        "sightings",
        "sighting_assertions",
        "source_state",
    }.issubset(tables)


def test_ai_read_connection_rejects_writes(tmp_path: Path) -> None:
    """公開予定のread-only接続がSQLite書込みを拒否する。"""
    database_path = tmp_path / "kuma.sqlite3"
    migrate_database(database_path)

    connection = open_readonly_database(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM sightings").fetchone() == (0,)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute(
                """
                INSERT INTO sources(source_id, source_kind, source_url, created_at)
                VALUES ('villain', 'manual', 'https://example.invalid', '2026-08-11T00:00:00Z')
                """
            )
    finally:
        connection.close()


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_observations_are_append_only(tmp_path: Path, operation: str) -> None:
    """内部write接続でも観測の更新と削除をtriggerで拒否する。"""
    database_path = tmp_path / "kuma.sqlite3"
    migrate_database(database_path)
    _seed_observation(database_path)

    connection = sqlite3.connect(database_path)
    try:
        statement = (
            "UPDATE sightings SET original_text = 'burned' WHERE sighting_id = 1"
            if operation == "UPDATE"
            else "DELETE FROM sightings WHERE sighting_id = 1"
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(statement)
    finally:
        connection.close()
