"""破壊的DB操作前dump（設計判断0005）のallow-list境界を検証する。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from kuma800.storage import UnexpectedTableError, dump_database, migrate_database


def test_dump_exports_schema_and_data(tmp_path: Path) -> None:
    """許可済みtableだけで構成されたDBはschemaとdataをSQLへexportできる。"""
    database_path = tmp_path / "kuma.sqlite3"
    migrate_database(database_path)
    connection = sqlite3.connect(database_path)
    try:
        with connection:
            connection.execute(
                """
                INSERT INTO sources(source_id, source_kind, source_url, created_at)
                VALUES ('fake', 'fixture', 'https://example.invalid/kuma', '2026-08-30T00:00:00Z')
                """
            )
    finally:
        connection.close()

    output_path = tmp_path / "snapshot.sql"
    dump_database(database_path, output_path)

    dump_text = output_path.read_text(encoding="utf-8")
    assert "CREATE TABLE sources" in dump_text
    assert 'INSERT INTO "sources"' in dump_text
    assert "fake" in dump_text


def test_dump_rejects_unexpected_table(tmp_path: Path) -> None:
    """allow-list外のtableが存在する場合はexportせずエラーで停止する。"""
    database_path = tmp_path / "kuma.sqlite3"
    migrate_database(database_path)
    connection = sqlite3.connect(database_path)
    try:
        with connection:
            connection.execute(
                "CREATE TABLE user_secret_location (user_id TEXT, latitude REAL, longitude REAL)"
            )
    finally:
        connection.close()

    output_path = tmp_path / "snapshot.sql"
    with pytest.raises(UnexpectedTableError, match="user_secret_location"):
        dump_database(database_path, output_path)
    assert not output_path.exists()


def test_dump_rejects_sqlite_binary_output_path(tmp_path: Path) -> None:
    """dump先へsqlite binary相当のpathを渡すことを拒否する。"""
    database_path = tmp_path / "kuma.sqlite3"
    migrate_database(database_path)

    with pytest.raises(ValueError, match="binary"):
        dump_database(database_path, tmp_path / "snapshot.sqlite3")
