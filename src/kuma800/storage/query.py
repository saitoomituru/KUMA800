"""AIへ公開できる固定read-only query。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .migrations import open_readonly_database


def observation_status(database_path: Path) -> dict[str, object]:
    """観測DBの件数とsource状態を返す。"""
    if not database_path.exists():
        return {
            "initialized": False,
            "sighting_count": 0,
            "fetch_run_count": 0,
            "sources": [],
        }
    connection = open_readonly_database(database_path)
    connection.row_factory = sqlite_dict_row
    try:
        sources = connection.execute(
            """
            SELECT s.source_id, s.source_kind, s.source_url,
                   ss.last_started_at, ss.last_succeeded_at, ss.next_fetch_at,
                   ss.consecutive_failures, ss.backoff_until, ss.last_error_code
            FROM sources AS s
            LEFT JOIN source_state AS ss USING (source_id)
            ORDER BY s.source_id
            """
        ).fetchall()
        return {
            "initialized": True,
            "sighting_count": _scalar_count(connection, "sightings"),
            "fetch_run_count": _scalar_count(connection, "fetch_runs"),
            "sources": [dict(row) for row in sources],
        }
    finally:
        connection.close()


def recent_sightings(database_path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    """新しい観測を原典・fetch run付きで返す。"""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if not database_path.exists():
        return []
    connection = open_readonly_database(database_path)
    connection.row_factory = sqlite_dict_row
    try:
        rows = connection.execute(
            """
            SELECT sighting_id, source_id, source_event_id, source_url,
                   fetched_at, event_time, latitude, longitude, location_precision,
                   input_kind, review_state, animal_kind, count, original_text,
                   content_hash, fetch_run_id, created_at
            FROM sightings
            ORDER BY fetched_at DESC, sighting_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def recent_fetch_runs(database_path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    """新しいscraping logをsourceと結果付きで返す。"""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if not database_path.exists():
        return []
    connection = open_readonly_database(database_path)
    connection.row_factory = sqlite_dict_row
    try:
        rows = connection.execute(
            """
            SELECT run_id, source_id, status, started_at, finished_at, final_url,
                   content_hash, error_code, error_detail
            FROM fetch_runs
            ORDER BY started_at DESC, run_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def sqlite_dict_row(cursor: sqlite3.Cursor, row: tuple[object, ...]) -> dict[str, object]:
    """sqlite rowをJSON化可能なdictへ変換する。"""
    description = cursor.description
    return {str(column[0]): row[index] for index, column in enumerate(description)}


def _scalar_count(connection: Any, table_name: str) -> int:
    """内部固定tableの件数を返す。table名は外部入力にしない。"""
    row = connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
    if row is None:
        raise RuntimeError(f"cannot count table: {table_name}")
    return int(next(iter(row.values())))
