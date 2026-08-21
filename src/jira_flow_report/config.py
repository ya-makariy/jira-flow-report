"""Config file handling. Nothing about any particular Jira lives in the code."""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

CONFIG_ENV = "JIRA_FLOW_REPORT_CONFIG"
TOKEN_ENV = "JIRA_API_TOKEN"
TIMEOUT_ENV = "JIRA_FLOW_REPORT_TIMEOUT"
# Generous on purpose: a changelog-expanded page of 50 issues has been
# measured at 12s on a healthy server. This exists to end a stalled
# connection, not to police a slow query.
DEFAULT_TIMEOUT = 60.0
SERVER_ENV = "JIRA_SERVER"


def config_path() -> Path:
    """XDG-ish location, overridable for tests and for multiple instances."""
    if os.environ.get(CONFIG_ENV):
        return Path(os.environ[CONFIG_ENV]).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "jira-flow-report" / "config.toml"


def load(required: bool = True) -> dict:
    p = config_path()
    if not p.exists():
        if required:
            sys.exit(f"No config at {p}\nRun:  jira-flow-report init")
        return {}
    with p.open("rb") as fh:
        return tomllib.load(fh)


def save(cfg: dict) -> Path:
    import tomli_w

    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("wb") as fh:
        tomli_w.dump(cfg, fh)
    p.chmod(0o600)
    return p


def token() -> str:
    """The API token is read from the environment only — never stored in config."""
    tok = os.environ.get(TOKEN_ENV)
    if not tok:
        sys.exit(
            f"{TOKEN_ENV} is not set.\n"
            "Export it in your shell profile, e.g.\n"
            f"  export {TOKEN_ENV}='<your token>'\n"
            "It is deliberately not written to the config file."
        )
    return tok


def client(server: str | None = None):
    """A Jira client. Imported lazily so the offline commands need no deps."""
    try:
        from jira import JIRA
    except ImportError:
        sys.exit(
            "The 'jira' package is not available in this interpreter.\n"
            "Install the tool with uv:  uv tool install jira-flow-report"
        )
    if server is None:
        server = os.environ.get(SERVER_ENV) or load().get("server")
    if not server:
        sys.exit("No Jira server known. Run: jira-flow-report init")
    # Without a timeout the library waits forever, and with max_retries=3 it does
    # so up to four times without saying anything -- which is indistinguishable
    # from the process being wedged.
    return JIRA(server=server, token_auth=token(), timeout=timeout())


def timeout() -> float:
    """Per-request HTTP timeout in seconds. 0 or negative disables it."""
    raw = os.environ.get(TIMEOUT_ENV)
    if raw is None:
        raw = str(load(required=False).get("timeout", DEFAULT_TIMEOUT))
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT
    return value if value > 0 else None
