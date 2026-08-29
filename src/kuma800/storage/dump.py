"""Dev期の破壊的DB操作前に`kuma.sqlite3`を人間審査可能な形でexportする。

運用ルールの正本は[設計判断0005](../../../docs/decisions/0005-Dev期の既存DB破壊的操作前にdumpを残す.ja.md)。
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import tempfile
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

# 意図的にmigrations.pyのtable定義から自動導出しない。schemaへtableを追加しても
# ここを人間が明示的に更新するまでdumpは失敗する（設計判断0005のfail-closed境界）。
_ALLOWED_TABLES = frozenset(
    {
        "sources",
        "fetch_runs",
        "sightings",
        "sighting_assertions",
        "source_state",
        "schema_migrations",
    }
)

_FORBIDDEN_OUTPUT_SUFFIXES = (".sqlite3", ".sqlite3-shm", ".sqlite3-wal")


class UnexpectedTableError(RuntimeError):
    """allow-listにないtableを検出し、dumpを拒否したことを表す。"""


def _user_table_names(connection: sqlite3.Connection) -> frozenset[str]:
    """sqlite内部table等を除いた、利用者定義tableの名前集合を返す。"""
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return frozenset(row[0] for row in rows)


def dump_database(database_path: Path, output_path: Path) -> None:
    """`database_path`の構造とデータをSQLテキストとして`output_path`へ原子書き出しする。

    allow-list外のtableが見つかった場合はexportせず`UnexpectedTableError`を送出する。
    """
    if output_path.suffix in _FORBIDDEN_OUTPUT_SUFFIXES:
        raise ValueError(f"dump出力先へsqlite binary相当のpathは使えない: {output_path}")

    connection = sqlite3.connect(f"{database_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        found = _user_table_names(connection)
        unexpected = found - _ALLOWED_TABLES
        if unexpected:
            raise UnexpectedTableError(
                f"allow-listにないtableを検出したためdumpを拒否した: {sorted(unexpected)}"
            )
        dump_text = "\n".join(connection.iterdump())
    finally:
        connection.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(dump_text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> None:
    """CLIから`kuma.sqlite3`をdumpする。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    output = arguments.output.expanduser().resolve()
    dump_database(arguments.database.expanduser().resolve(), output)
    _LOGGER.info("%s", output)


if __name__ == "__main__":
    main()
