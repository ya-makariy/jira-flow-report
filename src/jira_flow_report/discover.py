"""Interactive setup: ask for the few things only a human knows, read the rest
off the Jira REST API. Nothing about any particular instance is hardcoded."""
from __future__ import annotations

import collections
import sys

from jira_flow_report import config

AGILE = "{server}/rest/agile/1.0/{{path}}"


def _tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def ask(prompt: str, default: str | None = None, *, assume: bool = False) -> str:
    if assume or not _tty():
        if default is None:
            sys.exit(f"Need a value for: {prompt} (no terminal to ask on; pass it as a flag)")
        return default
    suffix = f" [{default}]" if default else ""
    while True:
        got = input(f"{prompt}{suffix}: ").strip()
        if got:
            return got
        if default is not None:
            return default


def pick(prompt: str, options: list[tuple[str, str]], default: int = 0,
         *, assume: bool = False) -> str:
    """options: (value, label). Returns the chosen value."""
    if not options:
        sys.exit(f"Nothing to choose from for: {prompt}")
    if len(options) == 1:
        print(f"  {prompt}: {options[0][1]}  (only candidate)")
        return options[0][0]
    if assume or not _tty():
        print(f"  {prompt}: {options[default][1]}  (default)")
        return options[default][0]
    print(f"\n{prompt}")
    for i, (_, label) in enumerate(options, 1):
        print(f"  {i:2d}) {label}")
    while True:
        got = input(f"choose 1-{len(options)} [{default + 1}]: ").strip()
        if not got:
            return options[default][0]
        if got.isdigit() and 1 <= int(got) <= len(options):
            return options[int(got) - 1][0]


def multipick(prompt: str, options: list[str], default: list[str],
              *, assume: bool = False) -> list[str]:
    if assume or not _tty():
        print(f"  {prompt}: {', '.join(default)}  (default)")
        return default
    print(f"\n{prompt}")
    for i, o in enumerate(options, 1):
        mark = "*" if o in default else " "
        print(f"  {mark}{i:2d}) {o}")
    got = input("numbers, comma-separated, or blank to keep the starred set: ").strip()
    if not got:
        return default
    out = []
    for part in got.split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= len(options):
            out.append(options[int(part) - 1])
    return out or default


def _agile(client, server, path):
    return client._get_json(path, base=AGILE.format(server=server))


def discover_board(client, server, board_id=None, *, assume=False) -> dict:
    """Return {'id', 'name', 'filter_id'} for the board to report on."""
    if board_id:
        b = _agile(client, server, f"board/{board_id}")
        chosen = str(b["id"])
        name = b["name"]
    else:
        boards, start = [], 0
        while True:
            page = _agile(client, server, f"board?startAt={start}&maxResults=50")
            boards += page.get("values", [])
            if page.get("isLast", True):
                break
            start += len(page.get("values", []))
        if not boards:
            sys.exit("No boards visible to this token.")
        kanban = [b for b in boards if b.get("type") == "kanban"] or boards
        opts = [(str(b["id"]), f"{b['name']}  (id {b['id']}, {b.get('type', '?')})")
                for b in sorted(kanban, key=lambda b: b["name"].lower())]
        chosen = pick("Which board?", opts, assume=assume)
        name = next(b["name"] for b in kanban if str(b["id"]) == chosen)
    cfgj = _agile(client, server, f"board/{chosen}/configuration")
    return {"id": int(chosen), "name": name,
            "filter_id": cfgj.get("filter", {}).get("id"), "_config": cfgj}


def discover_stages(client, board_config: dict) -> list[dict]:
    """The board's columns ARE the stage scale, in board order."""
    stages = []
    for col in board_config.get("columnConfig", {}).get("columns", []):
        for st in col.get("statuses", []):
            sid = st["self"].rstrip("/").rsplit("/", 1)[-1]
            s = client._get_json(f"status/{sid}")
            stages.append({"id": sid, "name": s["name"],
                           "category": s["statusCategory"]["key"], "column": col["name"]})
    return stages


def discover_project(client, server, board_id: int) -> str | None:
    """The project key, taken from an issue actually on the board."""
    try:
        page = _agile(client, server, f"board/{board_id}/issue?maxResults=1&fields=key")
        issues = page.get("issues", [])
        if issues:
            return issues[0]["key"].rsplit("-", 1)[0]
    except Exception:
        pass
    return None


def discover_labels(client, project: str, limit: int = 1500) -> collections.Counter:
    cnt: collections.Counter = collections.Counter()
    start = 0
    while start < limit:
        batch = client.search_issues(f"project = {project}", startAt=start,
                                     maxResults=100, fields="labels")
        if not batch:
            break
        for i in batch:
            cnt.update(i.fields.labels)
        start += len(batch)
        if len(batch) < 100:
            break
    return cnt


def discover_status_aliases(client, project: str, sample: int = 300) -> tuple[dict, list]:
    """Recover the changelog spelling -> field spelling map, empirically.

    Jira can render statuses localised in the REST fields while the changelog
    keeps English names. An issue's LAST status transition and its CURRENT status
    are by definition the same status, so pairing them yields the map with no
    hardcoded table. Returns (aliases, unmapped_changelog_names).
    """
    pairs: collections.Counter = collections.Counter()
    seen_changelog: set[str] = set()
    start = 0
    while start < sample:
        batch = client.search_issues(f"project = {project} ORDER BY updated DESC",
                                     startAt=start, maxResults=50,
                                     expand="changelog", fields="status")
        if not batch:
            break
        for i in batch:
            hist = sorted(
                ((h.created, it.fromString, it.toString)
                 for h in i.changelog.histories for it in h.items if it.field == "status"),
                key=lambda x: x[0])
            for _, f, t in hist:
                seen_changelog.update(x for x in (f, t) if x)
            if hist:
                pairs[(hist[-1][2], i.fields.status.name)] += 1
        start += len(batch)
        if len(batch) < 50:
            break

    by_source: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for (src, dst), n in pairs.items():
        by_source[src][dst] += n
    aliases, ambiguous = {}, []
    for src, dsts in by_source.items():
        best, _ = dsts.most_common(1)[0]
        if len(dsts) > 1:
            ambiguous.append((src, dict(dsts)))
        if best != src:
            aliases[src] = best
    for src, dsts in ambiguous:
        print(f"  warning: changelog status {src!r} mapped to several field names "
              f"{dsts} — picked the most common", file=sys.stderr)
    unmapped = sorted(seen_changelog - set(by_source))
    return aliases, unmapped


def suggest_roles(stages: list[dict]) -> dict:
    """Guess which stage is 'parked', which is 'done', which count as movement."""
    names = [s["name"] for s in stages]
    new = [s["name"] for s in stages if s["category"] == "new"]
    done = [s["name"] for s in stages if s["category"] == "done"]
    mid = [s["name"] for s in stages if s["category"] == "indeterminate"]
    return {
        # the last not-started column: work that has been queued and then sat there
        "parked": new[-1] if new else names[0],
        "done": done[-1] if done else names[-1],
        "track": mid + ([done[-1]] if done else []),
    }
