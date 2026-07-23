"""EON startup and operator health checks (K1 constitution §3.9)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from importlib import import_module
from typing import Any

from eon import __version__
from eon.config import apply_paths_to_engine, resolve_paths
from eon.task_log import resolve_task_log_path


@dataclass
class HealthCheck:
    name: str
    status: str  # passed | failed | warning | skipped
    detail: str
    critical: bool = True


@dataclass
class HealthReport:
    status: str
    version: str
    timestamp: str
    checks: list[HealthCheck] = field(default_factory=list)
    paths: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(
            c.status in ("passed", "warning", "skipped") or not c.critical
            for c in self.checks
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "version": self.version,
            "timestamp": self.timestamp,
            "passed": self.passed,
            "checks": [asdict(c) for c in self.checks],
            "paths": self.paths,
        }


def _check(name: str, ok: bool, detail: str, *, critical: bool = True, warning: bool = False) -> HealthCheck:
    if ok:
        return HealthCheck(name=name, status="passed", detail=detail, critical=critical)
    if warning:
        return HealthCheck(name=name, status="warning", detail=detail, critical=False)
    return HealthCheck(name=name, status="failed", detail=detail, critical=critical)


def run_health_check() -> HealthReport:
    paths = resolve_paths()
    engine = import_module("eon.pfa_engine")
    apply_paths_to_engine(engine)

    checks: list[HealthCheck] = []

    try:
        paths.data_dir.mkdir(parents=True, exist_ok=True)
        probe = paths.data_dir / ".eon_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        checks.append(_check("data_dir_writable", True, str(paths.data_dir)))
    except OSError as exc:
        checks.append(_check("data_dir_writable", False, f"{paths.data_dir}: {exc}"))

    profile = engine.read_json(paths.profile_path)
    if profile is None:
        checks.append(
            _check(
                "profile_present",
                False,
                "No profile.json — create one with `eon` menu option 1 or legacy CLI.",
                critical=False,
                warning=True,
            )
        )
    else:
        normalized = engine.normalize_profile_schema(profile)
        checks.append(
            _check(
                "profile_valid",
                normalized.get("type") == "personal",
                f"type={normalized.get('type')!r}",
            )
        )

    if paths.change_journal_path.exists():
        try:
            with open(paths.change_journal_path, encoding="utf-8") as handle:
                handle.readline()
            checks.append(_check("change_journal_readable", True, str(paths.change_journal_path)))
        except OSError as exc:
            checks.append(_check("change_journal_readable", False, str(exc)))
    else:
        checks.append(
            _check(
                "change_journal_readable",
                True,
                "journal not created yet (expected before first mutation)",
                critical=False,
            )
        )

    try:
        sample = engine.update_profile_estimates(
            {
                "type": "personal",
                "income_streams": [{"name": "probe", "amount": 1000, "frequency": "monthly"}],
                "rent": 0,
                "bills": {},
                "expenses": {},
            }
        )
        ok = float(sample.get("estimated_monthly_income", 0)) == 1000.0
        checks.append(_check("deterministic_engine", ok, "estimate probe"))
    except Exception as exc:
        checks.append(_check("deterministic_engine", False, str(exc)))

    try:
        import matplotlib.pyplot  # noqa: F401

        checks.append(_check("charts_available", True, "matplotlib installed", critical=False))
    except ImportError:
        checks.append(
            _check(
                "charts_available",
                False,
                "matplotlib not installed — View Profile charts degrade gracefully",
                critical=False,
                warning=True,
            )
        )

    if engine.Llama is None:
        checks.append(
            _check(
                "local_ai_runtime",
                False,
                "llama-cpp-python not installed — deterministic mode only",
                critical=False,
                warning=True,
            )
        )
    else:
        from eon.local_models import discover_gguf_models, recommend_best_model

        discovered = discover_gguf_models(paths.models_dir)
        suggested = recommend_best_model(discovered)
        if paths.model_path.exists() and paths.model_path.name != ".no_gguf_discovered":
            detail = str(paths.model_path)
            if suggested is not None and suggested.path == paths.model_path.resolve():
                detail += " (suggested best fit)"
            checks.append(_check("local_ai_model", True, detail, critical=False))
        elif discovered:
            names = ", ".join(m.name for m in discovered[:3])
            more = "" if len(discovered) <= 3 else f" (+{len(discovered) - 3} more)"
            suggestion = f"; suggested: {suggested.name}" if suggested else ""
            checks.append(
                _check(
                    "local_ai_model",
                    False,
                    f"no model selected; {len(discovered)} GGUF available ({names}{more}){suggestion}",
                    critical=False,
                    warning=True,
                )
            )
        else:
            checks.append(
                _check(
                    "local_ai_model",
                    False,
                    f"no runnable GGUF discovered in {paths.models_dir}",
                    critical=False,
                    warning=True,
                )
            )

    task_log_path = resolve_task_log_path()
    try:
        task_log_path.parent.mkdir(parents=True, exist_ok=True)
        probe = task_log_path.parent / ".eon_task_log_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        checks.append(
            _check(
                "task_log_writable",
                True,
                str(task_log_path),
                critical=False,
            )
        )
    except OSError as exc:
        checks.append(
            _check(
                "task_log_writable",
                False,
                f"{task_log_path}: {exc}",
                critical=False,
                warning=True,
            )
        )

    critical_failed = any(c.critical and c.status == "failed" for c in checks)
    status = "failed" if critical_failed else "degraded" if any(c.status == "warning" for c in checks) else "ok"

    return HealthReport(
        status=status,
        version=__version__,
        timestamp=datetime.now(timezone.utc).isoformat(),
        checks=checks,
        paths={
            "data_dir": str(paths.data_dir),
            "profile": str(paths.profile_path),
            "change_journal": str(paths.change_journal_path),
            "model": str(paths.model_path),
            "log_dir": str(paths.log_dir),
            "task_log": str(task_log_path),
        },
    )


def health_json() -> str:
    return json.dumps(run_health_check().to_dict(), indent=2)
