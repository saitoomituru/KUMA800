"""取得失敗のRETRYABLE/TERMINAL分類を検証する（Issue #7）。"""

from __future__ import annotations

import pytest

from kuma800.domain import FailureCategory
from kuma800.scrapers.http import PublicFetchError
from kuma800.worker.failure_classification import classify_failure
from kuma800.worker.subprocess_runner import AdapterTimedOut


@pytest.mark.parametrize(
    "error",
    [
        PublicFetchError("x", reason="timeout"),
        PublicFetchError("x", reason="connection_error"),
        PublicFetchError("x", reason="http_status", status_code=429),
        PublicFetchError("x", reason="http_status", status_code=500),
        PublicFetchError("x", reason="http_status", status_code=503),
        AdapterTimedOut("dummy-kuma", 60.0),
    ],
)
def test_temporary_failures_are_retryable(error: PublicFetchError) -> None:
    """timeout、一時的接続失敗、429、5xxはRETRYABLEへ分類する。"""
    assert classify_failure(error) is FailureCategory.RETRYABLE


@pytest.mark.parametrize(
    "error",
    [
        PublicFetchError("x", reason="disallowed_host"),
        PublicFetchError("x", reason="unexpected_content_type"),
        PublicFetchError("x", reason="content_length_exceeded"),
        PublicFetchError("x", reason="body_size_exceeded"),
        PublicFetchError("x", reason="http_status", status_code=404),
        PublicFetchError("x", reason="transport_error"),
        ValueError("Yamagata CSV schema changed"),
        RuntimeError("something unforeseen"),
    ],
)
def test_human_confirmation_failures_are_terminal(error: BaseException) -> None:
    """schema drift、許可外host、想定外4xx、未知例外はTERMINALへ丸める。"""
    assert classify_failure(error) is FailureCategory.TERMINAL
