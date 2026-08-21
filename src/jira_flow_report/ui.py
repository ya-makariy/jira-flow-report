"""Terminal presentation. Everything here writes to **stderr**.

The banner and any notices are chrome, not data: `show-config` and the report
steps are routinely piped, and chrome on stdout would corrupt them.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache

from rich.console import Console
from rich.text import Text

from jira_flow_report import buildinfo

TAGLINE = "Kanban flow reports for any Jira board"
NO_BANNER_ENV = "JIRA_FLOW_REPORT_NO_BANNER"


@lru_cache(maxsize=1)
def err() -> Console:
    """Chrome goes here, so stdout stays clean for piping."""
    return Console(stderr=True, highlight=False, soft_wrap=True)


@lru_cache(maxsize=1)
def out() -> Console:
    return Console(highlight=False, soft_wrap=True)


def interactive() -> bool:
    """A human is watching and can answer."""
    return sys.stdin.isatty() and sys.stderr.isatty() and not os.environ.get("CI")


def banner(*, force: bool = False) -> None:
    if os.environ.get(NO_BANNER_ENV):
        return
    if not force and not sys.stderr.isatty():
        return
    info = buildinfo.get()
    c = err()
    name = Text("jira-flow-report", style="bold #2a78d6")
    name.append("  ")
    name.append(TAGLINE, style="default")
    c.print()
    c.print(name)
    c.print(Text(info.short(), style="dim"))
    c.print()


def rule(label: str) -> None:
    err().print(f"[dim]──[/dim] [bold]{label}[/bold]")


def ok(msg: str) -> None:
    err().print(f"[green]✓[/green] {msg}")


def info(msg: str) -> None:
    err().print(f"[dim]·[/dim] {msg}")


def warn(msg: str) -> None:
    err().print(f"[yellow]![/yellow] {msg}")


def fail(msg: str) -> None:
    err().print(f"[red]✗[/red] {msg}")


def update_notice(status) -> None:
    """Render whatever is stale. Quiet when everything is current."""
    lines = []
    if status.cli_outdated:
        lines.append(f"[bold]CLI[/bold] {status.cli_current} → [green]{status.cli_latest}[/green]")
    if status.skill_stale:
        lines.append(f"[bold]skill[/bold] {status.skill_reason}")
    if not lines:
        return
    c = err()
    c.print()
    for line in lines:
        c.print(f"  [yellow]↑[/yellow] {line}")
    c.print("  [dim]run[/dim] jira-flow-report update")
    c.print()
