"""Packaging integration tests for EON within K1."""

from __future__ import annotations

import tomllib
from pathlib import Path


K1_ROOT = Path(__file__).resolve().parents[2]
EON_ROOT = K1_ROOT / "EON"


def test_k1_finance_extra_declares_eon():
    data = tomllib.loads((K1_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    finance = data["project"]["optional-dependencies"]["finance"]
    assert any("eon" in dep for dep in finance)


def test_eon_pyproject_has_cli_entrypoint():
    data = tomllib.loads((EON_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["scripts"]["eon"] == "eon.cli:app"


def test_install_headless_script_exists():
    script = EON_ROOT / "scripts" / "install_headless.sh"
    assert script.is_file()
    assert script.stat().st_mode & 0o111
