"""KUMA800 service群が共有するローカルpath契約。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """queue、観測正本、利用者設定を分離したruntime path。"""

    data_dir: Path

    @classmethod
    def resolve(cls) -> RuntimePaths:
        """明示環境変数またはOS標準user data directoryから解決する。"""
        configured = os.environ.get("KUMA800_DATA_DIR")
        data_dir = (
            Path(configured).expanduser()
            if configured
            else user_data_path("KUMA800", "ZeroRoomLab")
        )
        return cls(data_dir=data_dir)

    @property
    def observation_database(self) -> Path:
        """追記専用クマ観測正本のpathを返す。"""
        return self.data_dir / "kuma.sqlite3"

    @property
    def queue_database(self) -> Path:
        """再作成可能なHuey queueのpathを返す。"""
        return self.data_dir / "queue.sqlite3"

    @property
    def users_yaml(self) -> Path:
        """利用者位置YAMLのpathを返す。"""
        return self.data_dir / "users.yaml"
