"""Shared pytest fixtures for isolated EON engine state."""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from eon import pfa_engine

REGRESSION_SEED_PROFILE = {
    "type": "personal",
    "income_streams": [
        {
            "name": "Primary income",
            "amount": 1800,
            "frequency": "bi-weekly",
        },
    ],
    "rent": 1700,
    "bills": {
        "car loan": 325,
        "phone": 25,
        "electricity": 50,
        "food": 400,
        "insurance": 100,
        "subscriptions": 40,
        "child support": 450,
    },
    "expenses": {},
}


@contextmanager
def isolated_engine(seed_profile: dict | None = None) -> Iterator[object]:
    """Bind the engine to a temp data directory and restore afterward."""
    original = {
        "BASE_DIR": pfa_engine.BASE_DIR,
        "FINANCE_DIR": pfa_engine.FINANCE_DIR,
        "REPORTS_DIR": pfa_engine.REPORTS_DIR,
        "PROFILE_PATH": pfa_engine.PROFILE_PATH,
        "PROFILE_BACKUP_PATH": pfa_engine.PROFILE_BACKUP_PATH,
        "SUMMARY_PATH": pfa_engine.SUMMARY_PATH,
        "CHANGE_JOURNAL_PATH": pfa_engine.CHANGE_JOURNAL_PATH,
    }

    temp_root = Path(tempfile.mkdtemp(prefix="eon_pytest_"))
    temp_finance_dir = temp_root / "finance"
    temp_reports_dir = temp_finance_dir / "reports"
    temp_finance_dir.mkdir(parents=True, exist_ok=True)
    temp_reports_dir.mkdir(parents=True, exist_ok=True)

    pfa_engine.BASE_DIR = temp_root
    pfa_engine.FINANCE_DIR = temp_finance_dir
    pfa_engine.REPORTS_DIR = temp_reports_dir
    pfa_engine.PROFILE_PATH = temp_finance_dir / "profile.json"
    pfa_engine.PROFILE_BACKUP_PATH = temp_finance_dir / "profile_last_backup.json"
    pfa_engine.SUMMARY_PATH = temp_finance_dir / "mastercard_summary.json"
    pfa_engine.CHANGE_JOURNAL_PATH = temp_finance_dir / "change_journal.csv"

    profile = seed_profile if seed_profile is not None else REGRESSION_SEED_PROFILE
    pfa_engine.write_json(
        pfa_engine.PROFILE_PATH,
        pfa_engine.update_profile_estimates(profile),
    )
    pfa_engine.write_json(pfa_engine.SUMMARY_PATH, [])

    try:
        yield pfa_engine
    finally:
        for key, value in original.items():
            setattr(pfa_engine, key, value)
        shutil.rmtree(temp_root, ignore_errors=True)


def current_profile(engine) -> dict:
    profile = engine.load_profile()
    if profile is None:
        raise AssertionError("expected seeded profile to load")
    profile = engine.update_profile_estimates(profile)
    engine.save_profile(profile)
    return profile


@pytest.fixture
def engine():
    with isolated_engine() as eng:
        yield eng
