"""利用者位置YAMLのdomain model。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True, slots=True)
class UserLocation:
    """近傍検索に使う利用者位置と検索条件。"""

    user_id: str
    latitude: float
    longitude: float
    radius_km: float
    timezone: str
    enabled: bool
    updated_at: datetime

    def __post_init__(self) -> None:
        """YAMLへ保存できる最小不変条件を検証する。"""
        if not self.user_id.strip():
            raise ValueError("user_id must not be empty")
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude must be between -180 and 180")
        if self.radius_km <= 0:
            raise ValueError("radius_km must be greater than zero")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown timezone: {self.timezone}") from error
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("updated_at must be timezone-aware")
