"""scraper実行と観測ingestを結ぶ同期application service。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from kuma800.domain import FetchRunStatus
from kuma800.runtime import RuntimePaths
from kuma800.scrapers import DummyKumaAdapter, ScraperAdapter, YamagataCsvAdapter
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
    yamagata = YamagataCsvAdapter()
    return {
        dummy.source.source_id: dummy,
        yamagata.source.source_id: yamagata,
    }


def available_source_ids() -> tuple[str, ...]:
    """静的registryにあるsource IDを安定順で返す。"""
    return tuple(sorted(_adapters()))


def execute_scrape(
    source_id: str,
    *,
    paths: RuntimePaths | None = None,
    now: datetime | None = None,
    run_id: str | None = None,
    retry_of_run_id: str | None = None,
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
    resolved_run_id = store.start_fetch(
        source_id, started_at=fetched_at, run_id=run_id, retry_of_run_id=retry_of_run_id
    )
    try:
        batch = adapter.fetch(fetched_at=fetched_at)
        inserted_count = sum(
            store.append_candidate(
                candidate,
                fetch_run_id=resolved_run_id,
                created_at=fetched_at,
            ).sighting_inserted
            for candidate in batch.candidates
        )
    except Exception as error:
        store.finish_fetch(
            resolved_run_id,
            status=FetchRunStatus.FAILED,
            finished_at=datetime.now(UTC),
            error_code=type(error).__name__,
        )
        raise

    store.finish_fetch(
        resolved_run_id,
        status=FetchRunStatus.SUCCEEDED,
        finished_at=datetime.now(UTC),
        final_url=batch.final_url,
        content_hash=batch.content_hash,
    )
    return ScrapeRunResult(
        run_id=resolved_run_id,
        source_id=source_id,
        candidate_count=len(batch.candidates),
        inserted_count=inserted_count,
    )


def recover_and_retry_stale(
    paths: RuntimePaths, *, before: datetime, recovered_at: datetime
) -> tuple[str, ...]:
    """stale runをSTALE化し、初回staleに限り新runを一度だけqueueへenqueueする。

    旧runは`STALE`のまま保存し、書き換えない。新runは`retry_of_run_id`で旧run
    を追跡できる。旧run自体が既に別runの再実行だった場合は、無制限retryを避け
    るため再enqueueしない（設計判断はIssue #6の設計拘束を参照）。
    """
    # huey_appはexecute_scrapeをimportするため、循環importを避けて遅延importする。
    from kuma800.worker.huey_app import scrape_source

    store = ObservationIngestStore(paths.observation_database)
    stale_runs = store.recover_stale(before=before, recovered_at=recovered_at)

    retried_run_ids: list[str] = []
    for stale_run in stale_runs:
        if not stale_run.retryable:
            continue
        retry_run_id = str(uuid4())
        scrape_source(stale_run.source_id, run_id=retry_run_id, retry_of_run_id=stale_run.run_id)
        retried_run_ids.append(retry_run_id)
    return tuple(retried_run_ids)
