import json
from unittest.mock import patch

from typer.testing import CliRunner

from eon.cli import app


runner = CliRunner()


def test_cli_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "EON v" in result.stdout


def test_cli_health_json():
    result = runner.invoke(app, ["health", "--json"])
    assert result.exit_code in (0, 1)
    payload = json.loads(result.stdout)
    assert payload["version"]
    assert "checks" in payload


def test_cli_query_json(tmp_path, monkeypatch):
    monkeypatch.setenv("K1_EON_TASK_LOG", str(tmp_path / "task.jsonl"))
    result = runner.invoke(app, ["query", "what are my monthly expenses?"])
    assert result.exit_code in (0, 1)
    payload = json.loads(result.stdout)
    assert payload["routing"] in ("blocked", "deterministic", "llm_fallback")
    assert "answer" in payload
    assert "task_id" in payload


def test_cli_logs_json(tmp_path, monkeypatch):
    log_path = tmp_path / "task.jsonl"
    log_path.write_text(
        '{"task_id":"eon-1","status":"ok","objective":"probe","duration_ms":1.0}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("K1_EON_TASK_LOG", str(log_path))
    result = runner.invoke(app, ["logs", "--json", "--limit", "5"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["entries"][0]["task_id"] == "eon-1"


def test_cli_no_args_launches_menu():
    with patch("eon.cli.apply_paths_to_engine"), patch(
        "eon.pfa_engine.entrypoint", return_value=0
    ) as menu:
        result = runner.invoke(app, [])
    assert result.exit_code == 0
    menu.assert_called_once_with()


def test_cli_menu_command_launches_menu():
    with patch("eon.cli.apply_paths_to_engine"), patch(
        "eon.pfa_engine.entrypoint", return_value=0
    ) as menu:
        result = runner.invoke(app, ["menu"])
    assert result.exit_code == 0
    menu.assert_called_once_with()


def test_cli_self_test():
    result = runner.invoke(app, ["self-test"])
    assert result.exit_code == 0
    assert "25/25 passed" in result.stdout
