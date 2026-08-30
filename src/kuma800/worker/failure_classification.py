"""取得失敗を自動retry可能か人間確認が必要かへ分類する（Issue #7）。

未知の例外・未知のHTTP status・未知の`PublicFetchError.reason`は、すべて
`TERMINAL`（人間確認が必要）へ丸める。一時故障だと推定して無制限retryへ
倒す既定は取らない。backoffの秒数計算は`kuma800.domain.backoff`が持つ
（scraper非依存の純粋関数のため）。
"""

from __future__ import annotations

from kuma800.domain import FailureCategory
from kuma800.scrapers.http import PublicFetchError
from kuma800.worker.subprocess_runner import AdapterTimedOut

_RETRYABLE_REASONS = frozenset({"timeout", "connection_error"})


def classify_failure(error: BaseException) -> FailureCategory:
    """例外をRETRYABLE（自動retry可）かTERMINAL（人間確認要）へ分類する。"""
    if isinstance(error, AdapterTimedOut):
        # 子processのhang自体は一時的な事象である可能性が高く、無条件でTERMINAL
        # へ倒すと#8のsubprocess isolationが単なる「即terminal」機構になってしまう。
        return FailureCategory.RETRYABLE
    if isinstance(error, PublicFetchError):
        if error.reason == "http_status" and error.status_code is not None:
            if error.status_code == 429 or 500 <= error.status_code < 600:
                return FailureCategory.RETRYABLE
            return FailureCategory.TERMINAL
        if error.reason in _RETRYABLE_REASONS:
            return FailureCategory.RETRYABLE
        return FailureCategory.TERMINAL
    return FailureCategory.TERMINAL
