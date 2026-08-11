"""KUMA800の正規化domain model。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from urllib.parse import urlparse

_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class FetchRunStatus(StrEnum):
    """収集実行の永続状態。"""

    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    STALE = "STALE"


class AssertionKind(StrEnum):
    """観測へ追加する出典付き主張の種類。"""

    REPORTED = "reported"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    RETRACTED = "retracted"
    FALSE_REPORT = "false_report"
    NO_LONGER_PRESENT = "no_longer_present"


class ReviewState(StrEnum):
    """情報源での確認段階。"""

    PROVISIONAL = "provisional"
    REVIEWED_CANDIDATE = "reviewed_candidate"
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"


def require_aware(value: datetime, field_name: str) -> None:
    """日時がtimezone付きであることを検証する。"""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def require_public_http_url(value: str, field_name: str) -> None:
    """出典URLがHTTP(S)の絶対URLであることを検証する。"""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be an absolute HTTP(S) URL")


def require_sha256(value: str, field_name: str) -> None:
    """hashがalgorithm名付きのlowercase SHA-256であることを検証する。"""
    if not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must use sha256:<64 lowercase hex>")


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    """静的に登録する情報源の識別情報。"""

    source_id: str
    source_kind: str
    source_url: str

    def __post_init__(self) -> None:
        """空識別子と相対URLを拒否する。"""
        if not self.source_id.strip():
            raise ValueError("source_id must not be empty")
        if not self.source_kind.strip():
            raise ValueError("source_kind must not be empty")
        require_public_http_url(self.source_url, "source_url")


@dataclass(frozen=True, slots=True)
class CandidateObservation:
    """adapterからcore ingestへ渡す正規化済み観測候補。"""

    source_id: str
    source_event_id: str
    source_url: str
    fetched_at: datetime
    event_time: datetime | None
    latitude: float | None
    longitude: float | None
    location_precision: str
    input_kind: str
    review_state: ReviewState
    assertion_kind: AssertionKind
    animal_kind: str
    count: int | None
    original_text: str
    content_hash: str

    def __post_init__(self) -> None:
        """欠損を安全へ丸める前に、保存可能な最小不変条件を検証する。"""
        if not self.source_id.strip() or not self.source_event_id.strip():
            raise ValueError("source_id and source_event_id must not be empty")
        require_public_http_url(self.source_url, "source_url")
        require_aware(self.fetched_at, "fetched_at")
        if self.event_time is not None:
            require_aware(self.event_time, "event_time")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        if self.latitude is not None and not -90 <= self.latitude <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if self.longitude is not None and not -180 <= self.longitude <= 180:
            raise ValueError("longitude must be between -180 and 180")
        if self.count is not None and self.count < 0:
            raise ValueError("count must be non-negative")
        for field_name, value in (
            ("location_precision", self.location_precision),
            ("input_kind", self.input_kind),
            ("animal_kind", self.animal_kind),
            ("original_text", self.original_text),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must not be empty")
        require_sha256(self.content_hash, "content_hash")


@dataclass(frozen=True, slots=True)
class IngestResult:
    """冪等ingestの結果。"""

    sighting_id: int
    assertion_id: int
    sighting_inserted: bool
    assertion_inserted: bool
