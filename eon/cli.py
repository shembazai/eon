"""EON CLI — K1-aligned operator interface."""

from __future__ import annotations

import json
from typing import Optional

import typer

from eon import __version__
from eon.config import apply_paths_to_engine
from eon.health import run_health_check
from eon.logger import configure_logging

app = typer.Typer(
    name="eon",
    help="EON — deterministic local-first personal finance for K1.",
    # Bare `eon` launches the interactive menu (same as `eon menu`).
    no_args_is_help=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"EON v{__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable DEBUG logging."),
) -> None:
    level = "DEBUG" if verbose else "INFO"
    configure_logging(level=level)
    if ctx.invoked_subcommand is None:
        from eon import pfa_engine

        apply_paths_to_engine(pfa_engine)
        raise SystemExit(pfa_engine.entrypoint())


@app.command()
def health(
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Operator health dashboard (constitution §3.9 resilience)."""
    report = run_health_check()
    if as_json:
        typer.echo(json.dumps(report.to_dict(), indent=2))
    else:
        typer.echo(f"Health: {report.status} (EON v{report.version})")
        for check in report.checks:
            typer.echo(f"  [{check.status}] {check.name}: {check.detail}")
    raise typer.Exit(code=0 if report.passed else 1)


@app.command("self-test")
def self_test() -> None:
    """Run the built-in regression harness."""
    from eon import pfa_engine

    apply_paths_to_engine(pfa_engine)
    code = pfa_engine.run_regression_tests()
    raise typer.Exit(code=code)


@app.command()
def query(
    prompt: str,
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Apply profile mutations (default: preview-only).",
    ),
) -> None:
    """Run a single deterministic-first finance query."""
    from eon.bridge import query_finance_task

    result = query_finance_task(prompt, caller="cli", apply_mutations=apply)
    typer.echo(json.dumps(result, indent=2))
    ok_statuses = ("ok", "requires_ai", "requires_confirm")
    raise typer.Exit(code=0 if result.get("status") in ok_statuses else 1)


@app.command()
def logs(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of recent entries."),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Show recent EON task log entries (constitution §14.5 observability)."""
    from eon.task_log import read_recent_entries, resolve_task_log_path

    entries = read_recent_entries(limit=limit)
    if as_json:
        typer.echo(json.dumps({"path": str(resolve_task_log_path()), "entries": entries}, indent=2))
    elif not entries:
        typer.echo(f"No task log entries at {resolve_task_log_path()}")
    else:
        typer.echo(f"Task log: {resolve_task_log_path()} ({len(entries)} shown)")
        for entry in entries:
            status = entry.get("status", "?")
            task_id = entry.get("task_id", "?")
            objective = entry.get("objective", "")[:60]
            duration = entry.get("duration_ms", 0)
            guard = ""
            if entry.get("benchmark_guard_applied"):
                guard = f" 🛡️ guard[{entry.get('guard_reason') or 'benchmark blocked'}]"
            typer.echo(f"  [{status}] {task_id} {duration:.1f}ms — {objective}{guard}")
    raise typer.Exit(code=0)


@app.command()
def menu() -> None:
    """Launch the interactive EON menu."""
    from eon import pfa_engine

    apply_paths_to_engine(pfa_engine)
    raise SystemExit(pfa_engine.entrypoint())


def entrypoint() -> int:
    """Default entry: interactive menu when invoked without subcommand."""
    import sys

    if len(sys.argv) > 1:
        app()
        return 0
    from eon import pfa_engine

    apply_paths_to_engine(pfa_engine)
    return pfa_engine.entrypoint()


if __name__ == "__main__":
    raise SystemExit(entrypoint())
