"""Where the CLI's own version, build date and commit come from.

Three sources, in order of trust:
  1. `_build.py`, written by the build hook into a wheel or sdist
  2. installed distribution metadata, for the version at least
  3. the git checkout, when running from source
"""

from __future__ import annotations

import datetime as dt
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BuildInfo:
    version: str
    build_date: str = ""
    commit: str = ""
    dirty: bool = False
    source: str = "unknown"

    def short(self) -> str:
        bits = [self.version]
        if self.build_date:
            bits.append(f"built {self.build_date}")
        if self.commit:
            bits.append(self.commit + ("+dirty" if self.dirty else ""))
        elif self.source == "source":
            bits.append("from source")
        return " · ".join(bits)


def _git(root: Path, *args: str) -> str:
    """Best effort. Version reporting must never be the thing that crashes."""
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, check=True, timeout=5
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _pkg_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("jira-flow-report")
    except PackageNotFoundError:
        return "0+unknown"


def get() -> BuildInfo:
    try:
        from jira_flow_report import _build
    except ImportError:
        pass
    else:
        return BuildInfo(
            version=_build.VERSION,
            build_date=_build.BUILD_DATE,
            commit=_build.COMMIT,
            dirty=getattr(_build, "DIRTY", False),
            source="build",
        )

    # running from a checkout: ask git, so a dev build still shows something true
    root = Path(__file__).resolve().parents[2]
    if (root / ".git").exists():
        commit = _git(root, "rev-parse", "--short=7", "HEAD")
        iso = _git(root, "log", "-1", "--format=%cs")
        dirty = bool(_git(root, "status", "--porcelain"))
        if commit:
            return BuildInfo(
                version=_pkg_version(), build_date=iso, commit=commit, dirty=dirty, source="source"
            )

    mtime = ""
    try:
        ts = Path(__file__).stat().st_mtime
        mtime = dt.datetime.fromtimestamp(ts, tz=dt.UTC).strftime("%Y-%m-%d")
    except OSError:
        pass
    return BuildInfo(version=_pkg_version(), build_date=mtime, source="metadata")
