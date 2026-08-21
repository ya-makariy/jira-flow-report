"""Version reporting, staleness detection, and the prompt fallbacks.

The prompts themselves need a terminal, so what is tested here is the contract
that matters off a terminal: never block, never guess silently, always resolve
to the stated default.
"""

from __future__ import annotations

import json

import pytest

from jira_flow_report import buildinfo, prompts, ui, update

# --- build info ----------------------------------------------------------------


def test_buildinfo_always_resolves():
    b = buildinfo.get()
    assert b.version and b.version != ""
    assert b.source in {"build", "source", "metadata"}
    assert b.version in b.short()


def test_short_includes_build_date_when_known():
    b = buildinfo.BuildInfo(version="1.2.3", build_date="2026-01-31", commit="abc1234")
    assert b.short() == "1.2.3 · built 2026-01-31 · abc1234"
    assert "+dirty" in buildinfo.BuildInfo("1.0", "2026-01-31", "abc1234", True).short()


def test_short_survives_missing_pieces():
    assert buildinfo.BuildInfo(version="1.0").short() == "1.0"


# --- version comparison --------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "newer"),
    [
        ("0.2.0", "0.1.0", True),
        ("0.10.0", "0.9.0", True),
        ("1.0.0", "1.0.0", False),
        ("v0.3.0", "0.2.9", True),
        ("0.2.0", "0.2.1", False),
    ],
)
def test_version_ordering(a, b, newer):
    assert (update._version_tuple(a) > update._version_tuple(b)) is newer


def test_version_tuple_tolerates_junk():
    # a tag like "2026.08-rc1" must not raise; ordering it is a bonus
    assert isinstance(update._version_tuple("2026.08-rc1"), tuple)


# --- staleness -----------------------------------------------------------------


CFG = {
    "server": "https://jira.example.com",
    "project": "ABC",
    "board": 1,
    "labels": ["backend"],
    "stages": ["Queued", "Shipped"],
    "parked": "Queued",
    "done": "Shipped",
    "track": ["Shipped"],
    "status_aliases": {},
    "lang": "en",
}


def test_fingerprint_tracks_only_skill_relevant_fields():
    a = update.config_fingerprint(CFG)
    assert update.config_fingerprint({**CFG, "board_name": "irrelevant"}) == a
    assert update.config_fingerprint({**CFG, "labels": ["backend", "ops"]}) != a


@pytest.fixture
def skills(tmp_path, monkeypatch):
    monkeypatch.setattr("jira_flow_report.config.load", lambda *_a, **_k: CFG)
    monkeypatch.setenv(update.DISABLE_ENV, "1")  # never touch the network in tests
    return tmp_path


def test_missing_skill_is_stale(skills):
    st = update.check(offline=True, skills_dir=str(skills))
    assert st.skill_stale and not st.skill_installed
    assert st.skill_reason == "not installed"


def test_unstamped_skill_is_stale(skills):
    d = skills / "jira-flow-report"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: x\n---\n")
    st = update.check(offline=True, skills_dir=str(skills))
    assert st.skill_stale and "version stamping" in st.skill_reason


def test_stamped_current_skill_is_not_stale(skills):
    d = skills / "jira-flow-report"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: x\n---\n")
    update.write_stamp(d, CFG)
    st = update.check(offline=True, skills_dir=str(skills))
    assert not st.skill_stale, st.skill_reason


def test_config_change_makes_the_skill_stale(skills):
    d = skills / "jira-flow-report"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: x\n---\n")
    update.write_stamp(d, CFG)
    stamp = json.loads((d / update.STAMP).read_text())
    stamp["config_fingerprint"] = "0" * 12
    (d / update.STAMP).write_text(json.dumps(stamp))
    st = update.check(offline=True, skills_dir=str(skills))
    assert st.skill_stale and "config changed" in st.skill_reason


def test_older_generator_version_makes_the_skill_stale(skills):
    d = skills / "jira-flow-report"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: x\n---\n")
    update.write_stamp(d, CFG)
    stamp = json.loads((d / update.STAMP).read_text())
    stamp["generated_by"] = "0.0.1"
    (d / update.STAMP).write_text(json.dumps(stamp))
    st = update.check(offline=True, skills_dir=str(skills))
    assert st.skill_stale and "0.0.1" in st.skill_reason


def test_corrupt_stamp_is_treated_as_stale(skills):
    d = skills / "jira-flow-report"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: x\n---\n")
    (d / update.STAMP).write_text("{not json")
    st = update.check(offline=True, skills_dir=str(skills))
    assert st.skill_stale


def test_offline_never_reports_a_cli_update(skills):
    st = update.check(offline=True, skills_dir=str(skills))
    assert st.cli_latest == "" and not st.cli_outdated


def test_install_writes_a_stamp(tmp_path, monkeypatch):
    from jira_flow_report import install

    monkeypatch.setattr("jira_flow_report.config.load", lambda *_a, **_k: CFG)
    dest = tmp_path / "jira-flow-report"
    install.render_skill(CFG, dest, target="code")
    stamp = update.read_stamp(dest)
    assert stamp and stamp["generated_by"] == buildinfo.get().version
    assert stamp["config_fingerprint"] == update.config_fingerprint(CFG)


# --- prompt fallbacks ----------------------------------------------------------


@pytest.fixture
def headless(monkeypatch):
    monkeypatch.setattr(ui, "interactive", lambda: False)


def test_text_returns_the_default_without_a_terminal(headless):
    assert prompts.text("Project key", "ABC") == "ABC"


def test_text_without_a_default_exits_rather_than_hanging(headless):
    with pytest.raises(SystemExit):
        prompts.text("Project key")


def test_select_returns_the_indexed_default(headless):
    opts = [("a", "Alpha"), ("b", "Beta")]
    assert prompts.select("Which?", opts) == "a"
    assert prompts.select("Which?", opts, default=1) == "b"


def test_select_with_one_option_needs_no_prompt(headless):
    assert prompts.select("Which?", [("only", "Only one")]) == "only"


def test_select_with_no_options_exits(headless):
    with pytest.raises(SystemExit):
        prompts.select("Which?", [])


def test_multiselect_returns_the_default_set(headless):
    got = prompts.multiselect("Labels", ["a", "b", "c"], ["b", "c"])
    assert got == ["b", "c"]


def test_confirm_returns_the_default(headless):
    assert prompts.confirm("ok?", True) is True
    assert prompts.confirm("ok?", False) is False


def test_assume_bypasses_the_terminal_check(monkeypatch):
    monkeypatch.setattr(ui, "interactive", lambda: True)
    assert prompts.text("Project key", "ABC", assume=True) == "ABC"


# --- the banner is chrome, not data -------------------------------------------


def test_banner_goes_to_stderr_never_stdout(capsys, monkeypatch):
    monkeypatch.delenv(ui.NO_BANNER_ENV, raising=False)
    ui.banner(force=True)
    captured = capsys.readouterr()
    assert "jira-flow-report" in captured.err
    assert captured.out == ""


def test_banner_suppressed_by_env(capsys, monkeypatch):
    monkeypatch.setenv(ui.NO_BANNER_ENV, "1")
    ui.banner(force=True)
    assert capsys.readouterr().err == ""


def test_update_notice_is_silent_when_current(capsys):
    ui.update_notice(update.Status(cli_current="1.0"))
    assert capsys.readouterr().err == ""


def test_update_notice_names_what_is_stale(capsys):
    ui.update_notice(
        update.Status(
            cli_current="1.0",
            cli_latest="2.0",
            cli_outdated=True,
            skill_stale=True,
            skill_reason="config changed",
        )
    )
    err = capsys.readouterr().err
    assert "2.0" in err and "config changed" in err and "update" in err
