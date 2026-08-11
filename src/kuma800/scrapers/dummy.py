"""ネットワークへ接続しないDUMMY-KUMA adapter。"""

from __future__ import annotations

import hashlib
from datetime import datetime

from kuma800.domain import (
    AssertionKind,
    CandidateObservation,
    ReviewState,
    ScrapeBatch,
    SourceDescriptor,
)

_TEXT = "DUMMY-KUMA: fake observation for process validation"
_HASH = f"sha256:{hashlib.sha256(_TEXT.encode()).hexdigest()}"


class DummyKumaAdapter:
    """同じeventとhashを返して冪等性を検証するfake adapter。"""

    @property
    def source(self) -> SourceDescriptor:
        """外部接続しないfixture sourceを返す。"""
        return SourceDescriptor(
            source_id="dummy-kuma",
            source_kind="fixture",
            source_url="https://example.invalid/kuma800/dummy-kuma",
        )

    def fetch(self, *, fetched_at: datetime) -> ScrapeBatch:
        """山形県近傍の架空観測を一件返す。"""
        candidate = CandidateObservation(
            source_id=self.source.source_id,
            source_event_id="dummy-event-1",
            source_url=self.source.source_url,
            fetched_at=fetched_at,
            event_time=fetched_at,
            latitude=38.0,
            longitude=140.0,
            location_precision="fixture-point",
            input_kind="fixture",
            review_state=ReviewState.UNKNOWN,
            assertion_kind=AssertionKind.REPORTED,
            animal_kind="bear",
            count=1,
            original_text=_TEXT,
            content_hash=_HASH,
        )
        return ScrapeBatch(
            final_url=self.source.source_url,
            content_hash=_HASH,
            candidates=(candidate,),
        )
