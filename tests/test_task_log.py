"""Tests for EON structured task logging (Phase B observability)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from eon.task_log import (
    TaskLogEntry,
    ToolCallRecord,
    append_task_log,
    build_task_log_entry,
    read_recent_entries,
    record_task_log,
    resolve_task_log_path,
)


class _FakeEngine:
    Llama = None
    MODEL_PATH = Path("/nonexistent/model.gguf")


def test_resolve_task_log_path_default(monkeypatch, tmp_path):
    monkeypatch.delenv("K1_EON_TASK_LOG", raising=False)
    monkeypatch.setenv("K1_EON_LOG_DIR", str(tmp_path / "logs"))
    assert resolve_task_log_path() == tmp_path / "logs" / "eon-task-log.jsonl"


def test_resolve_task_log_path_override(monkeypatch, tmp_path):
    custom = tmp_path / "custom.jsonl"
    monkeypatch.setenv("K1_EON_TASK_LOG", str(custom))
    assert resolve_task_log_path() == custom


def test_build_task_log_entry_ok():
    started = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)
    finished = datetime(2026, 7, 13, 12, 0, 0, 100000, tzinfo=timezone.utc)
    tools = [
        ToolCallRecord(tool="eon.get_profile_context", status="ok", detail="profile loaded"),
        ToolCallRecord(
            tool="eon.run_deterministic_engine",
            status="ok",
            detail="Monthly expenses: $3090.00",
            routing="deterministic",
        ),
    ]
    entry = build_task_log_entry(
        prompt="what are my monthly expenses?",
        result={
            "status": "ok",
            "routing": "deterministic",
            "answer": "Monthly expenses: $3090.00",
            "profile_type": "personal",
        },
        tools_called=tools,
        started_at=started,
        finished_at=finished,
        caller="pytest",
        agent="finance",
        engine=_FakeEngine(),
        task_id="eon-test123",
    )
    payload = entry.to_dict()
    assert payload["task_id"] == "eon-test123"
    assert payload["objective"] == "what are my monthly expenses?"
    assert payload["agent"] == "finance"
    assert payload["caller"] == "pytest"
    assert payload["task_succeeded"] is True
    assert payload["failure_cause"] is None
    assert payload["routing"] == "deterministic"
    assert payload["llm_fallback_activated"] is False
    assert payload["llm_backend_available"] is False
    assert len(payload["tools_called"]) == 2
    assert payload["tools_called"][1]["routing"] == "deterministic"


def test_build_task_log_entry_no_profile_failure():
    started = datetime.now(timezone.utc)
    finished = started
    entry = build_task_log_entry(
        prompt="budget check",
        result={"status": "no_profile", "routing": "blocked", "answer": "No profile found."},
        tools_called=[ToolCallRecord(tool="eon.get_profile_context", status="failed", detail="No profile found.")],
        started_at=started,
        finished_at=finished,
        caller="cli",
        agent="finance",
        engine=_FakeEngine(),
    )
    assert entry.task_succeeded is False
    assert entry.failure_cause == "No profile found."


def test_append_and_read_roundtrip(tmp_path):
    log_path = tmp_path / "eon-task-log.jsonl"
    entry = TaskLogEntry(
        task_id="eon-abc",
        objective="test prompt",
        agent="finance",
        tools_called=[ToolCallRecord(tool="eon.bridge.query_finance_task", status="ok")],
        task_succeeded=True,
        failure_cause=None,
        duration_ms=1.0,
        llm_backend_available=False,
        llm_fallback_activated=False,
        started_at="2026-07-13T12:00:00+00:00",
        finished_at="2026-07-13T12:00:00+00:00",
        status="ok",
        routing="deterministic",
        caller="pytest",
    )
    append_task_log(entry, path=log_path)
    append_task_log(entry, path=log_path)

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    parsed = json.loads(lines[0])
    assert parsed["task_id"] == "eon-abc"
    assert parsed["objective"] == "test prompt"

    recent = read_recent_entries(limit=1, path=log_path)
    assert len(recent) == 1
    assert recent[0]["task_id"] == "eon-abc"


def test_record_task_log_integration(tmp_path):
    log_path = tmp_path / "task.jsonl"
    started = datetime.now(timezone.utc)
    finished = started
    entry = record_task_log(
        prompt="income check",
        result={"status": "requires_ai", "routing": "llm_fallback", "answer": "needs ai"},
        tools_called=[ToolCallRecord(tool="eon.llm_fallback", status="requires_ai", routing="llm_fallback")],
        started_at=started,
        finished_at=finished,
        caller="finance_agent",
        agent="finance",
        engine=_FakeEngine(),
        path=log_path,
    )
    assert entry.task_id.startswith("eon-")
    assert entry.llm_fallback_activated is True
    assert entry.task_succeeded is True
    assert log_path.exists()


def test_read_recent_entries_missing_file(tmp_path):
    assert read_recent_entries(path=tmp_path / "missing.jsonl") == []


def test_build_task_log_entry_captures_benchmark_guard():
    started = datetime.now(timezone.utc)
    entry = build_task_log_entry(
        prompt="what is the ideal savings rate?",
        result={
            "status": "ok",
            "routing": "llm_sanitized_fallback",
            "answer": "Grounded fallback answer.",
            "profile_type": "personal",
            "benchmark_guard_applied": True,
            "guard_reason": "blocked phrase: 'recommended'",
        },
        tools_called=[ToolCallRecord(tool="eon.ask_llm", status="blocked", routing="llm_sanitized_fallback")],
        started_at=started,
        finished_at=started,
        caller="menu",
        agent="finance",
        engine=_FakeEngine(),
    )
    payload = entry.to_dict()
    assert payload["benchmark_guard_applied"] is True
    assert payload["guard_reason"] == "blocked phrase: 'recommended'"
    assert payload["llm_fallback_activated"] is True
    assert payload["task_succeeded"] is True


def test_build_task_log_entry_defaults_guard_false():
    started = datetime.now(timezone.utc)
    entry = build_task_log_entry(
        prompt="what are my monthly expenses?",
        result={"status": "ok", "routing": "deterministic", "answer": "x"},
        tools_called=[],
        started_at=started,
        finished_at=started,
        caller="menu",
        agent="finance",
        engine=_FakeEngine(),
    )
    assert entry.benchmark_guard_applied is False
    assert entry.guard_reason is None
    assert entry.llm_fallback_activated is False
