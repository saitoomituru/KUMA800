"""FastMCPとHueyを別processで監督するlaunchd LaunchAgent生成器。"""

from __future__ import annotations

import argparse
import logging
import os
import plistlib
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

_LABEL_PREFIX = "io.zeroroomlab.kuma800"
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LaunchdPaths:
    """LaunchAgentが参照する絶対path群。"""

    python_executable: Path
    data_dir: Path
    log_dir: Path

    def __post_init__(self) -> None:
        """launchdへ曖昧な相対pathを渡さない。"""
        for field_name, value in (
            ("python_executable", self.python_executable),
            ("data_dir", self.data_dir),
            ("log_dir", self.log_dir),
        ):
            if not value.is_absolute():
                raise ValueError(f"{field_name} must be absolute")


def _service_payload(role: str, paths: LaunchdPaths) -> dict[str, object]:
    """一つのforeground Python service用plist payloadを返す。"""
    if role not in {"worker", "mcp"}:
        raise ValueError(f"unknown launchd role: {role}")
    module = "kuma800.worker.cli" if role == "worker" else "kuma800.mcp_server"
    label = f"{_LABEL_PREFIX}.{role}"
    program_arguments = [str(paths.python_executable), "-m", module]
    if role == "worker":
        # launchdが監督するworkerは唯一のperiodic ownerとして明示する。
        program_arguments.append("--periodic-owner")
    return {
        "Label": label,
        "ProgramArguments": program_arguments,
        "EnvironmentVariables": {"KUMA800_DATA_DIR": str(paths.data_dir)},
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "ThrottleInterval": 10,
        "StandardOutPath": str(paths.log_dir / f"{role}.stdout.log"),
        "StandardErrorPath": str(paths.log_dir / f"{role}.stderr.log"),
    }


def _atomic_plist(path: Path, payload: dict[str, object]) -> None:
    """同一directoryの一時fileを経由してplistを原子置換する。"""
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as stream:
            _write_plist(stream, payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _write_plist(stream: BinaryIO, payload: dict[str, object]) -> None:
    """plistlibのXML形式でservice定義を書く。"""
    plistlib.dump(payload, stream, fmt=plistlib.FMT_XML, sort_keys=True)


def render_launch_agents(output_dir: Path, paths: LaunchdPaths) -> tuple[Path, Path]:
    """workerとMCPのLaunchAgent plistを生成する。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.log_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    for role in ("worker", "mcp"):
        destination = output_dir / f"{_LABEL_PREFIX}.{role}.plist"
        _atomic_plist(destination, _service_payload(role, paths))
        rendered.append(destination)
    return rendered[0], rendered[1]


def main() -> None:
    """現在のPython環境を使うLaunchAgent plistを指定directoryへ生成する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    rendered = render_launch_agents(
        arguments.output_dir.expanduser().resolve(),
        LaunchdPaths(
            python_executable=Path(os.path.abspath(arguments.python.expanduser())),
            data_dir=arguments.data_dir.expanduser().resolve(),
            log_dir=arguments.log_dir.expanduser().resolve(),
        ),
    )
    for path in rendered:
        _LOGGER.info("%s", path)


if __name__ == "__main__":
    main()
