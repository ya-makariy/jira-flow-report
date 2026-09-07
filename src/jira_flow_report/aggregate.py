#!/usr/bin/env python3
"""Step 2: snapshot.json + a date window -> report.json.

Standalone by design: stdlib only, no imports from this package, no network.
That is what lets it run in a sandbox with no access to the Jira host.

Selection — the two rules are OR'd:
  1. the issue transitioned INTO one of --track inside [--from, --to]
  2. the issue is STILL in --parked and entered it before --parked-cutoff
Per-label restrictions from --restrict are then applied per label, so an issue
dropped from one label's chart stays in the others'.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys


def pdate(s: str) -> dt.date:
    """Date part only. Timezone is deliberately ignored: a transition is attributed
    to the date its own timestamp carries, which is the date a reader of the board
    would have seen it on."""
    return dt.datetime.strptime(s[:10], "%Y-%m-%d").date()  # noqa: DTZ007


def parse_date(s: str, name: str) -> dt.date:
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()  # noqa: DTZ007
        except ValueError:
            pass
    sys.exit(f"--{name}: cannot parse {s!r}. Use YYYY-MM-DD or DD.MM.YYYY.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aggregate", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("-i", "--snapshot", default="snapshot.json")
    p.add_argument("-o", "--out", default="report.json")
    p.add_argument(
        "--from", dest="dfrom", required=True, help="window start (YYYY-MM-DD or DD.MM.YYYY)"
    )
    p.add_argument("--to", dest="dto", required=True, help="window end, inclusive")
    p.add_argument(
        "--parked",
        default=None,
        help="the status that counts as 'still sitting there' (default: from the snapshot)",
    )
    p.add_argument(
        "--parked-cutoff",
        default=None,
        help="ignore issues that entered --parked on/after this date, so a "
        "grooming batch is not read as stagnation. "
        "Default: --to minus 4 days. 'none' disables.",
    )
    p.add_argument(
        "--stages",
        default=None,
        help="comma-separated stage scale, low->high (default: from the snapshot)",
    )
    p.add_argument(
        "--track",
        default=None,
        help="transitions into these statuses select an issue (default: from the snapshot)",
    )
    p.add_argument(
        "--done",
        default=None,
        help="the stage reported as the closed share (default: from the snapshot)",
    )
    p.add_argument(
        "--labels",
        default=None,
        help="chart categories in display order (default: from the snapshot)",
    )
    p.add_argument(
        "--no-fold-case",
        dest="fold_case",
        action="store_false",
        help="treat label spellings that differ only in case as distinct",
    )
    p.add_argument(
        "--restrict",
        action="append",
        default=[],
        metavar="LABEL=USER[,USER]",
        help="for this label only, keep just these assignees; "
        "'unassigned' is a valid entry. Repeatable.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        with open(a.snapshot, encoding="utf-8") as fh:
            snap = json.load(fh)
    except FileNotFoundError:
        sys.exit(f"No snapshot at {a.snapshot}. Run: jira-flow-report collect")

    # The alias map folds the changelog's status spelling onto the field spelling.
    # Jira can localise one and not the other; matching a single spelling silently
    # loses whole transition classes. Discovered at collect time, not hardcoded.
    if "status_aliases" not in snap:
        print(
            "warning: this snapshot carries no 'status_aliases' key. If the changelog "
            "and the REST fields spell any status differently, its transitions will be "
            "split across two buckets. Re-run 'jira-flow-report collect', or add the "
            "map by hand (see references/snapshot-schema.md).",
            file=sys.stderr,
        )
    aliases = snap.get("status_aliases") or {}

    def norm(name):
        return aliases.get(name, name)

    def listarg(v, fallback):
        if v:
            return [x.strip() for x in v.split(",") if x.strip()]
        return list(fallback or [])

    STAGES = listarg(a.stages, snap.get("stages"))
    TRACK = set(listarg(a.track, snap.get("track")))
    CATS = listarg(a.labels, snap.get("labels"))
    PARKED = a.parked or snap.get("parked")
    DONE = a.done or snap.get("done")

    missing = [
        n
        for n, v in (
            ("--stages", STAGES),
            ("--track", TRACK),
            ("--labels", CATS),
            ("--parked", PARKED),
            ("--done", DONE),
        )
        if not v
    ]
    if missing:
        sys.exit(
            f"{', '.join(missing)} not in the snapshot and not given on the command "
            f"line. Re-run 'jira-flow-report init', or pass them explicitly."
        )
    if DONE not in STAGES:
        sys.exit(f"--done {DONE!r} is not one of --stages {STAGES}")

    D_FROM, D_TO = parse_date(a.dfrom, "from"), parse_date(a.dto, "to")
    if D_FROM > D_TO:
        sys.exit(f"--from ({D_FROM}) is after --to ({D_TO})")
    if a.parked_cutoff is None:
        D_CUT = D_TO - dt.timedelta(days=4)
        cutoff_note = f"{D_CUT} (default: --to minus 4 days)"
    elif a.parked_cutoff.lower() == "none":
        D_CUT, cutoff_note = None, "disabled"
    else:
        D_CUT = parse_date(a.parked_cutoff, "parked-cutoff")
        cutoff_note = str(D_CUT)

    restrict: dict[str, set] = {}
    for r in a.restrict:
        if "=" not in r:
            sys.exit(f"--restrict wants LABEL=USER[,USER]; got {r!r}")
        lab, users = r.split("=", 1)
        allowed = set()
        for raw in users.split(","):
            user = raw.strip()
            if user:
                allowed.add(None if user.lower() in ("unassigned", "none", "-") else user)
        if not allowed:
            sys.exit(f"--restrict {r!r} lists no users")
        restrict[lab.strip()] = allowed
    unknown = sorted(set(restrict) - set(CATS))
    if unknown:
        print(
            f"warning: --restrict names label(s) {unknown} that are not among the "
            f"chart categories {CATS} — that restriction does nothing",
            file=sys.stderr,
        )

    if a.fold_case:
        folded, dropped = [], []
        for c in CATS:
            if c.lower() in {x.lower() for x in folded}:
                dropped.append(c)
            else:
                folded.append(c)
        if dropped:
            print(
                f"note: label spellings {dropped} fold into categories already listed; "
                f"charting {folded}. Pass --no-fold-case to keep them apart.",
                file=sys.stderr,
            )
            CATS = folded
    canon = {c.lower(): c for c in CATS} if a.fold_case else {c: c for c in CATS}
    if a.fold_case:

        def key_of(label):
            return label.lower()
    else:

        def key_of(label):
            return label

    rows = []
    for it in snap["issues"]:
        cats = sorted({canon[key_of(lab)] for lab in it["labels"] if key_of(lab) in canon})
        if not cats:
            continue
        hist = [(pdate(h["at"]), norm(h["from"]), norm(h["to"])) for h in it["history"]]
        cur = norm(it["status"])
        moved = [
            {"date": str(d), "from": f, "to": t}
            for d, f, t in hist
            if t in TRACK and D_FROM <= d <= D_TO
        ]
        entries = [d for d, _f, t in hist if t == PARKED]
        since = entries[-1] if entries else pdate(it["created"])
        parked = cur == PARKED and (D_CUT is None or since < D_CUT)
        if not moved and not parked:
            continue
        rows.append(
            {
                "key": it["key"],
                "summary": it["summary"],
                "cats": cats,
                "status": cur,
                "assignee": it["assignee"],
                "reason": "moved" if moved else "parked",
                "parked_since": str(since) if parked else None,
                "transitions": moved,
            }
        )

    # An issue selected by the window may since have moved to a status that is not
    # on the chart scale (typically back to the backlog). Prepend those rather than
    # dropping them, so the charts still sum to the row count, and say so.
    extra = sorted({r["status"] for r in rows} - set(STAGES))
    if extra:
        STAGES[:0] = extra
        print(
            f"note: {len(extra)} status(es) outside --stages, prepended to the scale: "
            f"{', '.join(extra)}",
            file=sys.stderr,
        )

    def keep(r, cat):
        return cat in r["cats"] and (cat not in restrict or r["assignee"] in restrict[cat])

    rep = {
        "schema": 1,
        "meta": {
            "server": snap.get("server", ""),
            "project": snap.get("project", ""),
            "board": snap.get("board"),
            "jql": snap.get("jql", ""),
            "window": [str(D_FROM), str(D_TO)],
            "parked": PARKED,
            "parked_cutoff": cutoff_note,
            "stages": STAGES,
            "done": DONE,
            "track": sorted(TRACK),
            "cats": CATS,
            "extra_stages": extra,
            "restrict": {
                k: sorted("unassigned" if u is None else u for u in v) for k, v in restrict.items()
            },
        },
        "cats": {},
        "excluded": [],
        "parked_list": [],
    }

    uniq: dict[str, dict] = {}
    for cat in CATS:
        sub = [r for r in rows if keep(r, cat)]
        for r in sub:
            uniq.setdefault(r["key"], dict(r, shown_cats=[]))["shown_cats"].append(cat)
        cnt = collections.Counter(r["status"] for r in sub)
        rep["cats"][cat] = {
            "total": len(sub),
            "counts": [cnt.get(s, 0) for s in STAGES],
            "done_pct": round(cnt.get(DONE, 0) / len(sub) * 100, 1) if sub else None,
            "issues": sorted(
                (
                    {
                        k: r[k]
                        for k in ("key", "status", "assignee", "reason", "parked_since", "summary")
                    }
                    for r in sub
                ),
                key=lambda x: (STAGES.index(x["status"]), x["key"]),
            ),
        }
    for cat, allowed in restrict.items():
        for r in rows:
            if cat in r["cats"] and r["assignee"] not in allowed:
                rep["excluded"].append(
                    {
                        "key": r["key"],
                        "label": cat,
                        "assignee": r["assignee"],
                        "status": r["status"],
                        "summary": r["summary"],
                        "kept_in": [c for c in r["cats"] if c != cat],
                    }
                )

    cnt = collections.Counter(r["status"] for r in uniq.values())
    tot = len(uniq)
    rep["all"] = {
        "total": tot,
        "counts": [cnt.get(s, 0) for s in STAGES],
        "done_pct": round(cnt.get(DONE, 0) / tot * 100, 1) if tot else None,
    }
    rep["parked_list"] = sorted(
        (
            {
                "key": r["key"],
                "cats": r["cats"],
                "since": r["parked_since"],
                "assignee": r["assignee"],
                "summary": r["summary"],
            }
            for r in uniq.values()
            if r["reason"] == "parked"
        ),
        key=lambda x: x["since"],
    )
    rep["table"] = sorted(uniq.values(), key=lambda r: (STAGES.index(r["status"]), r["key"]))

    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1)

    print(f"window {D_FROM}..{D_TO}   parked-cutoff {cutoff_note}", file=sys.stderr)
    print(f"{tot} unique issues, {rep['all']['done_pct']}% {DONE}", file=sys.stderr)
    for cat in CATS:
        c = rep["cats"][cat]
        print(
            f"  {cat:14s} {c['total']:4d}   {DONE} {c['done_pct']}%   {c['counts']}",
            file=sys.stderr,
        )
    if rep["excluded"]:
        print(f"  {len(rep['excluded'])} label-rows dropped by --restrict", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
