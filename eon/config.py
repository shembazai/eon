"""Path and environment resolution for EON.

Resolution order (K1 constitution: local-first, explicit state):
1. K1_EON_DATA_DIR — canonical K1 deployment data root
2. EON_PFA_BASE_DIR — legacy ~/AI-style base directory
3. ~/AI — development default

When K1_EON_DATA_DIR is set, profile and journal live directly under that
directory. Otherwise data lives under <base>/finance/ for backward
compatibility with the standalone finance tree.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from eon.local_models import resolve_model_path


def _legacy_ai_base() -> Path:
    return Path(os.getenv("EON_PFA_BASE_DIR", Path.home() / "AI"))


@dataclass(frozen=True)
class EonPaths:
    data_dir: Path
    reports_dir: Path
    models_dir: Path
    profile_path: Path
    profile_backup_path: Path
    summary_path: Path
    change_journal_path: Path
    model_path: Path
    log_dir: Path
    task_log_path: Path


def resolve_paths() -> EonPaths:
    k1_data = os.getenv("K1_EON_DATA_DIR")
    if k1_data:
        data_dir = Path(k1_data)
        models_dir = Path(os.getenv("K1_MODELS_DIR", "/opt/k1/models"))
    else:
        base = _legacy_ai_base()
        data_dir = base / "finance"
        models_dir = base / "models"

    # Env override wins; otherwise discover best local GGUF (no hardcoded required name).
    model_path = resolve_model_path(models_dir)
    log_dir = Path(os.getenv("K1_EON_LOG_DIR", os.getenv("EON_LOG_DIR", "/opt/k1/logs")))
    task_log_path = Path(
        os.getenv("K1_EON_TASK_LOG", log_dir / "eon-task-log.jsonl")
    )

    return EonPaths(
        data_dir=data_dir,
        reports_dir=data_dir / "reports",
        models_dir=models_dir,
        profile_path=data_dir / "profile.json",
        profile_backup_path=data_dir / "profile_last_backup.json",
        summary_path=data_dir / "mastercard_summary.json",
        change_journal_path=data_dir / "change_journal.csv",
        model_path=model_path,
        log_dir=log_dir,
        task_log_path=task_log_path,
    )


def apply_paths_to_engine(engine_module) -> EonPaths:
    """Bind resolved paths onto the monolithic engine module globals."""
    paths = resolve_paths()
    engine_module.BASE_DIR = paths.data_dir.parent if os.getenv("K1_EON_DATA_DIR") else _legacy_ai_base()
    engine_module.FINANCE_DIR = paths.data_dir
    engine_module.REPORTS_DIR = paths.reports_dir
    engine_module.MODELS_DIR = paths.models_dir
    engine_module.PROFILE_PATH = paths.profile_path
    engine_module.PROFILE_BACKUP_PATH = paths.profile_backup_path
    engine_module.SUMMARY_PATH = paths.summary_path
    engine_module.CHANGE_JOURNAL_PATH = paths.change_journal_path
    engine_module.MODEL_PATH = paths.model_path
    return paths
