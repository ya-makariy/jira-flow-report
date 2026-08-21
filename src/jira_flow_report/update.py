"""Is this install current, and how do we make it current.

Two separate things go stale:
  * the **CLI** — a newer version exists upstream
  * the **skill** — it is generated, so it drifts when either the tool or the
    config moves on. A stale skill is the dangerous one: Claude keeps following
    instructions that no longer match the code.

The upstream check is deliberately timid: stderr-only, once a day, short
timeout, cached, never fatal, and off entirely with one env var. A tool that
phones home on every invocation is a tool people stop using.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from jira_flow_report import buildinfo, config

REPO = "ya-makariy/jira-flow-report"
GIT_URL = f"https://github.com/{REPO}"
DISABLE_ENV = "JIRA_FLOW_REPORT_NO_UPDATE_CHECK"
CHECK_INTERVAL = 24 * 3600
STAMP = ".generated.json"


# --- state ---------------------------------------------------------------------


def cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".cache"
    return root / "jira-flow-report" / "update-check.json"


def skill_dir(skills_dir: str = "~/.claude/skills") -> Path:
    return Path(skills_dir).expanduser() / "jira-flow-report"


def config_fingerprint(cfg: dict) -> str:
    """Only the fields that end up in the generated skill."""
    keys = (
        "server",
        "project",
        "board",
        "labels",
        "stages",
        "parked",
        "done",
        "track",
        "status_aliases",
        "lang",
    )
    blob = json.dumps({k: cfg.get(k) for k in keys}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def write_stamp(dest: Path, cfg: dict) -> None:
    info = buildinfo.get()
    (dest / STAMP).write_text(
        json.dumps(
            {
                "generated_by": info.version,
                "commit": info.commit,
                "config_fingerprint": config_fingerprint(cfg),
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            indent=1,
        )
        + "\n"
    )


def read_stamp(dest: Path) -> dict | None:
    try:
        return json.loads((dest / STAMP).read_text())
    except (OSError, json.JSONDecodeError):
        return None


# --- status --------------------------------------------------------------------


@dataclass
class Status:
    cli_current: str = ""
    cli_latest: str = ""
    cli_outdated: bool = False
    skill_installed: bool = False
    skill_stale: bool = False
    skill_reason: str = ""
    notes: list[str] = field(default_factory=list)


def _version_tuple(v: str) -> tuple:
    parts = []
    for chunk in v.lstrip("v").replace("-", ".").split("."):
        parts.append(int(chunk) if chunk.isdigit() else 0)
    return tuple(parts)


def latest_upstream(timeout: float = 4.0) -> str:
    """Latest release tag, or "" when there is none or the network says no."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "jira-flow-report"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return (json.load(resp).get("tag_name") or "").lstrip("v")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return ""


def _cached_latest(force: bool) -> tuple[str, bool]:
    """(version, came_from_network)"""
    p = cache_path()
    if not force:
        try:
            blob = json.loads(p.read_text())
            if time.time() - blob.get("at", 0) < CHECK_INTERVAL:
                return blob.get("latest", ""), False
        except (OSError, json.JSONDecodeError):
            pass
    latest = latest_upstream()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"at": time.time(), "latest": latest}))
    except OSError:
        pass
    return latest, True


def check(
    *, offline: bool = False, force: bool = False, skills_dir: str = "~/.claude/skills"
) -> Status:
    info = buildinfo.get()
    st = Status(cli_current=info.version)

    if not offline and not os.environ.get(DISABLE_ENV):
        latest, _ = _cached_latest(force)
        st.cli_latest = latest
        if latest and _version_tuple(latest) > _version_tuple(info.version):
            st.cli_outdated = True

    dest = skill_dir(skills_dir)
    st.skill_installed = (dest / "SKILL.md").exists()
    if not st.skill_installed:
        st.skill_stale = True
        st.skill_reason = "not installed"
        return st

    stamp = read_stamp(dest)
    if stamp is None:
        st.skill_stale = True
        st.skill_reason = "installed before version stamping — regenerate to track it"
        return st

    cfg = config.load(required=False)
    if stamp.get("generated_by") != info.version:
        st.skill_stale = True
        st.skill_reason = f"generated by {stamp.get('generated_by')}, CLI is {info.version}"
    elif cfg and stamp.get("config_fingerprint") != config_fingerprint(cfg):
        st.skill_stale = True
        st.skill_reason = "config changed since it was generated"
    return st


# --- doing something about it --------------------------------------------------


def _install_method() -> str:
    """How this CLI got here, so we update it the same way.

    A checkout takes priority: someone running from source wants their working
    tree installed, not whatever is on the default branch upstream.
    """
    root = Path(__file__).resolve().parents[2]
    if (root / ".git").exists() and (root / "pyproject.toml").exists():
        return "checkout"
    here = Path(__file__).resolve().as_posix()
    try:
        launched = Path(sys.argv[0]).resolve().as_posix()
    except OSError:
        launched = ""
    if "/uv/tools/" in here or "/uv/tools/" in launched:
        return "uv-tool"
    return "unknown"


def self_update(*, dry_run: bool = False) -> int:
    from jira_flow_report import ui

    if not shutil.which("uv"):
        ui.fail("uv is not on PATH; cannot self-update.")
        ui.info(f"Install manually: uv tool install --force git+{GIT_URL}")
        return 1

    method = _install_method()
    root = Path(__file__).resolve().parents[2]
    if method == "checkout":
        source = str(root)
        ui.info(f"updating from the local checkout at [bold]{source}[/bold]")
    else:
        source = f"git+{GIT_URL}"
        ui.info(f"updating from [bold]{GIT_URL}[/bold]")

    cmd = ["uv", "tool", "install", "--force", source]
    if dry_run:
        ui.info("dry run: " + " ".join(cmd))
        return 0
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        ui.fail("uv tool install failed; the previous version is still in place.")
        return proc.returncode
    ui.ok("CLI updated")
    return 0
