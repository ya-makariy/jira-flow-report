"""Command line entry point."""
from __future__ import annotations

import argparse
import sys

from jira_flow_report import __version__, config


def cmd_init(args) -> int:
    from jira_flow_report import discover, install

    cfg = config.load(required=False)
    assume = args.yes
    server = (args.server or cfg.get("server")
              or discover.ask("Jira base URL (e.g. https://jira.example.com)",
                              cfg.get("server"), assume=assume))
    server = server.rstrip("/")
    print(f"\nconnecting to {server} ...")
    client = config.client(server)
    try:
        who = client.current_user()
        print(f"  authenticated as {who}")
    except Exception as exc:
        sys.exit(f"Could not authenticate against {server}: {exc}")

    board = discover.discover_board(client, server, args.board or cfg.get("board"),
                                    assume=assume)
    print(f"  board: {board['name']} (id {board['id']})")

    stage_meta = discover.discover_stages(client, board["_config"])
    if not stage_meta:
        sys.exit("That board exposes no columns with statuses — pick another board.")
    stages = [s["name"] for s in stage_meta]
    print("  stage scale from the board's columns:")
    for i, s in enumerate(stage_meta, 1):
        print(f"    {i}. {s['name']}  ({s['category']}, column {s['column']!r})")

    project = (args.project or discover.discover_project(client, server, board["id"])
               or cfg.get("project"))
    project = discover.ask("Project key", project, assume=assume)
    print(f"  project: {project}")

    board_filter = ""
    if board.get("filter_id"):
        try:
            board_filter = client.filter(board["filter_id"]).jql
        except Exception:
            pass

    print("\nscanning labels ...")
    counts = discover.discover_labels(client, project)
    if not counts:
        sys.exit(f"No labels found on any issue in {project}. This report groups by "
                 f"label, so there is nothing to chart.")
    options = [l for l, _ in counts.most_common()]
    for l, n in counts.most_common(20):
        print(f"    {n:5d}  {l}")
    # case variants of one label are one category; keep the most common spelling
    canon: dict[str, str] = {}
    for l, _ in counts.most_common():
        canon.setdefault(l.lower(), l)
    default = list(dict.fromkeys(canon[l.lower()] for l, _ in counts.most_common()))[:5]
    if args.labels:
        labels = [l.strip() for l in args.labels.split(",") if l.strip()]
        unknown = [l for l in labels if l.lower() not in canon]
        if unknown:
            sys.exit(f"--labels names label(s) not present on any {project} issue: {unknown}")
        print(f"  categories from --labels: {', '.join(labels)}")
    else:
        labels = discover.multipick("Which labels are the report's categories?",
                                    options, default, assume=assume)
    fetch_labels = sorted({l for l in options if l.lower() in {x.lower() for x in labels}})

    print("\ndiscovering status spellings from changelogs ...")
    aliases, unmapped = discover.discover_status_aliases(client, project)
    if aliases:
        for k, v in sorted(aliases.items()):
            print(f"    changelog {k!r} == field {v!r}")
    else:
        print("    the changelog and the fields agree — no alias map needed")
    if unmapped:
        print(f"    note: no mapping observed for {unmapped}; they will be reported "
              f"under their changelog spelling")

    roles = discover.suggest_roles(stage_meta)
    parked = discover.ask(f"Which stage is the 'queued and sitting there' column?",
                          roles["parked"], assume=assume)
    done = discover.ask("Which stage counts as closed?", roles["done"], assume=assume)
    track_default = ",".join(roles["track"])
    track = discover.ask("Transitions into which stages count as movement? (comma-separated)",
                         track_default, assume=assume)
    track = [t.strip() for t in track.split(",") if t.strip()]
    lang = args.lang or discover.ask("Report language (en/ru)",
                                     cfg.get("lang", "en"), assume=assume)

    for name, val in (("parked", parked), ("done", done)):
        if val not in stages:
            sys.exit(f"{name} = {val!r} is not one of the board's stages {stages}")
    bad = [t for t in track if t not in stages]
    if bad:
        sys.exit(f"track names stages that are not on the board: {bad}")

    new = {
        "server": server, "project": project, "board": board["id"],
        "board_name": board["name"], "board_filter": board_filter,
        "labels": labels, "fetch_labels": fetch_labels,
        "stages": stages, "parked": parked, "done": done, "track": track,
        "status_aliases": aliases, "lang": lang if lang in ("en", "ru") else "en",
        "stage_meta": stage_meta,
    }
    path = config.save(new)
    print(f"\nwrote {path}")

    if args.install or (not args.no_install and discover.ask(
            "Install the Claude Code skill now? (y/n)", "y", assume=assume).lower().startswith("y")):
        ns = argparse.Namespace(skills_dir="~/.claude/skills", desktop_zip=None,
                                desktop_zip_only=False, force=True)
        install.run(ns)
    return 0


def cmd_show_config(args) -> int:
    import tomli_w

    cfg = config.load()
    print(f"# {config.config_path()}")
    sys.stdout.write(tomli_w.dumps(cfg))
    return 0


def cmd_collect(args) -> int:
    from jira_flow_report import collect

    return collect.run(args)


def cmd_report(args, rest: list[str]) -> int:
    from jira_flow_report import aggregate, collect, render

    if not args.snapshot:
        ns = argparse.Namespace(server=None, project=None, labels=None,
                                categories=None, jql=None, board=None,
                                out="snapshot.json", rediscover_aliases=False)
        rc = collect.run(ns)
        if rc:
            return rc
        snap = "snapshot.json"
    else:
        snap = args.snapshot
    cfg = config.load(required=False)
    agg = ["-i", snap, "-o", args.report, "--from", args.dfrom, "--to", args.dto]
    if args.parked_cutoff:
        agg += ["--parked-cutoff", args.parked_cutoff]
    for r in args.restrict or []:
        agg += ["--restrict", r]
    agg += rest
    rc = aggregate.main(agg)
    if rc:
        return rc
    ren = ["-i", args.report, "-o", args.out, "--lang", args.lang or cfg.get("lang", "en")]
    if args.heading:
        ren += ["--heading", args.heading]
    if args.title:
        ren += ["--title", args.title]
    return render.main(ren)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(
        prog="jira-flow-report",
        description="Kanban flow reports for any Jira board, plus the Claude skill "
                    "that drives them.")
    p.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("init", help="interactive setup: asks what only you know, "
                                    "reads the rest off the Jira API")
    i.add_argument("--server"); i.add_argument("--project"); i.add_argument("--board")
    i.add_argument("--labels",
                   help="comma-separated chart categories, skipping the interactive pick")
    i.add_argument("--lang", help="report language (en/ru)")
    i.add_argument("-y", "--yes", action="store_true",
                   help="accept every discovered default; needed when there is no terminal")
    i.add_argument("--install", action="store_true", help="install the skill without asking")
    i.add_argument("--no-install", action="store_true", help="skip installing the skill")
    i.set_defaults(fn=cmd_init)

    sub.add_parser("show-config", help="print the resolved config").set_defaults(fn=cmd_show_config)

    ins = sub.add_parser("install", help="(re)generate and install the Claude skill")
    ins.add_argument("--skills-dir", default="~/.claude/skills")
    ins.add_argument("--desktop-zip", nargs="?", const="jira-flow-report-desktop.zip",
                     help="also build a Claude Desktop zip at this path")
    ins.add_argument("--desktop-zip-only", action="store_true",
                     help="build only the zip, do not touch the skills dir")
    ins.add_argument("--force", action="store_true")
    ins.set_defaults(fn=cmd_install)

    c = sub.add_parser("collect", help="step 1: Jira -> snapshot.json (needs network)")
    c.add_argument("--server"); c.add_argument("--project")
    c.add_argument("--labels", help="label spellings to query, comma-separated "
                                    "(JQL labels are case-sensitive)")
    c.add_argument("--categories", help="chart categories, comma-separated; defaults to the "
                                        "configured ones, else the fetched spellings folded")
    c.add_argument("--board"); c.add_argument("--jql")
    c.add_argument("--rediscover-aliases", action="store_true",
                   help="re-derive the status alias map instead of using the config's")
    c.add_argument("-o", "--out", default="snapshot.json")
    c.set_defaults(fn=cmd_collect)

    sub.add_parser("aggregate", add_help=False,
                   help="step 2: snapshot + dates -> report.json (offline)")
    sub.add_parser("render", add_help=False,
                   help="step 3: report.json -> flow.html (offline)")

    r = sub.add_parser("report", help="run all three steps")
    r.add_argument("--from", dest="dfrom", required=True)
    r.add_argument("--to", dest="dto", required=True)
    r.add_argument("--snapshot", help="reuse this snapshot instead of fetching")
    r.add_argument("--parked-cutoff")
    r.add_argument("--restrict", action="append")
    r.add_argument("--report", default="report.json")
    r.add_argument("-o", "--out", default="flow.html")
    r.add_argument("--lang"); r.add_argument("--title"); r.add_argument("--heading")
    r.set_defaults(fn=None)

    # aggregate/render forward their argv untouched to the standalone modules
    if argv and argv[0] == "aggregate":
        from jira_flow_report import aggregate
        return aggregate.main(argv[1:])
    if argv and argv[0] == "render":
        from jira_flow_report import render
        return render.main(argv[1:])
    if argv and argv[0] == "report":
        args, rest = r.parse_known_args(argv[1:])
        return cmd_report(args, rest)

    args = p.parse_args(argv)
    return args.fn(args)


def cmd_install(args) -> int:
    from jira_flow_report import install

    return install.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
