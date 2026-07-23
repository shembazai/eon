from eon.config import resolve_paths


def test_resolve_paths_legacy_layout():
    paths = resolve_paths()
    assert paths.profile_path.name == "profile.json"
    assert paths.change_journal_path.name == "change_journal.csv"
    assert "finance" in str(paths.data_dir) or paths.data_dir.name == "eon"


def test_health_report_structure():
    from eon.health import run_health_check

    report = run_health_check()
    data = report.to_dict()
    assert "status" in data
    assert "checks" in data
    assert isinstance(data["checks"], list)
    assert data["version"]
