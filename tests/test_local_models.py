"""Tests for replaceable local GGUF discovery and recommendation."""

from __future__ import annotations

from pathlib import Path

from eon.local_models import (
    DEFAULT_MODEL_SUGGESTION,
    discover_gguf_models,
    format_model_choice_menu,
    recommend_best_model,
    resolve_model_path,
    score_model_for_eon,
)


def _touch_gguf(path: Path, size_bytes: int) -> Path:
    path.touch()
    with path.open("r+b") as handle:
        handle.truncate(size_bytes)
    return path


def test_discover_skips_vocab_and_tiny_files(tmp_path):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    _touch_gguf(models_dir / "ggml-vocab-llama.gguf", 1024)
    _touch_gguf(models_dir / "tiny-stub.gguf", 1024)
    _touch_gguf(models_dir / "mistral-7b-instruct-q4_k_m.gguf", 60 * 1024 * 1024)

    found = discover_gguf_models(models_dir)
    assert len(found) == 1
    assert found[0].name == "mistral-7b-instruct-q4_k_m.gguf"


def test_discover_skips_split_shards_prefers_merged(tmp_path):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    size = 80 * 1024 * 1024
    _touch_gguf(models_dir / "qwen2.5-7b-instruct-q5_k_m-00001-of-00002.gguf", size)
    _touch_gguf(models_dir / "qwen2.5-7b-instruct-q5_k_m-00002-of-00002.gguf", size)
    merged = _touch_gguf(models_dir / "qwen2.5-7b-instruct-q5_k_m.gguf", size)

    found = discover_gguf_models(models_dir)
    assert len(found) == 1
    assert found[0].path == merged.resolve()
    best = recommend_best_model(found)
    assert best is not None
    assert best.path == merged.resolve()


def test_recommend_prefers_instruct_7b_q4km_over_coder_70b(tmp_path):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    size = 80 * 1024 * 1024
    _touch_gguf(models_dir / "codellama-70b-q8_0.gguf", size)
    preferred = _touch_gguf(models_dir / "mistral-7b-instruct-q4_k_m.gguf", size)
    _touch_gguf(models_dir / "random-weights.gguf", size)

    found = discover_gguf_models(models_dir)
    best = recommend_best_model(found)
    assert best is not None
    assert best.path == preferred.resolve()
    assert any("instruct" in r.lower() or "7b" in r.lower() for r in best.reasons)


def test_resolve_model_path_env_override_wins(tmp_path, monkeypatch):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    size = 80 * 1024 * 1024
    _touch_gguf(models_dir / "mistral-7b-instruct-q4_k_m.gguf", size)
    override = tmp_path / "custom.gguf"
    _touch_gguf(override, size)
    monkeypatch.setenv("EON_PFA_MODEL_PATH", str(override))

    assert resolve_model_path(models_dir) == override


def test_resolve_model_path_discovers_best_without_hardcoded_name(tmp_path, monkeypatch):
    monkeypatch.delenv("EON_PFA_MODEL_PATH", raising=False)
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    size = 80 * 1024 * 1024
    preferred = _touch_gguf(models_dir / "llama-8b-instruct-q5_k_m.gguf", size)
    _touch_gguf(models_dir / "other-3b.gguf", size)

    resolved = resolve_model_path(models_dir)
    assert resolved == preferred.resolve()
    assert "mistral-clean-q4_k_m.gguf" not in str(resolved)


def test_resolve_model_path_empty_dir_uses_sentinel_not_hardcoded(tmp_path, monkeypatch):
    monkeypatch.delenv("EON_PFA_MODEL_PATH", raising=False)
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    resolved = resolve_model_path(models_dir)
    assert resolved == models_dir / ".no_gguf_discovered"
    assert not resolved.exists()


def test_format_menu_marks_suggestion(tmp_path):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    size = 80 * 1024 * 1024
    _touch_gguf(models_dir / "phi-3-mini-instruct-q4_k_m.gguf", size)
    _touch_gguf(models_dir / "coder-only-7b.gguf", size)
    models = discover_gguf_models(models_dir)
    suggested = recommend_best_model(models)
    text = format_model_choice_menu(models, suggested)
    assert "replaceable tools" in text
    assert "suggested best fit" in text
    assert suggested is not None
    assert suggested.name in text


def test_format_empty_menu_offers_one_model_to_add():
    text = format_model_choice_menu([], None)
    assert "(none found)" in text
    assert f"Suggested model to add: {DEFAULT_MODEL_SUGGESTION}" in text
    assert text.count("Suggested model to add:") == 1


def test_score_excludes_embedding_name():
    score, reasons = score_model_for_eon(Path("nomic-embed-text.gguf"), 200 * 1024 * 1024)
    assert score <= -10_000
    assert "excluded" in reasons[0]
