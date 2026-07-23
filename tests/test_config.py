import os
from pathlib import Path

from eon.config import resolve_paths


def test_legacy_layout_uses_finance_subdir(monkeypatch):
    monkeypatch.delenv("K1_EON_DATA_DIR", raising=False)
    monkeypatch.setenv("EON_PFA_BASE_DIR", "/tmp/eon-config-test")
    paths = resolve_paths()
    assert paths.data_dir == Path("/tmp/eon-config-test/finance")
    assert paths.profile_path == Path("/tmp/eon-config-test/finance/profile.json")


def test_k1_layout_uses_data_dir_directly(monkeypatch):
    monkeypatch.setenv("K1_EON_DATA_DIR", "/opt/k1/data/eon")
    monkeypatch.delenv("EON_PFA_BASE_DIR", raising=False)
    paths = resolve_paths()
    assert paths.data_dir == Path("/opt/k1/data/eon")
    assert paths.profile_path == Path("/opt/k1/data/eon/profile.json")
    assert paths.models_dir == Path("/opt/k1/models")


def test_k1_models_dir_override(monkeypatch):
    monkeypatch.setenv("K1_EON_DATA_DIR", "/opt/k1/data/eon")
    monkeypatch.setenv("K1_MODELS_DIR", "/custom/models")
    paths = resolve_paths()
    assert paths.models_dir == Path("/custom/models")


def test_model_path_env_override(monkeypatch, tmp_path):
    monkeypatch.delenv("K1_EON_DATA_DIR", raising=False)
    monkeypatch.setenv("EON_PFA_BASE_DIR", str(tmp_path))
    override = tmp_path / "override.gguf"
    override.touch()
    with override.open("r+b") as handle:
        handle.truncate(60 * 1024 * 1024)
    monkeypatch.setenv("EON_PFA_MODEL_PATH", str(override))
    paths = resolve_paths()
    assert paths.model_path == override


def test_model_path_discovers_best_fit(monkeypatch, tmp_path):
    monkeypatch.delenv("K1_EON_DATA_DIR", raising=False)
    monkeypatch.delenv("EON_PFA_MODEL_PATH", raising=False)
    monkeypatch.setenv("EON_PFA_BASE_DIR", str(tmp_path))
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    preferred = models_dir / "mistral-7b-instruct-q4_k_m.gguf"
    other = models_dir / "other.gguf"
    for path in (preferred, other):
        path.touch()
        with path.open("r+b") as handle:
            handle.truncate(60 * 1024 * 1024)
    paths = resolve_paths()
    assert paths.model_path == preferred.resolve()


def test_task_log_path_default(monkeypatch):
    monkeypatch.delenv("K1_EON_TASK_LOG", raising=False)
    monkeypatch.setenv("K1_EON_LOG_DIR", "/var/log/k1")
    paths = resolve_paths()
    assert paths.task_log_path == Path("/var/log/k1/eon-task-log.jsonl")


def test_task_log_path_override(monkeypatch):
    monkeypatch.setenv("K1_EON_TASK_LOG", "/tmp/custom-task-log.jsonl")
    paths = resolve_paths()
    assert paths.task_log_path == Path("/tmp/custom-task-log.jsonl")
