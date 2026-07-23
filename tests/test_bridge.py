from eon.bridge import query_finance_task


def test_query_without_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("K1_EON_TASK_LOG", str(tmp_path / "task.jsonl"))
    result = query_finance_task("what are my monthly expenses?", caller="pytest", log=True)
    assert result["status"] in ("no_profile", "ok", "requires_ai")
    assert "routing" in result
    assert "answer" in result
    assert "task_id" in result
    assert "started_at" in result
    assert "finished_at" in result


def test_query_with_seeded_profile(engine, monkeypatch, tmp_path):
    from tests.conftest import current_profile
    from eon import bridge

    current_profile(engine)
    monkeypatch.setattr(bridge, "_engine", lambda: engine)
    monkeypatch.setenv("K1_EON_TASK_LOG", str(tmp_path / "task.jsonl"))
    result = bridge.query_finance_task("what are my monthly expenses?", caller="pytest", log=True)
    assert result["status"] == "ok"
    assert result["routing"] == "deterministic"
    assert "3090.00" in result["answer"]
    assert result["task_id"].startswith("eon-")

    log_lines = (tmp_path / "task.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 1
    import json

    entry = json.loads(log_lines[0])
    assert entry["objective"] == "what are my monthly expenses?"
    assert entry["task_succeeded"] is True
    assert entry["agent"] == "finance"
    assert len(entry["tools_called"]) >= 2


def test_mutation_defaults_to_preview(engine, monkeypatch):
    from tests.conftest import current_profile
    from eon import bridge

    current_profile(engine)
    monkeypatch.setattr(bridge, "_engine", lambda: engine)
    before = engine.load_profile()["rent"]
    result = bridge.query_finance_task(
        "replace rent with 1810",
        caller="pytest",
        log=False,
        apply_mutations=False,
    )
    assert result["status"] == "requires_confirm"
    assert "Proposed changes" in result["answer"]
    assert engine.load_profile()["rent"] == before


def test_mutation_applies_when_confirmed(engine, monkeypatch):
    from tests.conftest import current_profile
    from eon import bridge

    current_profile(engine)
    monkeypatch.setattr(bridge, "_engine", lambda: engine)
    result = bridge.query_finance_task(
        "replace rent with 1810",
        caller="pytest",
        log=False,
        apply_mutations=True,
    )
    assert result["status"] == "ok"
    assert "Saved changes" in result["answer"]
    assert engine.load_profile()["rent"] == 1810.0
