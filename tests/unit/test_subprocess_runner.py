"""adapter.fetch()のsubprocess隔離を検証する（Issue #8）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kuma800.worker.subprocess_runner import (
    AdapterSubprocessError,
    AdapterTimedOut,
    run_adapter_in_subprocess,
)

_NOW = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)


def test_successful_fetch_round_trips_through_subprocess() -> None:
    """productionのdummy-kumaを子processで実行し、in-process結果と同じ形になる。"""
    batch = run_adapter_in_subprocess("dummy-kuma", _NOW, timeout_seconds=30.0)

    assert batch.candidates[0].source_id == "dummy-kuma"
    assert batch.candidates[0].original_text.startswith("DUMMY-KUMA")
    assert batch.final_url == "https://example.invalid/kuma800/dummy-kuma"


def test_unknown_source_raises_key_error_from_child() -> None:
    """子processのKeyErrorが親側でも同じ型として再送出される。"""
    with pytest.raises(KeyError, match="unknown scraper source"):
        run_adapter_in_subprocess("does-not-exist", _NOW, timeout_seconds=30.0)


def test_timeout_kills_child_and_raises_adapter_timed_out() -> None:
    """timeoutを極端に短くすると、interpreter起動にすら間に合わずhard killされる。"""
    with pytest.raises(AdapterTimedOut) as captured:
        run_adapter_in_subprocess("dummy-kuma", _NOW, timeout_seconds=0.001)
    assert captured.value.source_id == "dummy-kuma"
    assert captured.value.timeout_seconds == 0.001


def test_adapter_subprocess_error_is_a_runtime_error() -> None:
    """未分類の子process失敗は独自例外として区別できる（TERMINAL分類対象）。"""
    assert issubclass(AdapterSubprocessError, RuntimeError)
