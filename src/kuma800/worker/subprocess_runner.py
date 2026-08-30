"""adapter.fetch()を子processへ隔離し、hangを外側からhard killする（Issue #8）。

Issue #8のUser Gateで「案1 subprocess runner」を採用した。`subprocess.run`
はmacOS/Windows双方で動く（`Popen.kill()`はWindowsでは`TerminateProcess`
相当）。子processは親のadapter objectをそのまま受け取らず、自分で
`source_id`からadapterを解決し直す。結果・失敗はJSON経由で標準出力へ
渡す。
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime

from kuma800.domain import AssertionKind, CandidateObservation, ReviewState, ScrapeBatch
from kuma800.scrapers.http import PublicFetchError

DEFAULT_TIMEOUT_SECONDS = 60.0


class AdapterTimedOut(RuntimeError):
    """子processがtimeout内に完了せず強制終了されたことを示す。"""

    def __init__(self, source_id: str, timeout_seconds: float) -> None:
        """timeoutしたsourceと上限秒数を保持する。"""
        self.source_id = source_id
        self.timeout_seconds = timeout_seconds
        super().__init__(f"adapter fetch timed out after {timeout_seconds}s: {source_id}")


class AdapterSubprocessError(RuntimeError):
    """子processが分類済みでない形で失敗したことを示す。"""


def run_adapter_in_subprocess(
    source_id: str,
    fetched_at: datetime,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> ScrapeBatch:
    """`source_id`のadapter.fetch()を子processで実行し、timeoutでhard killする。"""
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "kuma800.worker.subprocess_runner",
                source_id,
                fetched_at.astimezone(UTC).isoformat(),
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        # subprocess.runがtimeout時に子processをkill()済み。ここでは分類だけ行う。
        raise AdapterTimedOut(source_id, timeout_seconds) from error

    if completed.returncode != 0:
        _raise_from_child_error(completed.stdout, completed.stderr)
    payload = json.loads(completed.stdout)
    return _batch_from_dict(payload["batch"])


def _raise_from_child_error(stdout: str, stderr: str) -> None:
    """子processのJSONエラーを、親側で意味のある例外型へ復元する。"""
    try:
        payload = json.loads(stdout)
        error = payload["error"]
        error_type = str(error["type"])
        message = str(error["message"])
    except (json.JSONDecodeError, KeyError, TypeError, IndexError) as parse_error:
        raise AdapterSubprocessError(
            f"adapter subprocess failed without structured error: {stderr[-2000:]}"
        ) from parse_error
    if error_type == "PublicFetchError":
        raise PublicFetchError(
            message,
            reason=str(error.get("reason", "transport_error")),
            status_code=error.get("status_code"),
        )
    if error_type == "ValueError":
        raise ValueError(message)
    if error_type == "KeyError":
        raise KeyError(message)
    raise AdapterSubprocessError(f"{error_type}: {message}")


def _batch_from_dict(payload: dict[str, object]) -> ScrapeBatch:
    candidates_payload = payload["candidates"]
    assert isinstance(candidates_payload, list)
    candidates = tuple(_candidate_from_dict(item) for item in candidates_payload)
    return ScrapeBatch(
        final_url=str(payload["final_url"]),
        content_hash=str(payload["content_hash"]),
        candidates=candidates,
    )


def _candidate_from_dict(payload: object) -> CandidateObservation:
    assert isinstance(payload, dict)
    fields = dict(payload)
    fields["fetched_at"] = datetime.fromisoformat(str(fields["fetched_at"]))
    fields["event_time"] = (
        datetime.fromisoformat(str(fields["event_time"])) if fields.get("event_time") else None
    )
    fields["review_state"] = ReviewState(fields["review_state"])
    fields["assertion_kind"] = AssertionKind(fields["assertion_kind"])
    return CandidateObservation(**fields)


def _batch_to_dict(batch: ScrapeBatch) -> dict[str, object]:
    return {
        "final_url": batch.final_url,
        "content_hash": batch.content_hash,
        "candidates": [_candidate_to_dict(candidate) for candidate in batch.candidates],
    }


def _candidate_to_dict(candidate: CandidateObservation) -> dict[str, object]:
    fields = asdict(candidate)
    fields["fetched_at"] = candidate.fetched_at.astimezone(UTC).isoformat()
    fields["event_time"] = (
        candidate.event_time.astimezone(UTC).isoformat() if candidate.event_time else None
    )
    fields["review_state"] = candidate.review_state.value
    fields["assertion_kind"] = candidate.assertion_kind.value
    return fields


def main() -> None:
    """子process側entrypoint。`source_id fetched_at`をargvで受け取る。"""
    # 循環import回避のための遅延import（service.pyはこのmoduleを実行時にimportしない
    # が、subprocess起動という重い副作用をmodule import時に持たせないため統一する）。
    from kuma800.worker.service import resolve_adapter

    source_id = sys.argv[1]
    fetched_at = datetime.fromisoformat(sys.argv[2])
    adapter = resolve_adapter(source_id)
    if adapter is None:
        print(
            json.dumps(
                {"error": {"type": "KeyError", "message": f"unknown scraper source: {source_id}"}}
            )
        )
        sys.exit(1)
    try:
        batch = adapter.fetch(fetched_at=fetched_at)
    except Exception as error:
        error_payload: dict[str, object] = {"type": type(error).__name__, "message": str(error)}
        reason = getattr(error, "reason", None)
        if reason is not None:
            error_payload["reason"] = reason
        status_code = getattr(error, "status_code", None)
        if status_code is not None:
            error_payload["status_code"] = status_code
        print(json.dumps({"error": error_payload}))
        sys.exit(1)
    print(json.dumps({"batch": _batch_to_dict(batch)}))


if __name__ == "__main__":
    main()
