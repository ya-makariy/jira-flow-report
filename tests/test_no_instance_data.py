"""Guard the repository against instance-specific data.

This tool is generic; the values for one Jira live in a config file outside the
tree and in the *generated* skill, never in here. The checks are written
generically on purpose — an allowlist of forbidden company names would itself
publish the thing it is guarding.

The gate covers tracked files only. Real snapshots and reports are gitignored;
this catches the case where one is committed anyway, or where an example is
pasted in with live values still in it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent

# Hosts the project legitimately names.
ALLOWED_HOSTS = {
    "jira.example.com",
    "example.com",
    "www.example.com",
    "github.com",
    "api.github.com",
    "docs.pypi.org",
    "pypi.org",
    "test.pypi.org",
    "docs.astral.sh",
    "code.claude.com",
    "opensource.org",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
}
# Project keys used as examples in docs, templates and fixtures.
ALLOWED_KEYS = {"ABC"}
# Uppercase-hyphen-digit tokens that are not Jira keys.
NOT_TICKET_KEYS = {
    "UTF",
    "ISO",
    "RFC",
    "SHA",
    "AES",
    "RGB",
    "SVG",
    "CSS",
    "API",
    "MIT",
    "IBM",
    "XDG",
    "TOML",
    "JSON",
    "HTML",
    "CVD",
    "OKLCH",
    "OKLAB",
    "PEP",
}

HOST_RE = re.compile(r"https?://([A-Za-z0-9._-]+)")
PRIVATE_IP_RE = re.compile(
    r"\b(?:10(?:\.\d{1,3}){3}"
    r"|192\.168(?:\.\d{1,3}){2}"
    r"|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
    r"|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])(?:\.\d{1,3}){2})\b"
)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,9})-\d+\b")


# This module necessarily spells out patterns resembling what it hunts for: the
# ticket-key regex source contains a character class whose text is itself
# key-shaped, so the pattern matches its own definition. The gate skips itself.
SELF = Path(__file__).resolve()


def tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    keep = []
    for rel in out:
        p = REPO / rel
        if not p.is_file() or p.suffix in {".lock"} or p.resolve() == SELF:
            continue
        try:
            p.read_text()
        except UnicodeDecodeError:
            continue
        keep.append(p)
    return keep


@pytest.fixture(scope="module")
def files():
    fs = tracked_text_files()
    assert fs, "git ls-files returned nothing — is this a checkout?"
    return fs


def _report(hits):
    return "\n".join(f"  {p.relative_to(REPO)}: {v}" for p, v in hits)


def test_no_unexpected_hosts(files):
    hits = []
    for p in files:
        for host in set(HOST_RE.findall(p.read_text())):
            if host not in ALLOWED_HOSTS:
                hits.append((p, host))
    assert not hits, "hostname(s) that are not generic examples:\n" + _report(hits)


def test_no_private_ip_addresses(files):
    hits = [(p, m) for p in files for m in set(PRIVATE_IP_RE.findall(p.read_text()))]
    assert not hits, "private/CGNAT address(es) committed:\n" + _report(hits)


def test_no_real_email_addresses(files):
    hits = []
    for p in files:
        for dom in set(EMAIL_RE.findall(p.read_text())):
            if dom not in ALLOWED_HOSTS and not dom.endswith("users.noreply.github.com"):
                hits.append((p, dom))
    assert not hits, "email domain(s) that are not examples:\n" + _report(hits)


def test_no_real_ticket_keys(files):
    hits = []
    for p in files:
        for key in set(TICKET_RE.findall(p.read_text())):
            if key in ALLOWED_KEYS or key in NOT_TICKET_KEYS:
                continue
            hits.append((p, key))
    assert not hits, (
        "Jira-key-shaped token(s) from a real project:\n"
        + _report(hits)
        + "\nIf this is an example, add its prefix to ALLOWED_KEYS."
    )


def test_no_workflow_names_hardcoded_outside_examples():
    """Stage names, the parked column and the closed stage must come from config.
    A default baked into the code would silently be wrong on every other board."""
    for name in ("aggregate.py", "collect.py", "render.py"):
        src = (REPO / "src" / "jira_flow_report" / name).read_text()
        # argparse defaults for these must be None, i.e. 'fall back to the snapshot'
        for flag in ("--parked", "--done", "--stages", "--track", "--labels"):
            for m in re.finditer(rf'"{re.escape(flag)}"[^)]*?default=([^,)]+)', src, re.S):
                assert m.group(1).strip() in {"None", '""'}, (
                    f"{name}: {flag} has a hardcoded default {m.group(1).strip()}"
                )


def test_snapshots_and_reports_are_ignored():
    """These carry ticket summaries, usernames and links. Never committed."""
    ignored = subprocess.run(["git", "check-ignore", "-q", "snapshot.json"], cwd=REPO, check=False)
    assert ignored.returncode == 0, "snapshot.json is not gitignored"
    for pattern in ("report.json", "flow.html", "x-desktop.zip"):
        r = subprocess.run(["git", "check-ignore", "-q", pattern], cwd=REPO, check=False)
        assert r.returncode == 0, f"{pattern} is not gitignored"
