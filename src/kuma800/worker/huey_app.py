"""Huey consumerがimportする永続queueとtask。"""

from __future__ import annotations

from dataclasses import asdict

from huey import SqliteHuey, crontab  # type: ignore[import-untyped]

from kuma800.runtime import RuntimePaths

from .service import execute_scrape

paths = RuntimePaths.resolve()
paths.data_dir.mkdir(parents=True, exist_ok=True)
# 追跡の正本はfetch_runs.run_id（観測SQLite側）。Huey result storeは誰も読まない
# ため、未回収resultの蓄積を避け、正本を二重に持たせない。
huey = SqliteHuey("kuma800", filename=str(paths.queue_database), results=False, utc=True)


@huey.task()  # type: ignore[untyped-decorator]
def scrape_source(
    source_id: str, run_id: str | None = None, retry_of_run_id: str | None = None
) -> dict[str, object]:
    """指定sourceのscrapeをconsumer processで実行する。

    `retry_of_run_id`はstale回収後の再実行enqueue（`worker.service.recover_and_
    retry_stale`）から渡される。手動enqueueでは指定しない。
    """
    return asdict(
        execute_scrape(source_id, paths=paths, run_id=run_id, retry_of_run_id=retry_of_run_id)
    )


@huey.periodic_task(crontab(minute="*/5"))  # type: ignore[untyped-decorator]
def poll_dummy_kuma() -> dict[str, object]:
    """DUMMY-KUMAを5分ごとにpollするscheduler smoke。"""
    return asdict(execute_scrape("dummy-kuma", paths=paths))


@huey.periodic_task(crontab(minute="17"))  # type: ignore[untyped-decorator]
def poll_yamagata_csv() -> dict[str, object]:
    """山形県ページから現行CSV snapshotを毎時17分に確認する。"""
    return asdict(execute_scrape("yamagata-r8-csv", paths=paths))
