"""Step 1: Jira -> snapshot.json (issues + full status changelog).

The snapshot carries the stage scale and the status alias map alongside the
issues, so the offline steps need no config and no network — which is what lets
them run in a sandbox that cannot reach the Jira host.
"""

from __future__ import annotations

import json
import sys

from jira_flow_report import config


def build_jql(project: str, labels: list[str] | None, extra: str | None) -> str:
    if extra:
        return extra
    if not project:
        sys.exit("No project key. Pass --project or set it with: jira-flow-report init")
    q = f"project = {project}"
    if labels:
        # JQL labels are case-sensitive, so every spelling variant is listed.
        q += " AND labels in (" + ", ".join(sorted(set(labels))) + ")"
    return q + " ORDER BY key ASC"


def run(args) -> int:
    cfg = config.load(required=False)
    server = args.server or cfg.get("server")
    project = args.project or cfg.get("project")
    # Two different lists, and conflating them silently splits a category in two:
    #   fetch_labels -- every spelling variant to put in the JQL (case-sensitive)
    #   labels       -- the chart categories, one per real category
    fetch_labels = (
        [lab.strip() for lab in args.labels.split(",") if lab.strip()]
        if args.labels
        else cfg.get("fetch_labels") or cfg.get("labels")
    )
    cats = (
        [lab.strip() for lab in args.categories.split(",") if lab.strip()]
        if args.categories
        else cfg.get("labels")
    )
    if not cats and fetch_labels:
        # fold spelling variants down to one category each, keeping first-seen spelling
        seen, cats = {}, []
        for lab in fetch_labels:
            if lab.lower() not in seen:
                seen[lab.lower()] = lab
                cats.append(lab)
    if not server:
        sys.exit("No Jira server. Pass --server or run: jira-flow-report init")

    client = config.client(server)
    jql = build_jql(project, fetch_labels, args.jql)
    print(f"jql: {jql}", file=sys.stderr)

    issues, start = [], 0
    while True:
        batch = client.search_issues(
            jql,
            startAt=start,
            maxResults=50,
            expand="changelog",
            fields="labels,status,assignee,summary,created",
        )
        if not batch:
            break
        issues += batch
        start += len(batch)
        print(f"  fetched {start}", file=sys.stderr)
        if len(batch) < 50:
            break

    aliases = cfg.get("status_aliases") or {}
    if args.rediscover_aliases or not aliases:
        from jira_flow_report import discover

        aliases, unmapped = discover.discover_status_aliases(
            client, project, stages=cfg.get("stages")
        )
        if unmapped:
            print(
                f"  note: no field-name mapping observed for {unmapped} — "
                f"they will be reported under their changelog spelling",
                file=sys.stderr,
            )

    out = {
        "schema": 1,
        "server": server,
        "project": project,
        "board": args.board or cfg.get("board"),
        "jql": jql,
        "labels": cats or [],
        "fetch_labels": fetch_labels or [],
        "stages": cfg.get("stages") or [],
        "parked": cfg.get("parked"),
        "track": cfg.get("track") or [],
        "done": cfg.get("done"),
        "status_aliases": aliases,
        "issues": [],
    }
    for i in issues:
        out["issues"].append(
            {
                "key": i.key,
                "summary": i.fields.summary,
                "labels": list(i.fields.labels),
                "status": i.fields.status.name,
                "assignee": i.fields.assignee.name if i.fields.assignee else None,
                "created": i.fields.created,
                "history": sorted(
                    [
                        {
                            "at": h.created,
                            "by": h.author.name,
                            "from": it.fromString,
                            "to": it.toString,
                        }
                        for h in i.changelog.histories
                        for it in h.items
                        if it.field == "status"
                    ],
                    key=lambda x: x["at"],
                ),
            }
        )

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"{len(out['issues'])} issues -> {args.out}", file=sys.stderr)
    return 0
