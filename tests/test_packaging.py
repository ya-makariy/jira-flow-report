"""Metadata rules that only bite at publish time.

PyPI rejects an upload rather than warning, and a version can never be reused, so
these are cheaper to assert than to discover during a release.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO = Path(__file__).parent.parent
PYPROJECT = tomllib.loads((REPO / "pyproject.toml").read_text())


def test_license_expression_without_license_classifiers():
    """PyPI refuses an upload that carries both a PEP 639 expression and a
    `License ::` classifier."""
    project = PYPROJECT["project"]
    assert project["license"] == "MIT"
    offenders = [c for c in project["classifiers"] if c.startswith("License ::")]
    assert not offenders, f"remove these, the license expression supersedes them: {offenders}"


def test_license_file_is_declared_and_present():
    assert PYPROJECT["project"]["license-files"] == ["LICENSE"]
    assert (REPO / "LICENSE").is_file()


def test_classifiers_match_requires_python():
    """A classifier claiming a version the package refuses to install on is a lie
    told to anyone browsing PyPI."""
    project = PYPROJECT["project"]
    assert project["requires-python"] == ">=3.11"
    claimed = {
        c.rsplit(" :: ", 1)[1]
        for c in project["classifiers"]
        if c.startswith("Programming Language :: Python :: 3.")
    }
    assert claimed == {"3.11", "3.12", "3.13", "3.14"}


def test_typed_classifier_only_if_py_typed_ships():
    claims_typed = any(c.startswith("Typing :: Typed") for c in PYPROJECT["project"]["classifiers"])
    ships_marker = (REPO / "src" / "jira_flow_report" / "py.typed").exists()
    assert claims_typed == ships_marker, (
        "either ship a py.typed marker or drop the Typing :: Typed classifier"
    )


def test_entry_point_is_declared():
    assert PYPROJECT["project"]["scripts"] == {"jira-flow-report": "jira_flow_report.cli:main"}


def test_console_script_target_is_importable_and_callable():
    from jira_flow_report.cli import main

    assert callable(main)


def test_build_hook_is_registered_and_shipped():
    """The hook bakes the build stamp; if it is not in the sdist, a build from
    the sdist silently produces a wheel with no build info."""
    assert PYPROJECT["tool"]["hatch"]["build"]["hooks"]["custom"]["path"] == "hatch_build.py"
    assert "hatch_build.py" in PYPROJECT["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]


def test_release_workflow_guards_the_tag():
    wf = (REPO / ".github" / "workflows" / "release.yml").read_text()
    assert "does not match project version" in wf, "the tag/version guard is gone"
    assert "id-token: write" in wf, "trusted publishing needs an OIDC token"
    assert "uv run pytest" in wf, "never publish without running the suite"
