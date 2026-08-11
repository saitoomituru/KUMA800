"""scraper実行と観測ingestを結ぶ同期application service。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from kuma800.domain import FetchRunStatus
from kuma800.runtime import RuntimePaths
from kuma800.scrapers import DummyKumaAdapter, ScraperAdapter
from kuma800.storage import ObservationIngestStore, migrate_database


@dataclass(frozen=True, slots=True)
class ScrapeRunResult:
    """queue serializerへ渡せるscrape実行結果。"""

    run_id: str
    source_id: str
    candidate_count: int
    inserted_count: int


def _adapters() -> dict[str, ScraperAdapter]:
    """Season 1で静的に同梱するadapter registryを返す。"""
    dummy = DummyKumaAdapter()
    return {dummy.source.source_id: dummy}


def available_source_ids() -> tuple[str, ...]:
    """静的registryにあるsource IDを安定順で返す。"""
    return tuple(sorted(_adapters()))


def execute_scrape(
    source_id: str,
    *,
    paths: RuntimePaths | None = None,
    now: datetime | None = None,
) -> ScrapeRunResult:
    """一つのsourceを取得し、出典付き候補を冪等appendする。"""
    resolved_paths = paths or RuntimePaths.resolve()
    fetched_at = now or datetime.now(UTC)
    adapter = _adapters().get(source_id)
    if adapter is None:
        raise KeyError(f"unknown scraper source: {source_id}")

    migrate_database(resolved_paths.observation_database)
    store = ObservationIngestStore(resolved_paths.observation_database)
    store.register_source(adapter.source, created_at=fetched_at)
    run_id = store.start_fetch(source_id, started_at=fetched_at)
    try:
        candidates = adapter.fetch(fetched_at=fetched_at)
        inserted_count = sum(
            store.append_candidate(
                candidate,
                fetch_run_id=run_id,
                created_at=fetched_at,
            ).sighting_inserted
            for candidate in candidates
        )
    except Exception as error:
        store.finish_fetch(
            run_id,
            status=FetchRunStatus.FAILED,
            finished_at=datetime.now(UTC),
            error_code=type(error).__name__,
        )
        raise

    store.finish_fetch(
        run_id,
        status=FetchRunStatus.SUCCEEDED,
        finished_at=datetime.now(UTC),
    )
    return ScrapeRunResult(
        run_id=run_id,
        source_id=source_id,
        candidate_count=len(candidates),
        inserted_count=inserted_count,
    )
