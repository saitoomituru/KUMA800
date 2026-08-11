"""launchd service adapterの回帰試験。"""

import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

from kuma800.service import LaunchdPaths, render_launch_agents


def test_render_launch_agents_keeps_mcp_and_worker_separate(tmp_path: Path) -> None:
    """二つのforeground moduleを別label・同じdata contractで生成する。"""
    output = tmp_path / "agents"
    data = tmp_path / "data"
    logs = tmp_path / "logs"
    python = Path("/opt/kuma800/.venv/bin/python")

    worker_path, mcp_path = render_launch_agents(
        output,
        LaunchdPaths(python_executable=python, data_dir=data, log_dir=logs),
    )
    with worker_path.open("rb") as stream:
        worker = plistlib.load(stream)
    with mcp_path.open("rb") as stream:
        mcp = plistlib.load(stream)

    assert worker["Label"] == "io.zeroroomlab.kuma800.worker"
    assert mcp["Label"] == "io.zeroroomlab.kuma800.mcp"
    assert worker["ProgramArguments"] == [str(python), "-m", "kuma800.worker.cli"]
    assert mcp["ProgramArguments"] == [str(python), "-m", "kuma800.mcp_server"]
    assert worker["EnvironmentVariables"] == {"KUMA800_DATA_DIR": str(data)}
    assert mcp["EnvironmentVariables"] == {"KUMA800_DATA_DIR": str(data)}
    assert worker["KeepAlive"] is True
    assert mcp["RunAtLoad"] is True


def test_launchd_paths_reject_relative_values(tmp_path: Path) -> None:
    """service managerへcwd依存pathを渡さない。"""
    with pytest.raises(ValueError, match="python_executable"):
        LaunchdPaths(
            python_executable=Path("python"),
            data_dir=tmp_path / "data",
            log_dir=tmp_path / "logs",
        )


def test_cli_preserves_virtualenv_python_symlink(tmp_path: Path) -> None:
    """venv Pythonを実体へ解決してsite-packages境界を失わない。"""
    python_link = tmp_path / "venv" / "bin" / "python"
    python_link.parent.mkdir(parents=True)
    python_link.symlink_to(Path(sys.executable))
    output = tmp_path / "agents"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "kuma800.service.launchd",
            "--output-dir",
            str(output),
            "--data-dir",
            str(tmp_path / "data"),
            "--log-dir",
            str(tmp_path / "logs"),
            "--python",
            str(python_link),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    with (output / "io.zeroroomlab.kuma800.worker.plist").open("rb") as stream:
        worker = plistlib.load(stream)
    assert worker["ProgramArguments"][0] == str(python_link)
