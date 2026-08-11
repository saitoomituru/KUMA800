"""AI向けloopback FastMCP control-plane。"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime

from fastmcp import FastMCP

from kuma800.runtime import RuntimePaths
from kuma800.storage import observation_status, recent_fetch_runs, recent_sightings
from kuma800.user_config import UserLocation, UserLocationStore
from kuma800.worker import available_source_ids

EnqueueSource = Callable[[str], str]


def _default_enqueue(source_id: str) -> str:
    """Huey永続queueへtaskを追加してtask IDを返す。"""
    from kuma800.worker.huey_app import scrape_source

    result = scrape_source(source_id)
    return str(result.id)


def _user_payload(user: UserLocation | None) -> dict[str, object] | None:
    """利用者位置をMCP structured resultへ変換する。"""
    if user is None:
        return None
    payload = asdict(user)
    payload["updated_at"] = user.updated_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return payload


def create_server(
    *,
    paths: RuntimePaths | None = None,
    enqueue_source: EnqueueSource | None = None,
) -> FastMCP:
    """固定権限境界を持つKUMA800 MCP serverを作る。"""
    resolved_paths = paths or RuntimePaths.resolve()
    users = UserLocationStore(resolved_paths.users_yaml)
    enqueue = enqueue_source or _default_enqueue
    server = FastMCP(
        "KUMA800",
        instructions=(
            "クマ観測はread-onlyです。scrape requestは別Huey workerへenqueueし、"
            "同じMCP request内で完了を待ちません。"
        ),
    )

    @server.tool(name="kuma.status")
    def status() -> dict[str, object]:
        """観測件数、取得状態、失敗状態を返す。"""
        return observation_status(resolved_paths.observation_database)

    @server.tool(name="kuma.sightings.recent")
    def sightings_recent(limit: int = 20) -> list[dict[str, object]]:
        """新しいクマ観測を原典とfetch run付きで返す。"""
        return recent_sightings(resolved_paths.observation_database, limit=limit)

    @server.tool(name="kuma.fetch_runs.recent")
    def fetch_runs_recent(limit: int = 20) -> list[dict[str, object]]:
        """新しいscraping実行logを返す。"""
        return recent_fetch_runs(resolved_paths.observation_database, limit=limit)

    @server.tool(name="kuma.scrape.request")
    def scrape_request(source_id: str) -> dict[str, str]:
        """別Huey workerへscrapeを依頼し、待たずにtask IDを返す。"""
        if source_id not in available_source_ids():
            raise ValueError(f"unknown scraper source: {source_id}")
        return {"source_id": source_id, "task_id": enqueue(source_id), "status": "QUEUED"}

    @server.tool(name="kuma.users.list")
    def users_list() -> list[dict[str, object]]:
        """保存済み利用者位置を返す。"""
        return [_user_payload(user) or {} for user in users.list()]

    @server.tool(name="kuma.users.get")
    def users_get(user_id: str) -> dict[str, object] | None:
        """一人の利用者位置を返す。"""
        return _user_payload(users.get(user_id))

    @server.tool(name="kuma.users.upsert")
    def users_upsert(
        user_id: str,
        latitude: float,
        longitude: float,
        radius_km: float,
        timezone: str,
        enabled: bool = True,
    ) -> dict[str, object]:
        """利用者位置を追加または置換し、変更前後を返す。"""
        current = UserLocation(
            user_id=user_id,
            latitude=latitude,
            longitude=longitude,
            radius_km=radius_km,
            timezone=timezone,
            enabled=enabled,
            updated_at=datetime.now(UTC),
        )
        previous = users.upsert(current)
        return {
            "schema_version": 1,
            "path": str(users.path),
            "previous": _user_payload(previous),
            "current": _user_payload(current),
        }

    @server.tool(name="kuma.users.delete")
    def users_delete(user_id: str) -> dict[str, object]:
        """利用者位置を削除し、削除前の値を返す。"""
        return {
            "schema_version": 1,
            "path": str(users.path),
            "deleted": _user_payload(users.delete(user_id)),
        }

    return server


mcp = create_server()


def main() -> None:
    """loopback Streamable HTTP serverをforeground起動する。"""
    port = int(os.environ.get("KUMA800_MCP_PORT", "8765"))
    mcp.run(transport="http", host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
