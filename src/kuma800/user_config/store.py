"""permissionと原子置換を持つusers.yaml store。"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from kuma800.runtime import RuntimePaths

from .models import UserLocation

SCHEMA_VERSION = 1


def default_users_path() -> Path:
    """repository外のOS標準user data directoryを返す。"""
    return RuntimePaths.resolve().users_yaml


def _timestamp(value: datetime) -> str:
    """日時をUTC ISO 8601へ正規化する。"""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    """YAML値が文字列keyのmappingであることを検証する。"""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field_name} must be a mapping")
    return value


def _decode_user(user_id: str, value: object) -> UserLocation:
    """YAML mappingをUserLocationへ変換する。"""
    record = _mapping(value, f"users.{user_id}")
    expected = {"latitude", "longitude", "radius_km", "timezone", "enabled", "updated_at"}
    if set(record) != expected:
        raise ValueError(f"users.{user_id} has unexpected or missing fields")
    enabled = record["enabled"]
    if not isinstance(enabled, bool):
        raise ValueError(f"users.{user_id}.enabled must be boolean")
    try:
        updated_at = datetime.fromisoformat(str(record["updated_at"]).replace("Z", "+00:00"))
        return UserLocation(
            user_id=user_id,
            latitude=float(record["latitude"]),
            longitude=float(record["longitude"]),
            radius_km=float(record["radius_km"]),
            timezone=str(record["timezone"]),
            enabled=enabled,
            updated_at=updated_at,
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid users.{user_id} record") from error


def _encode_user(user: UserLocation) -> dict[str, object]:
    """UserLocationを安定したYAML mappingへ変換する。"""
    return {
        "latitude": user.latitude,
        "longitude": user.longitude,
        "radius_km": user.radius_km,
        "timezone": user.timezone,
        "enabled": user.enabled,
        "updated_at": _timestamp(user.updated_at),
    }


class UserLocationStore:
    """単一control-plane process向けの利用者位置store。"""

    def __init__(self, path: Path | None = None) -> None:
        """保存pathを固定する。省略時はOS標準directoryを使う。"""
        self.path = path or default_users_path()

    def list(self) -> list[UserLocation]:
        """user_id順で全利用者位置を返す。"""
        users = self._read()
        return [users[user_id] for user_id in sorted(users)]

    def get(self, user_id: str) -> UserLocation | None:
        """利用者位置を返し、未登録ならNoneを返す。"""
        return self._read().get(user_id)

    def upsert(self, user: UserLocation) -> UserLocation | None:
        """利用者位置を追加または置換し、変更前の値を返す。"""
        users = self._read()
        previous = users.get(user.user_id)
        users[user.user_id] = user
        self._write(users)
        return previous

    def delete(self, user_id: str) -> UserLocation | None:
        """利用者位置を削除し、存在した値を返す。"""
        users = self._read()
        previous = users.pop(user_id, None)
        if previous is not None:
            self._write(users)
        return previous

    def _read(self) -> dict[str, UserLocation]:
        """全schemaを検証してからmemoryへ返す。"""
        if not self.path.exists():
            return {}
        try:
            payload = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise ValueError(f"cannot read valid users YAML: {self.path}") from error
        root = _mapping(payload, "document")
        if root.get("version") != SCHEMA_VERSION or set(root) != {"version", "users"}:
            raise ValueError(f"unsupported or invalid users YAML schema: {self.path}")
        users = _mapping(root["users"], "users")
        return {user_id: _decode_user(user_id, value) for user_id, value in users.items()}

    def _write(self, users: dict[str, UserLocation]) -> None:
        """同一directoryの一時fileを検証してから原子置換する。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": SCHEMA_VERSION,
            "users": {user_id: _encode_user(users[user_id]) for user_id in sorted(users)},
        }
        serialized = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=self.path.parent,
                text=True,
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_path, 0o600)
            UserLocationStore(temporary_path)._read()
            os.replace(temporary_path, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
