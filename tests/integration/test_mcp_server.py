"""FastMCP in-memory transportで公開権限境界を検証する。"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from kuma800.mcp_server import create_server
from kuma800.runtime import RuntimePaths
from kuma800.worker import execute_scrape


@pytest.mark.asyncio
async def test_mcp_tools_keep_observations_read_only_and_users_writable(tmp_path: Path) -> None:
    """観測query・非同期依頼・user YAML CRUDを実MCP protocolで往復する。"""
    paths = RuntimePaths(tmp_path)
    execute_scrape("dummy-kuma", paths=paths)
    queued: list[str] = []

    def enqueue(source_id: str) -> str:
        queued.append(source_id)
        return "task-1"

    server = create_server(paths=paths, enqueue_source=enqueue)
    async with Client(server) as client:
        tools = {tool.name for tool in await client.list_tools()}
        assert "kuma.sightings.recent" in tools
        assert not any("sql" in name or "write" in name for name in tools)

        status = await client.call_tool("kuma.status", {})
        assert status.data["sighting_count"] == 1

        sightings = await client.call_tool("kuma.sightings.recent", {"limit": 10})
        assert sightings.data[0]["original_text"].startswith("DUMMY-KUMA")
        assert sightings.data[0]["source_url"] == "https://example.invalid/kuma800/dummy-kuma"

        request = await client.call_tool("kuma.scrape.request", {"source_id": "dummy-kuma"})
        assert request.data == {
            "source_id": "dummy-kuma",
            "run_id": "task-1",
            "status": "QUEUED",
        }
        assert queued == ["dummy-kuma"]

        with pytest.raises(ToolError, match="unknown scraper source"):
            await client.call_tool("kuma.scrape.request", {"source_id": "villain-source"})
        assert queued == ["dummy-kuma"]

        inserted = await client.call_tool(
            "kuma.users.upsert",
            {
                "user_id": "local-user",
                "latitude": 38.0,
                "longitude": 140.0,
                "radius_km": 10.0,
                "timezone": "Asia/Tokyo",
                "enabled": True,
            },
        )
        assert inserted.data["previous"] is None
        assert inserted.data["current"]["user_id"] == "local-user"

        listed = await client.call_tool("kuma.users.list", {})
        assert [user["user_id"] for user in listed.data] == ["local-user"]

        deleted = await client.call_tool("kuma.users.delete", {"user_id": "local-user"})
        assert deleted.data["deleted"]["user_id"] == "local-user"


@pytest.mark.asyncio
async def test_mcp_status_is_explicit_before_worker_initializes_database(tmp_path: Path) -> None:
    """未初期化DBを空データと誤認せずinitialized=falseで返す。"""
    server = create_server(paths=RuntimePaths(tmp_path), enqueue_source=lambda _: "unused")

    async with Client(server) as client:
        status = await client.call_tool("kuma.status", {})

    assert status.data == {
        "initialized": False,
        "sighting_count": 0,
        "fetch_run_count": 0,
        "sources": [],
    }
    assert not (tmp_path / "kuma.sqlite3").exists()


@pytest.mark.asyncio
@pytest.mark.process_smoke
async def test_mcp_loopback_http_process_starts(tmp_path: Path) -> None:
    """FastMCPを別processのloopback HTTPで起動してtool一覧を取得する。"""
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", 0))
        except PermissionError:
            pytest.skip("current sandbox does not allow loopback socket binding")
        port = int(probe.getsockname()[1])
    environment = os.environ.copy()
    environment["KUMA800_DATA_DIR"] = str(tmp_path)
    environment["KUMA800_MCP_PORT"] = str(port)
    server = subprocess.Popen(
        [sys.executable, "-m", "kuma800.mcp_server"],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 15
    try:
        while time.monotonic() < deadline:
            if server.poll() is not None:
                stdout, stderr = server.communicate(timeout=1)
                pytest.fail(f"MCP server exited early: {stdout}\n{stderr}")
            try:
                async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                    tools = await client.list_tools()
                assert any(tool.name == "kuma.status" for tool in tools)
                break
            except Exception:
                await asyncio.sleep(0.1)
        else:
            pytest.fail("MCP loopback HTTP server did not become ready")
    finally:
        server.terminate()
        try:
            server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.communicate(timeout=5)
