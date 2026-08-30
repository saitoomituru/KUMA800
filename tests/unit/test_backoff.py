"""source単位の上限付き指数backoff計算を検証する（clock非依存）。"""

from __future__ import annotations

import pytest

from kuma800.domain import INDEFINITE_BACKOFF_SECONDS, compute_backoff_seconds
from kuma800.domain.backoff import BACKOFF_FACTOR, INITIAL_BACKOFF_SECONDS, MAX_BACKOFF_SECONDS


def test_backoff_grows_exponentially_from_initial_delay() -> None:
    """1回目はinitial delay、以降はfactor倍で伸びる。"""
    assert compute_backoff_seconds(1) == INITIAL_BACKOFF_SECONDS
    assert compute_backoff_seconds(2) == INITIAL_BACKOFF_SECONDS * BACKOFF_FACTOR
    assert compute_backoff_seconds(3) == INITIAL_BACKOFF_SECONDS * BACKOFF_FACTOR**2


def test_backoff_is_capped_at_max_delay() -> None:
    """max_delayを超えて伸び続けない（retry上限内でcapへ到達する）。"""
    assert compute_backoff_seconds(7) == MAX_BACKOFF_SECONDS
    assert compute_backoff_seconds(8) == MAX_BACKOFF_SECONDS


def test_backoff_becomes_indefinite_past_retry_limit() -> None:
    """retry上限を超えると事実上の無期限backoffへ切り替わる。"""
    assert compute_backoff_seconds(9) == INDEFINITE_BACKOFF_SECONDS


def test_backoff_rejects_non_positive_failure_counts() -> None:
    """failure countが1未満は呼出し側の不正入力として拒否する。"""
    with pytest.raises(ValueError, match="at least 1"):
        compute_backoff_seconds(0)
