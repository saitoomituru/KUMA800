"""登録済みscraperだけが使用する出典付きingest経路。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from kuma800.domain import (
    CandidateObservation,
    FetchRunStatus,
    IngestResult,
    SourceDescriptor,
)

from .migrations import _connect_writable


def _as_utc_text(value: datetime) -> str:
    """timezone付き日時をUTCのISO 8601へ正規化する。"""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class ObservationIngestStore:
    """クマ観測DBへの唯一のapplication-level write API。"""

    def __init__(self, database_path: Path) -> None:
        """書込み対象DBを固定する。"""
        self._database_path = database_path

    def register_source(self, source: SourceDescriptor, *, created_at: datetime) -> None:
        """静的情報源を登録し、同じIDの意味差替えを拒否する。"""
        connection = _connect_writable(self._database_path)
        try:
            with connection:
                existing = connection.execute(
                    "SELECT source_kind, source_url FROM sources WHERE source_id = ?",
                    (source.source_id,),
                ).fetchone()
                expected = (source.source_kind, source.source_url)
                if existing is not None and existing != expected:
                    raise ValueError(
                        f"source_id already registered with different meaning: {source.source_id}"
                    )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO sources(source_id, source_kind, source_url, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        source.source_id,
                        source.source_kind,
                        source.source_url,
                        _as_utc_text(created_at),
                    ),
                )
        finally:
            connection.close()

    def start_fetch(
        self,
        source_id: str,
        *,
        started_at: datetime,
        run_id: str | None = None,
    ) -> str:
        """出典取得をSTARTEDとして記録する。"""
        resolved_run_id = run_id or str(uuid4())
        connection = _connect_writable(self._database_path)
        try:
            with connection:
                started_at_text = _as_utc_text(started_at)
                try:
                    connection.execute(
                        """
                        INSERT INTO fetch_runs(run_id, source_id, status, started_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            resolved_run_id,
                            source_id,
                            FetchRunStatus.STARTED.value,
                            started_at_text,
                        ),
                    )
                except sqlite3.IntegrityError as error:
                    active = connection.execute(
                        """
                        SELECT run_id FROM fetch_runs
                        WHERE source_id = ? AND status = 'STARTED'
                        """,
                        (source_id,),
                    ).fetchone()
                    if active is not None:
                        raise FetchAlreadyRunning(source_id, str(active[0])) from error
                    raise
                connection.execute(
                    """
                    INSERT INTO source_state(source_id, last_started_at)
                    VALUES (?, ?)
                    ON CONFLICT(source_id) DO UPDATE SET last_started_at = excluded.last_started_at
                    """,
                    (source_id, started_at_text),
                )
        finally:
            connection.close()
        return resolved_run_id

    def finish_fetch(
        self,
        run_id: str,
        *,
        status: FetchRunStatus,
        finished_at: datetime,
        final_url: str | None = None,
        content_hash: str | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        """STARTED runを終端状態へ遷移させる。"""
        if status is FetchRunStatus.STARTED:
            raise ValueError("finish_fetch requires a terminal status")
        connection = _connect_writable(self._database_path)
        try:
            with connection:
                current = connection.execute(
                    "SELECT status FROM fetch_runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                if current is None:
                    raise KeyError(f"unknown fetch run: {run_id}")
                if current[0] != FetchRunStatus.STARTED.value:
                    raise ValueError(f"fetch run is already terminal: {run_id}")
                connection.execute(
                    """
                    UPDATE fetch_runs
                    SET status = ?, finished_at = ?, final_url = ?, content_hash = ?,
                        error_code = ?, error_detail = ?
                    WHERE run_id = ?
                    """,
                    (
                        status.value,
                        _as_utc_text(finished_at),
                        final_url,
                        content_hash,
                        error_code,
                        error_detail,
                        run_id,
                    ),
                )
                if status is FetchRunStatus.SUCCEEDED:
                    connection.execute(
                        """
                        UPDATE source_state
                        SET last_succeeded_at = ?, consecutive_failures = 0,
                            backoff_until = NULL, last_error_code = NULL
                        WHERE source_id = (
                            SELECT source_id FROM fetch_runs WHERE run_id = ?
                        )
                        """,
                        (_as_utc_text(finished_at), run_id),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE source_state
                        SET consecutive_failures = consecutive_failures + 1,
                            last_error_code = ?
                        WHERE source_id = (
                            SELECT source_id FROM fetch_runs WHERE run_id = ?
                        )
                        """,
                        (error_code or status.value, run_id),
                    )
        finally:
            connection.close()

    def recover_stale(self, *, before: datetime, recovered_at: datetime) -> tuple[str, ...]:
        """期限より古いSTARTED runをSTALEへ遷移させる。"""
        connection = _connect_writable(self._database_path)
        stale_run_ids: list[str] = []
        try:
            with connection:
                rows = connection.execute(
                    """
                    SELECT run_id FROM fetch_runs
                    WHERE status = 'STARTED' AND started_at < ?
                    ORDER BY started_at, run_id
                    """,
                    (_as_utc_text(before),),
                ).fetchall()
                for row in rows:
                    run_id = str(row[0])
                    self._finish_stale(connection, run_id, recovered_at)
                    stale_run_ids.append(run_id)
        finally:
            connection.close()
        return tuple(stale_run_ids)

    @staticmethod
    def _finish_stale(connection: sqlite3.Connection, run_id: str, recovered_at: datetime) -> None:
        """同じtransaction内でstale runとsource状態を更新する。"""
        connection.execute(
            """
            UPDATE fetch_runs
            SET status = 'STALE', finished_at = ?, error_code = 'STALE_RECOVERY'
            WHERE run_id = ? AND status = 'STARTED'
            """,
            (_as_utc_text(recovered_at), run_id),
        )
        connection.execute(
            """
            UPDATE source_state
            SET consecutive_failures = consecutive_failures + 1,
                last_error_code = 'STALE_RECOVERY'
            WHERE source_id = (SELECT source_id FROM fetch_runs WHERE run_id = ?)
            """,
            (run_id,),
        )

    def append_candidate(
        self,
        candidate: CandidateObservation,
        *,
        fetch_run_id: str,
        created_at: datetime,
    ) -> IngestResult:
        """観測候補と主張を同一transactionで冪等appendする。"""
        connection = _connect_writable(self._database_path)
        try:
            with connection:
                run = connection.execute(
                    "SELECT source_id, status FROM fetch_runs WHERE run_id = ?",
                    (fetch_run_id,),
                ).fetchone()
                if run is None:
                    raise KeyError(f"unknown fetch run: {fetch_run_id}")
                if run[0] != candidate.source_id:
                    raise ValueError("fetch run source does not match candidate source")
                if run[1] not in {
                    FetchRunStatus.STARTED.value,
                    FetchRunStatus.SUCCEEDED.value,
                }:
                    raise ValueError("failed or stale fetch run cannot ingest observations")

                sighting_cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO sightings(
                        source_id, source_event_id, source_url, fetched_at, event_time,
                        latitude, longitude, location_precision, input_kind, review_state,
                        animal_kind, count, original_text, content_hash, fetch_run_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate.source_id,
                        candidate.source_event_id,
                        candidate.source_url,
                        _as_utc_text(candidate.fetched_at),
                        _as_utc_text(candidate.event_time) if candidate.event_time else None,
                        candidate.latitude,
                        candidate.longitude,
                        candidate.location_precision,
                        candidate.input_kind,
                        candidate.review_state.value,
                        candidate.animal_kind,
                        candidate.count,
                        candidate.original_text,
                        candidate.content_hash,
                        fetch_run_id,
                        _as_utc_text(created_at),
                    ),
                )
                sighting_inserted = sighting_cursor.rowcount == 1
                sighting_row = connection.execute(
                    """
                    SELECT sighting_id FROM sightings
                    WHERE source_id = ? AND source_event_id = ? AND content_hash = ?
                    """,
                    (
                        candidate.source_id,
                        candidate.source_event_id,
                        candidate.content_hash,
                    ),
                ).fetchone()
                if sighting_row is None:
                    raise RuntimeError("sighting insert was not observable in its transaction")
                sighting_id = int(sighting_row[0])

                assertion_cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO sighting_assertions(
                        sighting_id, assertion_kind, source_url, content_hash,
                        asserted_at, fetch_run_id
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sighting_id,
                        candidate.assertion_kind.value,
                        candidate.source_url,
                        candidate.content_hash,
                        _as_utc_text(created_at),
                        fetch_run_id,
                    ),
                )
                assertion_inserted = assertion_cursor.rowcount == 1
                assertion_row = connection.execute(
                    """
                    SELECT assertion_id FROM sighting_assertions
                    WHERE sighting_id = ? AND assertion_kind = ? AND content_hash = ?
                    """,
                    (
                        sighting_id,
                        candidate.assertion_kind.value,
                        candidate.content_hash,
                    ),
                ).fetchone()
                if assertion_row is None:
                    raise RuntimeError("assertion insert was not observable in its transaction")

                return IngestResult(
                    sighting_id=sighting_id,
                    assertion_id=int(assertion_row[0]),
                    sighting_inserted=sighting_inserted,
                    assertion_inserted=assertion_inserted,
                )
        finally:
            connection.close()


class FetchAlreadyRunning(RuntimeError):
    """同じsourceのfetchが既にSTARTEDであることを示す。"""

    def __init__(self, source_id: str, run_id: str) -> None:
        """衝突したsourceとrunを保持する。"""
        self.source_id = source_id
        self.run_id = run_id
        super().__init__(f"fetch already running for source {source_id}: {run_id}")
