"""Structured task logging for EON bridge invocations.

Aligns with K1 alpha observability (constitution §14.5): every
``query_finance_task`` call produces a machine-readable JSONL record that
answers objective, agent, tools, results, success/failure, duration, and
LLM fallback state without requiring source access.
"""

from __future__ import annotations

import fcntl
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from eon import __version__
from eon.config import resolve_paths

ANSWER_PREVIEW_LEN = 240


@dataclass
class ToolCallRecord:
    tool: str
    status: str
    detail: str | None = None
    routing: str | None = None


@dataclass
class TaskLogEntry:
    """K1 alpha observability fields for a single EON task execution."""

    task_id: str
    objective: str
    agent: str
    tools_called: list[ToolCallRecord]
    task_succeeded: bool
    failure_cause: str | None
    duration_ms: float
    llm_backend_available: bool
    llm_fallback_activated: bool
    started_at: str
    finished_at: str
    status: str
    routing: str
    component: str = "eon"
    version: str = __version__
    caller: str = "unknown"
    profile_type: str | None = None
    answer_preview: str | None = None
    benchmark_guard_applied: bool = False
    guard_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tools_called"] = [asdict(t) for t in self.tools_called]
        return payload


def resolve_task_log_path() -> Path:
    override = os.getenv("K1_EON_TASK_LOG")
    if override:
        return Path(override)
    return resolve_paths().log_dir / "eon-task-log.jsonl"


def _llm_backend_available(engine: Any) -> bool:
    try:
        if getattr(engine, "Llama", None) is None:
            return False
        model_path = getattr(engine, "MODEL_PATH", None)
        return bool(model_path and Path(model_path).exists())
    except Exception:
        return False


def _task_succeeded(status: str) -> bool:
    return status in ("ok", "requires_ai")


def _failure_cause(status: str, answer: str) -> str | None:
    if status in ("ok", "requires_ai"):
        return None
    return answer or status


def _answer_preview(answer: str | None) -> str | None:
    if not answer:
        return None
    text = answer.strip()
    if len(text) <= ANSWER_PREVIEW_LEN:
        return text
    return text[:ANSWER_PREVIEW_LEN] + "…"


def build_task_log_entry(
    *,
    prompt: str,
    result: dict[str, Any],
    tools_called: list[ToolCallRecord],
    started_at: datetime,
    finished_at: datetime,
    caller: str,
    agent: str,
    engine: Any,
    task_id: str | None = None,
) -> TaskLogEntry:
    status = str(result.get("status", "unknown"))
    routing = str(result.get("routing", "unknown"))
    answer = str(result.get("answer", ""))
    duration_ms = (finished_at - started_at).total_seconds() * 1000

    return TaskLogEntry(
        task_id=task_id or f"eon-{uuid4().hex[:12]}",
        objective=prompt,
        agent=agent,
        tools_called=tools_called,
        task_succeeded=_task_succeeded(status),
        failure_cause=_failure_cause(status, answer),
        duration_ms=round(duration_ms, 2),
        llm_backend_available=_llm_backend_available(engine),
        llm_fallback_activated=routing.startswith("llm"),
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
        status=status,
        routing=routing,
        caller=caller,
        profile_type=result.get("profile_type"),
        answer_preview=_answer_preview(answer),
        benchmark_guard_applied=bool(result.get("benchmark_guard_applied", False)),
        guard_reason=result.get("guard_reason"),
    )


def append_task_log(entry: TaskLogEntry, path: Path | None = None) -> Path:
    """Append one JSON line; exclusive flock keeps concurrent writers safe."""
    target = path or resolve_task_log_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry.to_dict(), sort_keys=True) + "\n"
    with open(target, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return target


def read_recent_entries(limit: int = 50, path: Path | None = None) -> list[dict[str, Any]]:
    """Return the most recent task log entries (newest last)."""
    target = path or resolve_task_log_path()
    if not target.exists():
        return []
    lines = target.read_text(encoding="utf-8").splitlines()
    entries: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def record_task_log(
    *,
    prompt: str,
    result: dict[str, Any],
    tools_called: list[ToolCallRecord],
    started_at: datetime,
    finished_at: datetime,
    caller: str,
    agent: str,
    engine: Any,
    path: Path | None = None,
) -> TaskLogEntry:
    entry = build_task_log_entry(
        prompt=prompt,
        result=result,
        tools_called=tools_called,
        started_at=started_at,
        finished_at=finished_at,
        caller=caller,
        agent=agent,
        engine=engine,
    )
    append_task_log(entry, path=path)
    return entry
