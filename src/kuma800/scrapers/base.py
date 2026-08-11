"""worker-facing同期scraper protocol。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from kuma800.domain import CandidateObservation, SourceDescriptor


class ScraperAdapter(Protocol):
    """Huey taskが呼ぶ同期adapter境界。"""

    @property
    def source(self) -> SourceDescriptor:
        """静的な出典識別情報を返す。"""

    def fetch(self, *, fetched_at: datetime) -> tuple[CandidateObservation, ...]:
        """正規化済み観測候補を返す。"""
