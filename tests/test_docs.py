"""Keep the docs honest about the CI they describe.

REVIEWING.md names CI jobs and branch-protection contexts, and CONTRIBUTING.md
names the commands to run before a PR. Both are copies of facts that live in
ci.yml, so both rot silently when the workflow changes. These tests are the
tripwire.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).parent.parent
CI = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text())
RELEASE = (REPO / ".github" / "workflows" / "release.yml").read_text()
CONTRIBUTING = (REPO / "CONTRIBUTING.md").read_text()
REVIEWING = (REPO / "docs" / "REVIEWING.md").read_text()
RELEASING = (REPO / "docs" / "RELEASING.md").read_text()
README = (REPO / "README.md").read_text()
PR_TEMPLATE = (REPO / ".github" / "pull_request_template.md").read_text()


def ci_run_lines() -> str:
    return "\n".join(
        step["run"] for job in CI["jobs"].values() for step in job["steps"] if "run" in step
    )


# --- the docs describe the CI that exists -------------------------------------


def test_reviewing_lists_every_ci_job():
    """A job added to CI without a row here is a check nobody knows to require."""
    for job in CI["jobs"].values():
        name = job["name"]
        if "${{" in name:  # a matrix job: its rendered names are checked below
            continue
        assert name in REVIEWING, f"docs/REVIEWING.md does not mention CI job {name!r}"


def test_reviewing_lists_each_matrix_version_as_a_protection_context():
    """Branch protection needs the rendered names, one per matrix entry."""
    versions = CI["jobs"]["test"]["strategy"]["matrix"]["python"]
    for v in versions:
        assert f"test (py{v})" in REVIEWING, f"missing protection context for py{v}"
    stale = set(re.findall(r"test \(py(3\.\d+)\)", REVIEWING)) - set(versions)
    assert not stale, f"docs name Python versions CI no longer runs: {sorted(stale)}"


@pytest.mark.parametrize(
    "invocation",
    ["uv lock --check", "uv run ruff check", "uv run ruff format", "uv run pytest"],
)
def test_contributing_commands_are_the_ones_ci_runs(invocation):
    """Compared as invocations, not exact strings: CI adds --output-format=github
    for annotations, which is not something a contributor needs to type."""
    assert invocation in CONTRIBUTING, f"CONTRIBUTING.md omits {invocation!r}"
    assert invocation in ci_run_lines(), f"CI does not actually run {invocation!r}"


def test_releasing_matches_the_release_workflow():
    assert "release.yml" in RELEASING
    # the guard the runbook leans on has to be the one the workflow implements
    assert "does not match project version" in RELEASE
    assert "must match" in RELEASING


def test_supported_versions_agree_across_ci_and_metadata():
    project = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]
    claimed = {
        c.rsplit(" :: ", 1)[1]
        for c in project["classifiers"]
        if c.startswith("Programming Language :: Python :: 3.")
    }
    tested = set(CI["jobs"]["test"]["strategy"]["matrix"]["python"])
    assert claimed == tested, "classifiers and the CI matrix disagree"


# --- the docs point at things that exist --------------------------------------


@pytest.mark.parametrize("doc", ["README.md", "CONTRIBUTING.md"])
def test_relative_links_resolve(doc):
    text = (REPO / doc).read_text()
    for target in re.findall(r"\]\((?!https?:)([^)#]+)", text):
        assert (REPO / target).exists(), f"{doc} links to missing {target}"


def test_reviewing_links_resolve():
    for target in re.findall(r"\]\((?!https?:)([^)#]+)", REVIEWING):
        assert (REPO / "docs" / target).resolve().exists(), f"REVIEWING.md links to {target}"


def test_invariant_files_named_in_the_docs_exist():
    """The docs point contributors at specific files; those names must be real."""
    named = set()
    for text in (CONTRIBUTING, REVIEWING, PR_TEMPLATE):
        named |= set(re.findall(r"`(tests/[a-z_]+\.py|skill/[a-z*.]+|src/[\w/.]+\.py)`", text))
    for name in named:
        if "*" in name:
            assert list(REPO.glob(name)), f"no file matches {name}"
        else:
            assert (REPO / name).exists(), f"docs name a missing file: {name}"


# --- the invariants the docs promise are actually enforced ---------------------


def test_the_four_invariants_have_tests_behind_them():
    """CONTRIBUTING claims CI enforces all four. Check each has a real test."""
    suite = "\n".join(p.read_text() for p in (REPO / "tests").glob("test_*.py"))
    for marker in (
        "test_offline_modules_are_stdlib_only",  # 1: stdlib-only pair
        "test_no_unexpected_hosts",  # 2: no instance data
        "test_frontmatter_is_valid",  # 3: generated skill valid
        "test_changelog_alias_is_folded",  # 4: status names not hardcoded
    ):
        assert marker in suite, f"CONTRIBUTING promises an invariant with no test: {marker}"
