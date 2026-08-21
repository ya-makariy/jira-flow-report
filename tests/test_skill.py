"""The skill is generated, so what needs testing is the generation.

A broken SKILL.md fails silently: Claude simply does not load the skill, or loads
it and follows stale instructions. These checks are the substitute for noticing
that by hand.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pytest
import yaml

from jira_flow_report import install

REPO = Path(__file__).parent.parent
SRC = REPO / "src" / "jira_flow_report"

CFG = {
    "server": "https://jira.example.com",
    "project": "ABC",
    "board": 42,
    "board_name": "ABC kanban",
    "board_filter": "project = ABC ORDER BY Rank ASC",
    "labels": ["backend", "frontend", "ops"],
    "fetch_labels": ["backend", "frontend", "ops", "Ops"],
    "stages": ["Backlog", "Queued", "Doing", "Review", "Shipped"],
    "parked": "Queued",
    "done": "Shipped",
    "track": ["Doing", "Review", "Shipped"],
    "status_aliases": {"InProgress": "Doing", "Finished": "Shipped"},
    "lang": "en",
    "stage_meta": [
        {"id": "1", "name": "Backlog", "category": "new", "column": "Backlog"},
        {"id": "2", "name": "Queued", "category": "new", "column": "Queued"},
        {"id": "3", "name": "Doing", "category": "indeterminate", "column": "Doing"},
        {"id": "4", "name": "Review", "category": "indeterminate", "column": "Review"},
        {"id": "5", "name": "Shipped", "category": "done", "column": "Shipped"},
    ],
}


@pytest.fixture(params=["code", "desktop"])
def built(request, tmp_path):
    dest = tmp_path / "jira-flow-report"
    install.render_skill(CFG, dest, target=request.param)
    return request.param, dest


def frontmatter(skill_md: Path) -> dict:
    text = skill_md.read_text()
    assert text.startswith("---\n"), "SKILL.md must open with YAML frontmatter"
    _, fm, _ = text.split("---\n", 2)
    return yaml.safe_load(fm)


# --- the generation itself ------------------------------------------------------


def test_every_placeholder_is_substituted(built):
    """A leftover ${...} means a template variable was renamed and not wired up."""
    _, dest = built
    for f in sorted(dest.rglob("*.md")):
        leftovers = re.findall(r"\$\{[a-z_]+\}", f.read_text())
        assert not leftovers, f"{f.name} still has {leftovers}"


def test_config_values_actually_reach_the_docs(built):
    _, dest = built
    text = (dest / "SKILL.md").read_text()
    for expected in (CFG["server"], CFG["project"], str(CFG["board"]), CFG["parked"], CFG["done"]):
        assert expected in text, f"{expected!r} missing from the generated SKILL.md"
    quirks = (dest / "references" / "jira-quirks.md").read_text()
    for src, dst in CFG["status_aliases"].items():
        assert src in quirks and dst in quirks


def test_frontmatter_is_valid(built):
    _, dest = built
    fm = frontmatter(dest / "SKILL.md")
    assert fm["name"] == "jira-flow-report" == dest.name, "name must match the directory"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", fm["name"])
    assert len(fm["name"]) <= 64
    desc = fm["description"].strip()
    assert desc and len(desc) <= 1024
    # the description is what the model matches on; it must say when to use it
    assert "Use for" in desc or "Use when" in desc


def test_frontmatter_keys_are_target_appropriate(built):
    """Claude Code understands argument-hint and allowed-tools; the Desktop bundle
    is kept to the keys that are portable."""
    target, dest = built
    fm = frontmatter(dest / "SKILL.md")
    if target == "code":
        assert "argument-hint" in fm
        assert "allowed-tools" in fm
    else:
        assert set(fm) == {"name", "description"}, f"desktop frontmatter has {set(fm)}"


def test_targets_document_the_right_invocation(built):
    target, dest = built
    text = (dest / "SKILL.md").read_text()
    if target == "code":
        assert "jira-flow-report collect" in text
        assert "Artifact" in text
    else:
        # step 1 cannot run in a hosted sandbox; the copy must not tell it to try
        assert "Step 1 does not run in this environment" in text
        assert "jira-flow-report collect -o" not in text


# --- the scripts that ship with it ---------------------------------------------


def test_shipped_scripts_match_the_package(built):
    """The skill carries copies; a drifted copy is worse than none."""
    _, dest = built
    for name in ("aggregate.py", "render.py"):
        shipped = dest / "scripts" / name
        assert shipped.exists()
        assert shipped.read_bytes() == (SRC / name).read_bytes()


def test_collect_is_not_shipped_as_a_script(built):
    """collect needs the network and third-party deps, so the skill calls the CLI
    for it. A stale standalone copy used to sit here with a hardcoded server."""
    _, dest = built
    assert not (dest / "scripts" / "collect.py").exists()


# --- documentation drift -------------------------------------------------------


def test_documented_subcommands_exist(built):
    """Every `jira-flow-report <cmd>` in the docs must be a real subcommand."""
    from jira_flow_report import cli

    parser_cmds = set()
    p = cli.build_parser() if hasattr(cli, "build_parser") else None
    if p is None:
        # cli builds its parser inside main(); read the literal list instead
        parser_cmds = set(
            re.findall(r'sub\.add_parser\(\s*"([a-z-]+)"', (SRC / "cli.py").read_text())
        )
    _, dest = built
    text = "\n".join(f.read_text() for f in dest.rglob("*.md"))
    used = set(re.findall(r"jira-flow-report ([a-z][a-z-]+)", text))
    unknown = used - parser_cmds
    assert not unknown, f"docs reference non-existent subcommands: {unknown}"


def test_referenced_reference_files_exist(built):
    _, dest = built
    text = (dest / "SKILL.md").read_text()
    for ref in re.findall(r"`(references/[a-z-]+\.md)`", text):
        assert (dest / ref).exists(), f"SKILL.md points at missing {ref}"


# --- the desktop bundle --------------------------------------------------------


def test_desktop_zip_layout(tmp_path, monkeypatch):
    import argparse

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("jira_flow_report.config.load", lambda *_a, **_k: CFG)
    out = tmp_path / "bundle.zip"
    install.run(
        argparse.Namespace(
            skills_dir=str(tmp_path / "skills"),
            desktop_zip=str(out),
            desktop_zip_only=True,
            force=True,
        )
    )
    assert out.exists()
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    assert "jira-flow-report/SKILL.md" in names
    assert any(n.endswith("scripts/aggregate.py") for n in names)
    assert not [n for n in names if "__pycache__" in n or n.endswith(".pyc")]
    # nothing should be staged outside the single top-level directory
    assert {n.split("/")[0] for n in names} == {"jira-flow-report"}
    assert not (tmp_path / ".jfr-desktop-staging").exists(), "staging dir left behind"
