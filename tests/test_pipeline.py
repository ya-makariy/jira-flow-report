"""Offline tests: the whole aggregate+render path on a synthetic snapshot."""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from jira_flow_report import aggregate, render

SRC = Path(__file__).parent.parent / "src" / "jira_flow_report"

STAGES = ["Backlog", "Queued", "Doing", "Review", "Done!"]
BASE = {
    "schema": 1, "server": "https://jira.example.com", "project": "ABC", "board": 1,
    "jql": "project = ABC", "labels": ["backend", "frontend", "ops"],
    "stages": STAGES, "parked": "Queued", "done": "Done!",
    "track": ["Doing", "Review", "Done!"],
    # the changelog says 'InProgress'; the fields say 'Doing'
    "status_aliases": {"InProgress": "Doing", "Finished": "Done!"},
}


def issue(key, labels, status, history, assignee="u1", created="2026-01-01T00:00:00.000+0000"):
    return {"key": key, "summary": f"summary of {key}", "labels": labels, "status": status,
            "assignee": assignee, "created": created,
            "history": [{"at": at, "by": "u1", "from": f, "to": t} for at, f, t in history]}


def write_snap(tmp_path, issues, **over):
    snap = dict(BASE, issues=issues)
    snap.update(over)
    p = tmp_path / "snapshot.json"
    p.write_text(json.dumps(snap, ensure_ascii=False))
    return p


def run_agg(tmp_path, snap, *args):
    out = tmp_path / "report.json"
    rc = aggregate.main(["-i", str(snap), "-o", str(out), *args])
    assert rc == 0
    return json.loads(out.read_text())


# --- the constraint the sandbox depends on -------------------------------------

STDLIB_OK = {"argparse", "collections", "datetime", "json", "sys", "math", "html",
             "__future__", "typing", "os", "pathlib"}


@pytest.mark.parametrize("mod", ["aggregate.py", "render.py"])
def test_offline_modules_are_stdlib_only(mod):
    """These two must run in a sandbox with nothing installed. Enforced, not hoped."""
    tree = ast.parse((SRC / mod).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= STDLIB_OK, f"{mod} imports {imported - STDLIB_OK}"


@pytest.mark.parametrize("mod", ["aggregate.py", "render.py"])
def test_offline_modules_run_as_scripts(mod, tmp_path):
    """Copied out of the package, they must still work."""
    r = subprocess.run([sys.executable, str(SRC / mod), "--help"],
                       capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0, r.stderr


# --- selection rules -----------------------------------------------------------

def test_window_selects_on_transition(tmp_path):
    snap = write_snap(tmp_path, [
        issue("ABC-1", ["backend"], "Done!", [("2026-03-10T10:00:00.000+0000", "Queued", "Finished")]),
        issue("ABC-2", ["backend"], "Done!", [("2026-02-01T10:00:00.000+0000", "Queued", "Finished")]),
    ])
    rep = run_agg(tmp_path, snap, "--from", "2026-03-01", "--to", "2026-03-31")
    assert [r["key"] for r in rep["table"]] == ["ABC-1"]


def test_changelog_alias_is_folded(tmp_path):
    """'InProgress' in the changelog is the same status as 'Doing' in the fields."""
    snap = write_snap(tmp_path, [
        issue("ABC-1", ["backend"], "Doing", [("2026-03-10T10:00:00.000+0000", "Queued", "InProgress")]),
    ])
    rep = run_agg(tmp_path, snap, "--from", "2026-03-01", "--to", "2026-03-31")
    assert rep["all"]["total"] == 1
    assert rep["cats"]["backend"]["counts"][STAGES.index("Doing")] == 1


def test_unfolded_alias_would_lose_the_issue(tmp_path):
    """Guard on the trap itself: with no alias map the transition is not tracked."""
    snap = write_snap(tmp_path, [
        issue("ABC-1", ["backend"], "Doing", [("2026-03-10T10:00:00.000+0000", "Queued", "InProgress")]),
    ], status_aliases={})
    rep = run_agg(tmp_path, snap, "--from", "2026-03-01", "--to", "2026-03-31")
    assert rep["all"]["total"] == 0


def test_parked_cutoff_excludes_recent_grooming(tmp_path):
    issues = [
        issue("ABC-1", ["backend"], "Queued", [("2026-01-05T10:00:00.000+0000", "Backlog", "Queued")]),
        issue("ABC-2", ["backend"], "Queued", [("2026-03-28T10:00:00.000+0000", "Backlog", "Queued")]),
    ]
    snap = write_snap(tmp_path, issues)
    rep = run_agg(tmp_path, snap, "--from", "2026-03-01", "--to", "2026-03-31",
                  "--parked-cutoff", "2026-03-27")
    assert [r["key"] for r in rep["parked_list"]] == ["ABC-1"]

    rep = run_agg(tmp_path, snap, "--from", "2026-03-01", "--to", "2026-03-31",
                  "--parked-cutoff", "none")
    assert sorted(r["key"] for r in rep["parked_list"]) == ["ABC-1", "ABC-2"]


def test_parked_cutoff_default_is_to_minus_four_days(tmp_path):
    snap = write_snap(tmp_path, [
        issue("ABC-1", ["backend"], "Queued", [("2026-03-29T10:00:00.000+0000", "Backlog", "Queued")]),
    ])
    rep = run_agg(tmp_path, snap, "--from", "2026-03-01", "--to", "2026-03-31")
    assert "2026-03-27" in rep["meta"]["parked_cutoff"]
    assert rep["parked_list"] == []


def test_no_history_falls_back_to_created(tmp_path):
    snap = write_snap(tmp_path, [
        issue("ABC-1", ["backend"], "Queued", [], created="2026-01-09T00:00:00.000+0000"),
    ])
    rep = run_agg(tmp_path, snap, "--from", "2026-03-01", "--to", "2026-03-31")
    assert rep["parked_list"][0]["since"] == "2026-01-09"


def test_restrict_is_per_label(tmp_path):
    """An issue dropped from one label's chart stays in the others'."""
    snap = write_snap(tmp_path, [
        issue("ABC-1", ["backend", "ops"], "Done!",
              [("2026-03-10T10:00:00.000+0000", "Queued", "Finished")], assignee="other"),
    ])
    rep = run_agg(tmp_path, snap, "--from", "2026-03-01", "--to", "2026-03-31",
                  "--restrict", "ops=keeper,unassigned")
    assert rep["cats"]["ops"]["total"] == 0
    assert rep["cats"]["backend"]["total"] == 1
    assert rep["excluded"][0]["kept_in"] == ["backend"]


def test_restrict_accepts_unassigned(tmp_path):
    snap = write_snap(tmp_path, [
        issue("ABC-1", ["ops"], "Done!", [("2026-03-10T10:00:00.000+0000", "Queued", "Finished")],
              assignee=None),
    ])
    rep = run_agg(tmp_path, snap, "--from", "2026-03-01", "--to", "2026-03-31",
                  "--restrict", "ops=unassigned")
    assert rep["cats"]["ops"]["total"] == 1


def test_labels_fold_case_by_default(tmp_path):
    snap = write_snap(tmp_path, [
        issue("ABC-1", ["Backend"], "Done!", [("2026-03-10T10:00:00.000+0000", "Queued", "Finished")]),
    ])
    rep = run_agg(tmp_path, snap, "--from", "2026-03-01", "--to", "2026-03-31")
    assert rep["cats"]["backend"]["total"] == 1
    rep = run_agg(tmp_path, snap, "--from", "2026-03-01", "--to", "2026-03-31", "--no-fold-case")
    assert rep["cats"]["backend"]["total"] == 0


def test_status_outside_the_scale_is_prepended_not_dropped(tmp_path):
    """Selected in the window, then moved somewhere off the configured scale."""
    snap = write_snap(tmp_path, [
        issue("ABC-1", ["backend"], "Cancelled",
              [("2026-03-10T10:00:00.000+0000", "Queued", "InProgress"),
               ("2026-03-12T10:00:00.000+0000", "InProgress", "Cancelled")]),
    ])
    rep = run_agg(tmp_path, snap, "--from", "2026-03-01", "--to", "2026-03-31")
    assert rep["meta"]["extra_stages"] == ["Cancelled"]
    assert rep["meta"]["stages"][0] == "Cancelled"
    assert sum(rep["cats"]["backend"]["counts"]) == rep["cats"]["backend"]["total"] == 1


def test_multi_label_issue_counted_in_each(tmp_path):
    snap = write_snap(tmp_path, [
        issue("ABC-1", ["backend", "frontend"], "Done!",
              [("2026-03-10T10:00:00.000+0000", "Queued", "Finished")]),
    ])
    rep = run_agg(tmp_path, snap, "--from", "2026-03-01", "--to", "2026-03-31")
    assert rep["all"]["total"] == 1
    assert rep["cats"]["backend"]["total"] == rep["cats"]["frontend"]["total"] == 1


def test_counts_always_sum_to_total(tmp_path):
    snap = write_snap(tmp_path, [
        issue("ABC-1", ["backend"], "Done!", [("2026-03-02T10:00:00.000+0000", "Queued", "Finished")]),
        issue("ABC-2", ["backend"], "Review", [("2026-03-03T10:00:00.000+0000", "Doing", "Review")]),
        issue("ABC-3", ["frontend"], "Queued", [("2026-01-01T10:00:00.000+0000", "Backlog", "Queued")]),
    ])
    rep = run_agg(tmp_path, snap, "--from", "2026-03-01", "--to", "2026-03-31")
    for cat, c in rep["cats"].items():
        assert sum(c["counts"]) == c["total"], cat
    assert sum(rep["all"]["counts"]) == rep["all"]["total"]


# --- argument handling ---------------------------------------------------------

@pytest.mark.parametrize("s,expect", [
    ("2026-03-10", "2026-03-10"), ("10.03.2026", "2026-03-10"),
    ("10/03/2026", "2026-03-10"), ("2026/03/10", "2026-03-10"),
])
def test_date_formats(s, expect):
    assert str(aggregate.parse_date(s, "from")) == expect


def test_bad_date_exits():
    with pytest.raises(SystemExit):
        aggregate.parse_date("March 10th", "from")


def test_reversed_window_exits(tmp_path):
    snap = write_snap(tmp_path, [])
    with pytest.raises(SystemExit):
        aggregate.main(["-i", str(snap), "-o", str(tmp_path / "r.json"),
                        "--from", "2026-03-31", "--to", "2026-03-01"])


def test_done_must_be_a_stage(tmp_path):
    snap = write_snap(tmp_path, [])
    with pytest.raises(SystemExit):
        aggregate.main(["-i", str(snap), "-o", str(tmp_path / "r.json"),
                        "--from", "2026-03-01", "--to", "2026-03-31", "--done", "Nope"])


def test_malformed_restrict_exits(tmp_path):
    snap = write_snap(tmp_path, [])
    with pytest.raises(SystemExit):
        aggregate.main(["-i", str(snap), "-o", str(tmp_path / "r.json"),
                        "--from", "2026-03-01", "--to", "2026-03-31", "--restrict", "oops"])


def test_missing_snapshot_exits(tmp_path):
    with pytest.raises(SystemExit):
        aggregate.main(["-i", str(tmp_path / "nope.json"), "-o", str(tmp_path / "r.json"),
                        "--from", "2026-03-01", "--to", "2026-03-31"])


# --- render -------------------------------------------------------------------

@pytest.fixture
def rendered(tmp_path):
    snap = write_snap(tmp_path, [
        issue("ABC-1", ["backend"], "Done!", [("2026-03-02T10:00:00.000+0000", "Queued", "Finished")]),
        issue("ABC-2", ["backend"], "Review", [("2026-03-03T10:00:00.000+0000", "Doing", "Review")]),
        issue("ABC-3", ["frontend"], "Queued", [("2026-01-01T10:00:00.000+0000", "Backlog", "Queued")]),
        issue("ABC-4", ["ops"], "Done!", [("2026-03-04T10:00:00.000+0000", "Queued", "Finished")]),
    ])
    rep_path = tmp_path / "report.json"
    aggregate.main(["-i", str(snap), "-o", str(rep_path), "--from", "2026-03-01",
                    "--to", "2026-03-31"])
    def go(*args):
        out = tmp_path / "flow.html"
        assert render.main(["-i", str(rep_path), "-o", str(out), *args]) == 0
        return out.read_text()
    return go


@pytest.mark.parametrize("lang", ["en", "ru"])
def test_render_produces_a_themed_page(rendered, lang):
    h = rendered("--lang", lang)
    assert h.startswith("<title>")
    # all three theme states must be covered
    assert "prefers-color-scheme:dark" in h
    assert ':root[data-theme="dark"]' in h
    assert 'body{margin:0;background:var(--plane)' in h
    # links point at the configured server
    assert "https://jira.example.com/browse/ABC-1" in h


def test_render_escapes_summaries(tmp_path):
    snap = write_snap(tmp_path, [
        {"key": "ABC-9", "summary": '<script>alert("x")</script>', "labels": ["backend"],
         "status": "Done!", "assignee": "u1", "created": "2026-01-01T00:00:00.000+0000",
         "history": [{"at": "2026-03-02T10:00:00.000+0000", "by": "u1",
                      "from": "Queued", "to": "Finished"}]},
    ])
    rep = tmp_path / "r.json"
    aggregate.main(["-i", str(snap), "-o", str(rep), "--from", "2026-03-01", "--to", "2026-03-31"])
    out = tmp_path / "f.html"
    render.main(["-i", str(rep), "-o", str(out)])
    h = out.read_text()
    assert "<script>alert" not in h
    assert "&lt;script&gt;" in h


def test_render_custom_title(rendered):
    assert "<title>My Board</title>" in rendered("--title", "My Board")


def test_render_empty_report_exits(tmp_path):
    snap = write_snap(tmp_path, [])
    rep = tmp_path / "r.json"
    aggregate.main(["-i", str(snap), "-o", str(rep), "--from", "2026-03-01", "--to", "2026-03-31"])
    with pytest.raises(SystemExit):
        render.main(["-i", str(rep), "-o", str(tmp_path / "f.html")])


def test_ramp_lengths_match_stage_count():
    for n in range(2, 9):
        light, dark = render.ramp(n)
        assert len(light) == len(dark) == n
        assert len(set(light)) == n, f"duplicate light steps at n={n}"


def test_case_variant_labels_do_not_split_a_category(tmp_path):
    """Regression: a snapshot listing both 'ops' and 'Ops' as categories must not
    produce two charts, one of them empty — and a --restrict on one spelling must
    not miss issues tagged with the other."""
    snap = write_snap(tmp_path, [
        issue("ABC-1", ["Ops"], "Done!", [("2026-03-02T10:00:00.000+0000", "Queued", "Finished")],
              assignee="other"),
        issue("ABC-2", ["ops"], "Done!", [("2026-03-03T10:00:00.000+0000", "Queued", "Finished")],
              assignee="keeper"),
    ], labels=["backend", "ops", "Ops"])
    rep = run_agg(tmp_path, snap, "--from", "2026-03-01", "--to", "2026-03-31",
                  "--restrict", "ops=keeper")
    assert rep["meta"]["cats"] == ["backend", "ops"]
    assert rep["cats"]["ops"]["total"] == 1
    assert [x["key"] for x in rep["excluded"]] == ["ABC-1"]


def test_collect_keeps_fetch_labels_and_categories_apart():
    """The JQL needs every spelling; the charts need one entry per category."""
    from jira_flow_report import collect
    assert "labels in (Ops, ops)" in collect.build_jql("ABC", ["ops", "Ops"], None)
