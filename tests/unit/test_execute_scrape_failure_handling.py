"""execute_scrapeのbackoff gateと失敗分類の配線を検証する（Issue #7）。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

import kuma800.worker.service as service
from kuma800.domain import ScrapeBatch, SourceDescriptor
from kuma800.runtime import RuntimePaths
from kuma800.scrapers.base import ScraperAdapter
from kuma800.scrapers.http import PublicFetchError
from kuma800.storage import ObservationIngestStore
from kuma800.worker.service import SourceInBackoff, execute_scrape

_SOURCE_ID = "failing-fixture"
_NOW = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)


class _FailingAdapter:
    """任意の例外を送出するtest専用adapter（production registryには置かない）。"""

    def __init__(self, error: BaseException) -> None:
        self._error = error

    @property
    def source(self) -> SourceDescriptor:
        return SourceDescriptor(
            source_id=_SOURCE_ID,
            source_kind="fixture",
            source_url="https://example.invalid/kuma800/failing-fixture",
        )

    def fetch(self, *, fetched_at: datetime) -> ScrapeBatch:
        raise self._error


def _patch_adapter(monkeypatch: pytest.MonkeyPatch, adapter: _FailingAdapter) -> None:
    monkeypatch.setattr(service, "_adapters", lambda: {_SOURCE_ID: adapter})


def _in_process_fetch(adapter: ScraperAdapter, fetched_at: datetime) -> ScrapeBatch:
    """subprocess隔離（Issue #8）を経由せず、fake adapterをin-processで直接呼ぶ。

    productionの既定はsubprocess経由（`kuma800.worker.subprocess_runner`）だが、
    子processは`worker.service._adapters`のmonkeypatchを認識できない。ここで
    検証したいのはfailure分類・backoff配線（Issue #7）であり、subprocess隔離
    機構そのもの（Issue #8）は別testで検証する。
    """
    return adapter.fetch(fetched_at=fetched_at)


def test_retryable_failure_sets_bounded_backoff_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """timeoutはRETRYABLEへ分類され、fetch_runsとsource_stateへ反映される。"""
    paths = RuntimePaths(tmp_path)
    _patch_adapter(monkeypatch, _FailingAdapter(PublicFetchError("x", reason="timeout")))

    with pytest.raises(PublicFetchError):
        execute_scrape(_SOURCE_ID, paths=paths, now=_NOW, fetch=_in_process_fetch)

    store = ObservationIngestStore(paths.observation_database)
    backoff_until = store.backoff_until_for(_SOURCE_ID)
    assert backoff_until is not None
    assert backoff_until > _NOW


def test_terminal_failure_sets_indefinite_backoff_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """schema drift相当のValueErrorはTERMINALへ分類され、無期限backoffになる。"""
    paths = RuntimePaths(tmp_path)
    _patch_adapter(monkeypatch, _FailingAdapter(ValueError("Yamagata CSV schema changed")))

    with pytest.raises(ValueError, match="schema changed"):
        execute_scrape(_SOURCE_ID, paths=paths, now=_NOW, fetch=_in_process_fetch)

    store = ObservationIngestStore(paths.observation_database)
    backoff_until = store.backoff_until_for(_SOURCE_ID)
    assert backoff_until is not None
    assert (backoff_until - _NOW).days > 300


def test_backoff_gate_refuses_upstream_contact_without_creating_fetch_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """backoff中はadapter.fetch()を呼ばず、fetch_runも作らない。"""
    paths = RuntimePaths(tmp_path)
    adapter = _FailingAdapter(PublicFetchError("x", reason="timeout"))
    _patch_adapter(monkeypatch, adapter)

    with pytest.raises(PublicFetchError):
        execute_scrape(_SOURCE_ID, paths=paths, now=_NOW, fetch=_in_process_fetch)

    def _fail_if_called(*, fetched_at: datetime) -> ScrapeBatch:
        pytest.fail("adapter.fetch() must not be called while in backoff")

    monkeypatch.setattr(adapter, "fetch", _fail_if_called)

    with pytest.raises(SourceInBackoff) as captured:
        execute_scrape(_SOURCE_ID, paths=paths, now=_NOW, fetch=_in_process_fetch)
    assert captured.value.source_id == _SOURCE_ID

    store = ObservationIngestStore(paths.observation_database)
    fetch_run_count = _count_fetch_runs(paths)
    assert fetch_run_count == 1  # backoff直前の一回だけで、gateされた呼出しは増えない
    assert store.backoff_until_for(_SOURCE_ID) is not None


def _count_fetch_runs(paths: RuntimePaths) -> int:
    connection = sqlite3.connect(paths.observation_database)
    try:
        row = connection.execute(
            "SELECT COUNT(*) FROM fetch_runs WHERE source_id = ?", (_SOURCE_ID,)
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return int(row[0])


def test_success_after_backoff_expires_clears_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """backoff終了後は接続でき、成功でfailure状態がclearされる。"""
    paths = RuntimePaths(tmp_path)
    failing = _FailingAdapter(PublicFetchError("x", reason="timeout"))
    _patch_adapter(monkeypatch, failing)
    with pytest.raises(PublicFetchError):
        execute_scrape(_SOURCE_ID, paths=paths, now=_NOW, fetch=_in_process_fetch)

    batch = ScrapeBatch(
        final_url="https://example.invalid/kuma800/failing-fixture",
        content_hash="sha256:" + "0" * 64,
        candidates=(),
    )

    class _SucceedingAdapter(_FailingAdapter):
        def fetch(self, *, fetched_at: datetime) -> ScrapeBatch:
            return batch

    succeeding = _SucceedingAdapter(RuntimeError("unused"))
    _patch_adapter(monkeypatch, succeeding)

    store = ObservationIngestStore(paths.observation_database)
    much_later = _NOW.replace(year=_NOW.year + 1)

    result = execute_scrape(_SOURCE_ID, paths=paths, now=much_later, fetch=_in_process_fetch)

    assert result.source_id == _SOURCE_ID
    assert store.backoff_until_for(_SOURCE_ID) is None
