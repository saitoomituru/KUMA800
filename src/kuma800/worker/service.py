"""scraper実行と観測ingestを結ぶ同期application service。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from kuma800.domain import FetchRunStatus, ScrapeBatch
from kuma800.runtime import RuntimePaths
from kuma800.scrapers import DummyKumaAdapter, ScraperAdapter, YamagataCsvAdapter
from kuma800.storage import ObservationIngestStore, migrate_database
from kuma800.worker.failure_classification import classify_failure
from kuma800.worker.subprocess_runner import run_adapter_in_subprocess

AdapterFetch = Callable[[ScraperAdapter, datetime], ScrapeBatch]


@dataclass(frozen=True, slots=True)
class ScrapeRunResult:
    """queue serializerへ渡せるscrape実行結果。"""

    run_id: str
    source_id: str
    candidate_count: int
    inserted_count: int


class SourceInBackoff(RuntimeError):
    """backoff中のsourceへ上流接続しなかったことを示す。"""

    def __init__(self, source_id: str, backoff_until: datetime) -> None:
        """gateしたsourceと解除予定時刻を保持する。"""
        self.source_id = source_id
        self.backoff_until = backoff_until
        super().__init__(f"source is in backoff until {backoff_until.isoformat()}: {source_id}")


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


def resolve_adapter(source_id: str) -> ScraperAdapter | None:
    """source_idからadapterを解決する（subprocess_runnerの子processが使う）。"""
    return _adapters().get(source_id)


def _default_fetch(adapter: ScraperAdapter, fetched_at: datetime) -> ScrapeBatch:
    """既定のfetch実装。子processへ隔離し、hangをhard killできるようにする（Issue #8）。"""
    return run_adapter_in_subprocess(adapter.source.source_id, fetched_at)


def execute_scrape(
    source_id: str,
    *,
    paths: RuntimePaths | None = None,
    now: datetime | None = None,
    run_id: str | None = None,
    retry_of_run_id: str | None = None,
    fetch: AdapterFetch | None = None,
) -> ScrapeRunResult:
    """一つのsourceを取得し、出典付き候補を冪等appendする。

    backoff中（`source_state.backoff_until`が未来）の場合は上流へ接続せず
    `SourceInBackoff`を送出する。fetch_runは作らない（Issue #7）。

    `fetch`を省略すると、既定でadapter.fetch()をsubprocessへ隔離する
    （Issue #8）。testでproduction registryにないfake adapterを直接
    実行したい場合だけ、in-process実装を明示的に渡す。
    """
    resolved_paths = paths or RuntimePaths.resolve()
    fetched_at = now or datetime.now(UTC)
    adapter = _adapters().get(source_id)
    if adapter is None:
        raise KeyError(f"unknown scraper source: {source_id}")
    fetch_fn = fetch or _default_fetch

    migrate_database(resolved_paths.observation_database)
    store = ObservationIngestStore(resolved_paths.observation_database)
    backoff_until = store.backoff_until_for(source_id)
    if backoff_until is not None and fetched_at < backoff_until:
        raise SourceInBackoff(source_id, backoff_until)

    store.register_source(adapter.source, created_at=fetched_at)
    resolved_run_id = store.start_fetch(
        source_id, started_at=fetched_at, run_id=run_id, retry_of_run_id=retry_of_run_id
    )
    try:
        batch = fetch_fn(adapter, fetched_at)
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
            failure_category=classify_failure(error),
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
