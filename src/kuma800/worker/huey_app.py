"""Huey consumerがimportする永続queueとtask。"""

from __future__ import annotations

from dataclasses import asdict

from huey import SqliteHuey, crontab  # type: ignore[import-untyped]

from kuma800.runtime import RuntimePaths

from .service import execute_scrape

paths = RuntimePaths.resolve()
paths.data_dir.mkdir(parents=True, exist_ok=True)
huey = SqliteHuey("kuma800", filename=str(paths.queue_database), results=True, utc=True)


@huey.task()  # type: ignore[untyped-decorator]
def scrape_source(source_id: str, run_id: str | None = None) -> dict[str, object]:
    """指定sourceのscrapeをconsumer processで実行する。"""
    return asdict(execute_scrape(source_id, paths=paths, run_id=run_id))


@huey.periodic_task(crontab(minute="*/5"))  # type: ignore[untyped-decorator]
def poll_dummy_kuma() -> dict[str, object]:
    """DUMMY-KUMAを5分ごとにpollするscheduler smoke。"""
    return asdict(execute_scrape("dummy-kuma", paths=paths))


@huey.periodic_task(crontab(minute="17"))  # type: ignore[untyped-decorator]
def poll_yamagata_csv() -> dict[str, object]:
    """山形県ページから現行CSV snapshotを毎時17分に確認する。"""
    return asdict(execute_scrape("yamagata-r8-csv", paths=paths))
