"""Port of inline regression harness cases to named pytest tests."""

from __future__ import annotations

from tests.conftest import current_profile, isolated_engine


def test_grounding_savings_ratio_computed(engine):
    grounding = engine.build_profile_llm_grounding(current_profile(engine))
    assert grounding.get("monthly_savings_pct_of_income") == 20.77


def test_supported_grounding_percentage_allowed(engine):
    grounding = engine.build_profile_llm_grounding(current_profile(engine))
    assert (
        engine.sanitize_llm_response("Rent is 43.59% of your monthly income.", grounding)
        == "Rent is 43.59% of your monthly income."
    )


def test_unsupported_benchmark_claim_rejected(engine):
    grounding = engine.build_profile_llm_grounding(current_profile(engine))
    assert engine.sanitize_llm_response(
        "Your savings rate is 43.15% of your income, which is below the recommended savings rate of 20%.",
        grounding,
    ) is None


def test_classify_reports_blocked_phrase_reason(engine):
    grounding = engine.build_profile_llm_grounding(current_profile(engine))
    clean, reason = engine.classify_llm_response(
        "That is below the recommended savings rate.", grounding
    )
    assert clean is None
    assert reason == "blocked phrase: 'recommended'"


def test_classify_reports_unsupported_percentage_reason(engine):
    grounding = engine.build_profile_llm_grounding(current_profile(engine))
    clean, reason = engine.classify_llm_response(
        "You should keep rent under 28% of income.", grounding
    )
    assert clean is None
    assert reason == "unsupported percentage: 28%"


def test_classify_allows_supported_response(engine):
    grounding = engine.build_profile_llm_grounding(current_profile(engine))
    clean, reason = engine.classify_llm_response(
        "Rent is 43.59% of your monthly income.", grounding
    )
    assert clean == "Rent is 43.59% of your monthly income."
    assert reason is None


class _FakeLLM:
    def __init__(self, text):
        self._text = text

    def __call__(self, *args, **kwargs):
        return {"choices": [{"text": self._text}]}


def test_ask_llm_flags_benchmark_guard(engine, monkeypatch):
    grounding = engine.build_profile_llm_grounding(current_profile(engine))
    monkeypatch.setattr(
        engine,
        "get_llm",
        lambda *a, **k: _FakeLLM("Your rent is below the recommended 30% ratio."),
    )
    result = engine.ask_llm(
        "what is the ideal rent ratio?",
        "Financial Profile",
        {},
        grounding_data=grounding,
        fallback_response="Grounded fallback answer.",
    )
    assert result["routing"] == "llm_sanitized_fallback"
    assert result["benchmark_guard_applied"] is True
    assert "blocked phrase" in result["guard_reason"]
    assert result["text"] == "Grounded fallback answer."


def test_ask_llm_passes_clean_response(engine, monkeypatch):
    grounding = engine.build_profile_llm_grounding(current_profile(engine))
    monkeypatch.setattr(
        engine,
        "get_llm",
        lambda *a, **k: _FakeLLM("Your rent is 43.59% of your monthly income."),
    )
    result = engine.ask_llm(
        "how much is rent vs income?",
        "Financial Profile",
        {},
        grounding_data=grounding,
        fallback_response="Grounded fallback answer.",
    )
    assert result["routing"] == "llm"
    assert result["benchmark_guard_applied"] is False
    assert result["text"] == "Your rent is 43.59% of your monthly income."


def test_ask_local_ai_logs_guard_to_task_log(engine, monkeypatch, tmp_path, capsys):
    log_path = tmp_path / "task.jsonl"
    monkeypatch.setenv("K1_EON_TASK_LOG", str(log_path))
    monkeypatch.setattr(
        engine,
        "get_llm",
        lambda *a, **k: _FakeLLM("That is below the recommended savings rate of 20%."),
    )

    engine.ask_local_ai("what is the ideal savings rate?")

    from eon.task_log import read_recent_entries

    entries = read_recent_entries(path=log_path)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["caller"] == "menu"
    assert entry["routing"] == "llm_sanitized_fallback"
    assert entry["benchmark_guard_applied"] is True
    assert "blocked phrase" in entry["guard_reason"]
    assert entry["llm_fallback_activated"] is True
    assert "guard applied" in capsys.readouterr().out


def test_ask_local_ai_logs_deterministic(engine, monkeypatch, tmp_path):
    log_path = tmp_path / "task.jsonl"
    monkeypatch.setenv("K1_EON_TASK_LOG", str(log_path))

    engine.ask_local_ai("what are my monthly expenses?")

    from eon.task_log import read_recent_entries

    entries = read_recent_entries(path=log_path)
    assert len(entries) == 1
    assert entries[0]["routing"] == "deterministic"
    assert entries[0]["caller"] == "menu"
    assert entries[0]["benchmark_guard_applied"] is False


def test_monthly_expenses_summary(engine):
    assert (
        engine.run_deterministic_engine(current_profile(engine), "what are my monthly expenses?")
        == "Estimated monthly expenses: $3090.00."
    )


def test_negative_rent_rejected(engine):
    assert (
        engine.run_deterministic_engine(current_profile(engine), "replace rent with -50")
        == "Invalid value for rent: negative amounts are not allowed. No changes were applied."
    )


def test_malformed_numeric_rejected(engine):
    assert (
        engine.run_deterministic_engine(current_profile(engine), "replace rent with abc")
        == "Invalid numeric value or incomplete update. No changes were applied."
    )


def test_ambiguous_field_rejected(engine):
    assert (
        engine.run_deterministic_engine(current_profile(engine), "replace bill with 50")
        == "Ambiguous field match for 'bill'. No changes were applied. Be more specific."
    )


def test_conflicting_income_frequencies_rejected(engine):
    assert (
        engine.run_deterministic_engine(
            current_profile(engine),
            "set weekly income to 900 and monthly income to 3500",
        )
        == "Conflicting income frequencies in one command. No changes were applied. Use one income frequency per command."
    )


def test_unsupported_rename_blocked(engine):
    assert (
        engine.run_deterministic_engine(current_profile(engine), "rename groceries to food")
        == engine.build_unsupported_modification_message()
    )


def test_scenario_routing(engine):
    assert (
        engine.run_deterministic_engine(current_profile(engine), "what happens if rent increases by 100")
        == "Under that scenario, your monthly income would be $3900.00, your rent would be $1800.00, your total monthly expenses would be $3190.00, and your monthly savings would become $710.00."
    )


def test_forecast_baseline_ending_cash(engine):
    baseline = engine.forecast_baseline(current_profile(engine), horizon_months=3)
    assert baseline["ending_cash"] == 2430.0


def test_forecast_baseline_deterministic_signature_stable(engine):
    profile = current_profile(engine)
    first = engine.forecast_baseline(profile, horizon_months=3)
    second = engine.forecast_baseline(profile, horizon_months=3)
    assert first["deterministic_signature"] == second["deterministic_signature"]


def test_forecast_goal_eta_whole_months(engine):
    goal = engine.forecast_goal_eta(current_profile(engine), goal_amount=3000)
    assert goal["goal_month"] == 4


def test_forecast_scenario_monthly_savings(engine):
    scenario = engine.forecast_scenario(
        current_profile(engine), horizon_months=2, scenario_delta={"rent": 100}
    )
    assert scenario["monthly_savings"] == 710.0


def test_decision_bundle_fixed_cost_flag_present(engine):
    bundle = engine.build_decision_bundle(current_profile(engine))
    assert "fixed_cost_concentration" in bundle["policy_flags"]


def test_decision_bundle_top_action_code(engine):
    bundle = engine.build_decision_bundle(current_profile(engine))
    assert bundle["actions"][0]["code"] == "reduce_top_fixed_cost"


def test_actionable_advice_routed_deterministically(engine):
    assert (
        engine.run_deterministic_engine(current_profile(engine), "give me actionable advice")
        == "Top finding: Fixed monthly costs are $3090.00 against monthly income of $3900.00.\nAction priorities:\n1. Rent is the largest expense. A reduction there will change monthly savings more than trimming small categories.\n2. The biggest leverage point is currently rent at $1700.00 per month.\n3. The budget is concentrated in rent, so that line deserves review before scattered minor expenses.\nStrength to preserve: The profile currently produces $810.00 in monthly savings."
    )


def test_compact_weak_points_summary_routed_deterministically(engine):
    assert (
        engine.run_deterministic_engine(
            current_profile(engine),
            "give me a two-sentence qualitative summary of my current financial weak points",
        )
        == "Top risk: Fixed monthly costs are $3090.00 against monthly income of $3900.00. First leverage point: Rent is the largest expense. A reduction there will change monthly savings more than trimming small categories; current strength: the profile currently produces $810.00 in monthly savings."
    )


def test_valid_rent_update_saved(engine):
    assert (
        engine.run_deterministic_engine(current_profile(engine), "replace rent with 1810")
        == "Saved changes: rent changed to $1810.00. Your estimated monthly income is now $3900.00, your total monthly expenses are $3200.00, and your monthly savings are $700.00."
    )


def test_journal_row_count_after_saved_change(engine):
    engine.run_deterministic_engine(current_profile(engine), "replace rent with 1810")
    assert engine.count_change_journal_entries() == 1


def test_no_op_does_not_save(engine):
    engine.run_deterministic_engine(current_profile(engine), "replace rent with 1810")
    assert (
        engine.run_deterministic_engine(current_profile(engine), "replace rent with 1810")
        == "No effective change was applied. The requested values already match the current profile."
    )


def test_journal_row_count_unchanged_after_no_op(engine):
    engine.run_deterministic_engine(current_profile(engine), "replace rent with 1810")
    engine.run_deterministic_engine(current_profile(engine), "replace rent with 1810")
    assert engine.count_change_journal_entries() == 1


def test_undo_last_change(engine):
    engine.run_deterministic_engine(current_profile(engine), "replace rent with 1810")
    assert (
        engine.run_deterministic_engine(current_profile(engine), "undo last change")
        == "Last saved change was undone. Your estimated monthly income is now $3900.00, your total monthly expenses are $3090.00, and your monthly savings are $810.00."
    )


def test_journal_row_count_unchanged_after_undo(engine):
    engine.run_deterministic_engine(current_profile(engine), "replace rent with 1810")
    engine.run_deterministic_engine(current_profile(engine), "undo last change")
    assert engine.count_change_journal_entries() == 1


def test_generic_income_update_blocked_with_multi_income(engine):
    profile = current_profile(engine)
    profile["income_streams"].append(
        {"name": "Side gig", "amount": 500, "frequency": "monthly"}
    )
    engine.save_profile(profile)
    assert (
        engine.run_deterministic_engine(current_profile(engine), "set monthly income to 3500")
        == "Multiple income streams detected. No generic income change was applied. Use Edit Profile instead."
    )


def test_inline_regression_harness_still_passes():
    from eon import pfa_engine

    with isolated_engine():
        assert pfa_engine.run_regression_tests() == 0
