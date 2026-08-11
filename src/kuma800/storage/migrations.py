"""クマ観測SQLiteのmigrationとread-only接続を提供する。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Migration:
    """順序付きSQLite migration。"""

    version: int
    name: str
    statements: tuple[str, ...]


_INITIAL_SCHEMA = Migration(
    version=1,
    name="initial_observation_store",
    statements=(
        """
        CREATE TABLE sources (
            source_id TEXT PRIMARY KEY,
            source_kind TEXT NOT NULL,
            source_url TEXT NOT NULL,
            created_at TEXT NOT NULL
        ) STRICT
        """,
        """
        CREATE TABLE fetch_runs (
            run_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(source_id),
            status TEXT NOT NULL CHECK (
                status IN ('STARTED', 'SUCCEEDED', 'FAILED', 'STALE')
            ),
            started_at TEXT NOT NULL,
            finished_at TEXT,
            final_url TEXT,
            content_hash TEXT,
            error_code TEXT,
            error_detail TEXT
        ) STRICT
        """,
        """
        CREATE TABLE sightings (
            sighting_id INTEGER PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(source_id),
            source_event_id TEXT NOT NULL,
            source_url TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            event_time TEXT,
            latitude REAL,
            longitude REAL,
            location_precision TEXT NOT NULL,
            input_kind TEXT NOT NULL,
            review_state TEXT NOT NULL,
            animal_kind TEXT NOT NULL,
            count INTEGER CHECK (count IS NULL OR count >= 0),
            original_text TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            fetch_run_id TEXT NOT NULL REFERENCES fetch_runs(run_id),
            created_at TEXT NOT NULL,
            UNIQUE (source_id, source_event_id, content_hash)
        ) STRICT
        """,
        """
        CREATE TABLE sighting_assertions (
            assertion_id INTEGER PRIMARY KEY,
            sighting_id INTEGER NOT NULL REFERENCES sightings(sighting_id),
            assertion_kind TEXT NOT NULL CHECK (
                assertion_kind IN (
                    'reported',
                    'confirmed',
                    'corrected',
                    'retracted',
                    'false_report',
                    'no_longer_present'
                )
            ),
            source_url TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            asserted_at TEXT NOT NULL,
            supersedes_assertion_id INTEGER REFERENCES sighting_assertions(assertion_id),
            fetch_run_id TEXT NOT NULL REFERENCES fetch_runs(run_id),
            UNIQUE (sighting_id, assertion_kind, content_hash)
        ) STRICT
        """,
        """
        CREATE TABLE source_state (
            source_id TEXT PRIMARY KEY REFERENCES sources(source_id),
            last_started_at TEXT,
            last_succeeded_at TEXT,
            next_fetch_at TEXT,
            consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
            backoff_until TEXT,
            last_error_code TEXT
        ) STRICT
        """,
        """
        CREATE TRIGGER sightings_reject_update
        BEFORE UPDATE ON sightings
        BEGIN
            SELECT RAISE(ABORT, 'sightings are append-only');
        END
        """,
        """
        CREATE TRIGGER sightings_reject_delete
        BEFORE DELETE ON sightings
        BEGIN
            SELECT RAISE(ABORT, 'sightings are append-only');
        END
        """,
        """
        CREATE TRIGGER assertions_reject_update
        BEFORE UPDATE ON sighting_assertions
        BEGIN
            SELECT RAISE(ABORT, 'sighting assertions are append-only');
        END
        """,
        """
        CREATE TRIGGER assertions_reject_delete
        BEFORE DELETE ON sighting_assertions
        BEGIN
            SELECT RAISE(ABORT, 'sighting assertions are append-only');
        END
        """,
    ),
)

_MIGRATIONS = (_INITIAL_SCHEMA,)


def _connect_writable(database_path: Path) -> sqlite3.Connection:
    """migrationとcore ingest専用の書込み接続を作る。"""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def migrate_database(database_path: Path) -> tuple[int, ...]:
    """未適用migrationをtransaction内で順番に適用する。"""
    connection = _connect_writable(database_path)
    applied_now: list[int] = []
    try:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                ) STRICT
                """
            )
            applied = {
                row[0] for row in connection.execute("SELECT version FROM schema_migrations")
            }
            for migration in _MIGRATIONS:
                if migration.version in applied:
                    continue
                for statement in migration.statements:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                    (migration.version, migration.name),
                )
                applied_now.append(migration.version)
    finally:
        connection.close()
    return tuple(applied_now)


def open_readonly_database(database_path: Path) -> sqlite3.Connection:
    """AI query面で使用するSQLiteのread-only接続を作る。"""
    resolved = database_path.resolve()
    connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection
