"""利用者位置YAML storeの回帰試験。"""

import stat
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kuma800.user_config import UserLocation, UserLocationStore

_NOW = datetime(2026, 8, 11, 13, 0, tzinfo=UTC)


def _user(user_id: str = "local-user") -> UserLocation:
    """正常な利用者位置を作る。"""
    return UserLocation(
        user_id=user_id,
        latitude=38.0,
        longitude=140.0,
        radius_km=10.0,
        timezone="Asia/Tokyo",
        enabled=True,
        updated_at=_NOW,
    )


def test_roundtrip_update_list_and_delete(tmp_path: Path) -> None:
    """CRUDがschema version付きYAMLを往復する。"""
    path = tmp_path / "state" / "users.yaml"
    store = UserLocationStore(path)
    first = _user()

    assert store.upsert(first) is None
    assert store.get(first.user_id) == first
    assert store.list() == [first]

    changed = replace(first, radius_km=3.5, enabled=False)
    assert store.upsert(changed) == first
    assert store.get(first.user_id) == changed
    assert store.delete(first.user_id) == changed
    assert store.list() == []
    assert store.delete(first.user_id) is None


def test_write_uses_owner_only_permission_when_supported(tmp_path: Path) -> None:
    """生成fileを所有者だけ読み書き可能にする。"""
    path = tmp_path / "users.yaml"
    UserLocationStore(path).upsert(_user())

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_corrupt_existing_yaml_is_not_overwritten(tmp_path: Path) -> None:
    """既存YAMLが壊れていれば自動修復せず原文を保持する。"""
    path = tmp_path / "users.yaml"
    original = "version: 1\nusers: [broken\n"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="cannot read valid"):
        UserLocationStore(path).upsert(_user())

    assert path.read_text(encoding="utf-8") == original


def test_user_location_rejects_invalid_values() -> None:
    """危険な位置条件を保存前に拒否する。"""
    with pytest.raises(ValueError, match="latitude"):
        replace(_user(), latitude=91.0)
    with pytest.raises(ValueError, match="longitude"):
        replace(_user(), longitude=181.0)
    with pytest.raises(ValueError, match="greater than zero"):
        replace(_user(), radius_km=0.0)
    with pytest.raises(ValueError, match="unknown timezone"):
        replace(_user(), timezone="Mars/Olympus")
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(_user(), updated_at=datetime(2026, 8, 11, 13, 0))
