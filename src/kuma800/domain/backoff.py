"""source単位の上限付き指数backoff計算（Issue #7）。

clock非依存の純粋関数のみを置く。`storage.ingest`と`worker`の双方から
参照されるため、scraper実装（`kuma800.scrapers`）への依存は持たない。
"""

from __future__ import annotations

INITIAL_BACKOFF_SECONDS = 60.0
BACKOFF_FACTOR = 2.0
MAX_BACKOFF_SECONDS = 3600.0
MAX_RETRY_ATTEMPTS = 8
INDEFINITE_BACKOFF_SECONDS = 60.0 * 60.0 * 24.0 * 365.0
"""retry上限到達・TERMINAL失敗時の事実上の無期限backoff。

人間がsourceの状態を確認してresetする管理toolはまだ存在しない（#9以降の
課題）。この定数は、単に毎回の周期pollがそのまま上流へ再接続してしまう
ことを避けるための現実的な安全側の縮退であり、真の「無期限gate解除」
機構の代替にはならない。
"""


def compute_backoff_seconds(consecutive_failures: int) -> float:
    """失敗回数から指数backoff（上限付き）を計算する。"""
    if consecutive_failures < 1:
        raise ValueError("consecutive_failures must be at least 1")
    if consecutive_failures > MAX_RETRY_ATTEMPTS:
        return INDEFINITE_BACKOFF_SECONDS
    return min(
        INITIAL_BACKOFF_SECONDS * (BACKOFF_FACTOR ** (consecutive_failures - 1)),
        MAX_BACKOFF_SECONDS,
    )
