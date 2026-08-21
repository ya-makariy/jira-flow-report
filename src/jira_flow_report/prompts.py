"""Interactive prompts, with a non-interactive fallback.

Arrow keys to move, space to mark in a multi-select, Enter to submit. When there
is no terminal — CI, a pipe, an agent driving the CLI — every prompt resolves to
the default it was given instead of blocking forever, and says what it chose.
"""

from __future__ import annotations

import sys

import questionary
from prompt_toolkit.styles import Style

from jira_flow_report import ui

# Muted, so the answer is what stands out rather than the chrome.
STYLE = Style(
    [
        ("qmark", "fg:#2a78d6 bold"),
        ("question", "bold"),
        ("answer", "fg:#1baf7a bold"),
        ("pointer", "fg:#2a78d6 bold"),
        ("highlighted", "fg:#2a78d6 bold"),
        ("selected", "fg:#1baf7a"),
        ("instruction", "fg:#898781"),
        ("text", ""),
        ("disabled", "fg:#898781 italic"),
    ]
)


class Aborted(Exception):
    """The user pressed Ctrl-C / Esc at a prompt."""


def _auto(label: str, shown: str) -> None:
    """Say what was chosen for us, so a non-interactive run is still auditable."""
    ui.info(f"{label}: [bold]{shown}[/bold] [dim](no terminal, using default)[/dim]")


def _unwrap(answer, label: str):
    if answer is None:  # questionary returns None on Ctrl-C
        raise Aborted(label)
    return answer


def text(message: str, default: str | None = None, *, assume: bool = False) -> str:
    if assume or not ui.interactive():
        if default is None:
            sys.exit(f"Need a value for: {message} (no terminal to ask on; pass it as a flag)")
        _auto(message, default)
        return default
    # Deliberately NOT pre-filled: questionary's `default=` puts the text in the
    # buffer, so typing appends to it and "ABC" + "XYZ" becomes "ABCXYZ". Show the
    # default instead and accept an empty Enter as "keep it".
    hint = f"(Enter for {default})" if default else "(required)"

    def validate(value: str) -> bool | str:
        if value.strip() or default is not None:
            return True
        return "Cannot be empty"

    answer = _unwrap(
        questionary.text(message, style=STYLE, instruction=hint, validate=validate).ask(),
        message,
    )
    answer = answer.strip()
    return answer or (default or "")


def select(
    message: str, options: list[tuple[str, str]], default: int = 0, *, assume: bool = False
) -> str:
    """options: (value, label). Returns the chosen value."""
    if not options:
        sys.exit(f"Nothing to choose from for: {message}")
    if len(options) == 1:
        ui.info(f"{message} [bold]{options[0][1]}[/bold] [dim](only candidate)[/dim]")
        return options[0][0]
    if assume or not ui.interactive():
        _auto(message, options[default][1])
        return options[default][0]
    choices = [questionary.Choice(title=label, value=value) for value, label in options]
    return _unwrap(
        questionary.select(
            message,
            choices=choices,
            default=choices[default],
            style=STYLE,
            instruction="(↑↓ to move, Enter to choose)",
            use_shortcuts=False,
        ).ask(),
        message,
    )


def multiselect(
    message: str,
    options: list[str],
    default: list[str],
    *,
    assume: bool = False,
    hint: str | None = None,
) -> list[str]:
    if assume or not ui.interactive():
        _auto(message, ", ".join(default))
        return list(default)
    chosen = set(default)
    choices = [questionary.Choice(title=opt, value=opt, checked=opt in chosen) for opt in options]
    answer = _unwrap(
        questionary.checkbox(
            message,
            choices=choices,
            style=STYLE,
            instruction=hint or "(↑↓ to move, Space to mark, Enter to submit)",
            validate=lambda picked: bool(picked) or "Pick at least one",
        ).ask(),
        message,
    )
    # keep the order the caller offered, not the order they were ticked
    return [o for o in options if o in set(answer)]


def confirm(message: str, default: bool = True, *, assume: bool = False) -> bool:
    if assume or not ui.interactive():
        _auto(message, "yes" if default else "no")
        return default
    return bool(_unwrap(questionary.confirm(message, default=default, style=STYLE).ask(), message))
