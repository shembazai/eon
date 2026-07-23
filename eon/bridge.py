"""Programmatic EON interface for K1 agents and automation."""

from __future__ import annotations

from datetime import datetime, timezone
from importlib import import_module
from typing import Any

from eon.config import apply_paths_to_engine
from eon.task_log import ToolCallRecord, record_task_log


def _engine():
    engine = import_module("eon.pfa_engine")
    apply_paths_to_engine(engine)
    return engine


def _finalize(
    result: dict[str, Any],
    *,
    prompt: str,
    started: datetime,
    tools_called: list[ToolCallRecord],
    caller: str,
    agent: str,
    engine: Any,
    log: bool,
) -> dict[str, Any]:
    finished = datetime.now(timezone.utc)
    result["started_at"] = started.isoformat()
    result["finished_at"] = finished.isoformat()
    if log:
        entry = record_task_log(
            prompt=prompt,
            result=result,
            tools_called=tools_called,
            started_at=started,
            finished_at=finished,
            caller=caller,
            agent=agent,
            engine=engine,
        )
        result["task_id"] = entry.task_id
    return result


def query_finance_task(
    prompt: str,
    *,
    caller: str = "unknown",
    agent: str = "finance",
    log: bool = True,
    apply_mutations: bool = False,
) -> dict[str, Any]:
    """Run a finance prompt through EON's deterministic-first router.

    Returns a structured, auditable result suitable for K1 task logs.
    When ``log`` is True (default), appends a JSONL record to the EON task log.

    Profile mutations default to preview-only (``apply_mutations=False``) per
    EON constitution §3.8 — use interactive ``eon`` or pass True to apply.
    """
    engine = _engine()
    started = datetime.now(timezone.utc)
    tools_called: list[ToolCallRecord] = []

    profile, profile_error = engine.get_profile_context()
    tools_called.append(
        ToolCallRecord(
            tool="eon.get_profile_context",
            status="ok" if not profile_error else "failed",
            detail=profile_error or "profile loaded",
        )
    )
    if profile_error:
        return _finalize(
            {
                "status": "no_profile" if "No profile found" in str(profile_error) else "blocked",
                "routing": "blocked",
                "answer": profile_error,
            },
            prompt=prompt,
            started=started,
            tools_called=tools_called,
            caller=caller,
            agent=agent,
            engine=engine,
            log=log,
        )

    deterministic = engine.run_deterministic_engine(
        profile,
        prompt,
        apply_mutations=apply_mutations,
    )
    tools_called.append(
        ToolCallRecord(
            tool="eon.run_deterministic_engine",
            status="ok" if deterministic is not None else "skipped",
            detail=deterministic,
            routing="deterministic" if deterministic is not None else None,
        )
    )
    if deterministic is not None:
        status = "ok"
        routing = "deterministic"
        if isinstance(deterministic, str) and deterministic.startswith("Proposed "):
            status = "requires_confirm"
            routing = "mutation_preview"
        return _finalize(
            {
                "status": status,
                "routing": routing,
                "answer": deterministic,
                "profile_type": profile.get("type"),
                "apply_mutations": apply_mutations,
            },
            prompt=prompt,
            started=started,
            tools_called=tools_called,
            caller=caller,
            agent=agent,
            engine=engine,
            log=log,
        )

    if engine.is_mutation_like_prompt(prompt):
        answer = engine.build_unsupported_modification_message()
        tools_called.append(
            ToolCallRecord(
                tool="eon.mutation_firewall",
                status="blocked",
                detail=answer,
                routing="mutation_firewall",
            )
        )
        return _finalize(
            {
                "status": "blocked",
                "routing": "mutation_firewall",
                "answer": answer,
            },
            prompt=prompt,
            started=started,
            tools_called=tools_called,
            caller=caller,
            agent=agent,
            engine=engine,
            log=log,
        )

    answer = (
        "Deterministic logic did not apply. Use interactive `eon` Local AI "
        "or install optional AI extras for programmatic LLM fallback."
    )
    tools_called.append(
        ToolCallRecord(
            tool="eon.llm_fallback",
            status="requires_ai",
            detail=answer,
            routing="llm_fallback",
        )
    )
    return _finalize(
        {
            "status": "requires_ai",
            "routing": "llm_fallback",
            "answer": answer,
        },
        prompt=prompt,
        started=started,
        tools_called=tools_called,
        caller=caller,
        agent=agent,
        engine=engine,
        log=log,
    )


def profile_summary() -> dict[str, Any]:
    engine = _engine()
    profile = engine.load_profile()
    if not profile:
        return {"status": "no_profile", "summary": engine.profile_missing_message()}
    profile_type = engine.normalize_text(profile.get("type", "personal"))
    if profile_type != "personal":
        return {
            "status": "blocked",
            "summary": "EON supports personal profiles only in the current release.",
        }
    profile = engine.update_profile_estimates(profile)
    return {
        "status": "ok",
        "summary": engine.build_profile_summary_text(profile),
        "estimates": {
            "monthly_income": profile.get("estimated_monthly_income"),
            "monthly_expenses": profile.get("estimated_monthly_expenses"),
            "monthly_savings": profile.get("estimated_monthly_savings"),
        },
    }
