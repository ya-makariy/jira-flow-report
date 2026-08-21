"""Bake version, build date and commit into the package at build time.

Without this the CLI can report a version but not when the thing was built, and
"is my install stale?" becomes guesswork.
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

TARGET = Path("src/jira_flow_report/_build.py")


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True, timeout=10
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _built_at() -> dt.datetime:
    """Honour SOURCE_DATE_EPOCH so reproducible builds stay reproducible."""
    stamp = os.environ.get("SOURCE_DATE_EPOCH", "")
    if stamp.isdigit():
        return dt.datetime.fromtimestamp(int(stamp), tz=dt.UTC)
    return dt.datetime.now(tz=dt.UTC)


def _previous(target: Path, field: str) -> str:
    """Read a field out of an existing _build.py.

    `uv build` builds the wheel from a freshly unpacked sdist, where there is no
    .git to ask. The sdist stage did have one, so carry its answer forward rather
    than overwrite it with a blank.
    """
    try:
        for line in target.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{field} = "):
                return line.split(" = ", 1)[1].strip().strip("'\"")
    except OSError:
        return ""
    return ""


def _commit(target: Path) -> str:
    return (
        _git("rev-parse", "--short=7", "HEAD")
        or os.environ.get("JIRA_FLOW_REPORT_COMMIT", "")[:7]
        or os.environ.get("GITHUB_SHA", "")[:7]
        or _previous(target, "COMMIT")
    )


class BuildInfoHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version, build_data):
        built = _built_at()
        target = Path(self.root) / TARGET
        in_git = bool(_git("rev-parse", "HEAD"))
        target.write_text(
            '"""Generated at build time. Do not edit; do not commit."""\n\n'
            f"VERSION = {self.metadata.version!r}\n"
            f"BUILD_DATE = {built.strftime('%Y-%m-%d')!r}\n"
            f"BUILD_TIME = {built.strftime('%Y-%m-%dT%H:%M:%SZ')!r}\n"
            f"COMMIT = {_commit(target)!r}\n"
            f"DIRTY = {bool(_git('status', '--porcelain')) if in_git else False!r}\n",
            encoding="utf-8",
        )
        build_data.setdefault("artifacts", []).append(f"/{TARGET.as_posix()}")
