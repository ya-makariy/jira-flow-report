"""Command line entry point."""

from __future__ import annotations

import argparse
import contextlib
import os
import sys

from jira_flow_report import buildinfo, config, ui


def cmd_init(args) -> int:
    from jira_flow_report import discover, install, render

    cfg = config.load(required=False)
    assume = args.yes
    server = (
        args.server
        or cfg.get("server")
        or discover.ask(
            "Jira base URL (e.g. https://jira.example.com)", cfg.get("server"), assume=assume
        )
    )
    server = server.rstrip("/")
    print(f"\nconnecting to {server} ...")
    client = config.client(server)
    try:
        who = client.current_user()
        print(f"  authenticated as {who}")
    except Exception as exc:  # noqa: BLE001 - any auth failure is fatal here
        sys.exit(f"Could not authenticate against {server}: {exc}")

    board = discover.discover_board(client, server, args.board or cfg.get("board"), assume=assume)
    print(f"  board: {board['name']} (id {board['id']})")

    stage_meta = discover.discover_stages(client, board["_config"])
    if not stage_meta:
        sys.exit("That board exposes no columns with statuses — pick another board.")
    stages = [s["name"] for s in stage_meta]
    print("  stage scale from the board's columns:")
    for i, s in enumerate(stage_meta, 1):
        print(f"    {i}. {s['name']}  ({s['category']}, column {s['column']!r})")

    project = (
        args.project or discover.discover_project(client, server, board["id"]) or cfg.get("project")
    )
    project = discover.ask("Project key", project, assume=assume)
    print(f"  project: {project}")

    board_filter = ""
    if board.get("filter_id"):
        with contextlib.suppress(Exception):  # the filter JQL is a nice-to-have
            board_filter = client.filter(board["filter_id"]).jql

    counts = discover.discover_labels(client, project)
    if not counts:
        sys.exit(
            f"No labels found on any issue in {project}. This report groups by "
            "label, so there is nothing to chart."
        )
    options = [lab for lab, _ in counts.most_common()]
    for lab, n in counts.most_common(20):
        print(f"    {n:5d}  {lab}")
    # case variants of one label are one category; keep the most common spelling
    canon: dict[str, str] = {}
    for lab, _ in counts.most_common():
        canon.setdefault(lab.lower(), lab)
    default = list(dict.fromkeys(canon[lab.lower()] for lab, _ in counts.most_common()))[:5]
    if args.labels:
        labels = [lab.strip() for lab in args.labels.split(",") if lab.strip()]
        unknown = [lab for lab in labels if lab.lower() not in canon]
        if unknown:
            sys.exit(f"--labels names label(s) not present on any {project} issue: {unknown}")
        print(f"  categories from --labels: {', '.join(labels)}")
    else:
        labels = discover.multipick(
            "Which labels are the report's categories?", options, default, assume=assume
        )
    fetch_labels = sorted({lab for lab in options if lab.lower() in {x.lower() for x in labels}})

    # stages come from the board above, so discovery can stop as soon as it has
    # seen every one of them instead of grinding through a fixed sample
    aliases, unmapped = discover.discover_status_aliases(client, project, stages=stages)
    if aliases:
        for k, v in sorted(aliases.items()):
            print(f"    changelog {k!r} == field {v!r}")
    else:
        print("    the changelog and the fields agree — no alias map needed")
    if unmapped:
        print(
            f"    note: no mapping observed for {unmapped}; they will be reported "
            f"under their changelog spelling"
        )

    roles = discover.suggest_roles(stage_meta)
    parked = discover.ask(
        "Which stage is the 'queued and sitting there' column?", roles["parked"], assume=assume
    )
    done = discover.ask("Which stage counts as closed?", roles["done"], assume=assume)
    track_default = ",".join(roles["track"])
    track = discover.ask(
        "Transitions into which stages count as movement? (comma-separated)",
        track_default,
        assume=assume,
    )
    track = [t.strip() for t in track.split(",") if t.strip()]
    lang = args.lang or discover.ask(
        "Report language (en/ru)", cfg.get("lang", "en"), assume=assume
    )
    palette = args.palette or discover.ask(
        "Stage colours: status (a hue per stage) or mono (one blue ramp)",
        cfg.get("palette", render.PALETTES[0]),
        assume=assume,
    )

    for name, val in (("parked", parked), ("done", done)):
        if val not in stages:
            sys.exit(f"{name} = {val!r} is not one of the board's stages {stages}")
    bad = [t for t in track if t not in stages]
    if bad:
        sys.exit(f"track names stages that are not on the board: {bad}")

    new = {
        "server": server,
        "project": project,
        "board": board["id"],
        "board_name": board["name"],
        "board_filter": board_filter,
        "labels": labels,
        "fetch_labels": fetch_labels,
        "stages": stages,
        "parked": parked,
        "done": done,
        "track": track,
        "status_aliases": aliases,
        "lang": lang if lang in ("en", "ru") else "en",
        "palette": palette if palette in render.PALETTES else render.PALETTES[0],
        "stage_meta": stage_meta,
    }
    path = config.save(new)
    print(f"\nwrote {path}")

    if args.install or (
        not args.no_install
        and discover.ask("Install the Claude Code skill now? (y/n)", "y", assume=assume)
        .lower()
        .startswith("y")
    ):
        ns = argparse.Namespace(
            skills_dir="~/.claude/skills", desktop_zip=None, desktop_zip_only=False, force=True
        )
        install.run(ns)
    return 0


def cmd_status(args) -> int:
    """What is installed, what is stale."""
    from jira_flow_report import update

    info = buildinfo.get()
    st = update.check(offline=args.offline, force=args.refresh, skills_dir=args.skills_dir)
    c = ui.err()

    def row(label: str, value: str) -> None:
        c.print(f"  [dim]{label:<13}[/dim] {value}")

    row("version", info.version)
    row("built", info.build_date or "[dim]unknown[/dim]")
    if info.commit:
        row("commit", info.commit + (" [yellow](dirty)[/yellow]" if info.dirty else ""))
    row("source", info.source)
    if st.cli_latest:
        row(
            "latest",
            f"{st.cli_latest}"
            + ("  [yellow]← newer[/yellow]" if st.cli_outdated else "  [green](current)[/green]"),
        )
    elif not args.offline:
        row("latest", "[dim]no published release to compare against[/dim]")

    dest = update.skill_dir(args.skills_dir)
    stamp = update.read_stamp(dest)
    c.print()
    row("skill", str(dest) if st.skill_installed else "[dim]not installed[/dim]")
    if stamp:
        row(
            "generated by",
            f"{stamp.get('generated_by', '?')}  [dim]{stamp.get('generated_at', '')}[/dim]",
        )
    if st.skill_stale:
        row("state", f"[yellow]stale[/yellow] [dim]— {st.skill_reason}[/dim]")
    elif st.skill_installed:
        row("state", "[green]current[/green]")

    cfg = config.load(required=False)
    c.print()
    row("config", str(config.config_path()) if cfg else "[dim]not set up[/dim]")
    if cfg:
        row("board", f"{cfg.get('board_name', '?')} [dim](id {cfg.get('board')})[/dim]")
        row("labels", ", ".join(cfg.get("labels") or []))
    ui.update_notice(st)
    return 0


def cmd_update(args) -> int:
    """Bring the CLI and the generated skill up to date."""
    from jira_flow_report import install, prompts, update

    st = update.check(offline=args.offline, force=True, skills_dir=args.skills_dir)
    did_something = False

    if args.skill_only:
        ui.info("skipping the CLI (--skill-only)")
    elif st.cli_outdated or args.force:
        if st.cli_outdated:
            ui.info(f"CLI {st.cli_current} → {st.cli_latest}")
        if args.yes or prompts.confirm("Update the CLI now?", True, assume=args.yes):
            rc = update.self_update(dry_run=args.dry_run)
            if rc:
                return rc
            did_something = True
            if not args.dry_run:
                ui.warn(
                    "the CLI was replaced; re-run 'jira-flow-report update' "
                    "to regenerate the skill with the new version"
                )
                return 0
    else:
        ui.ok(f"CLI is current ({st.cli_current})")

    if args.cli_only:
        ui.info("skipping the skill (--cli-only)")
        return 0

    cfg = config.load(required=False)
    if not cfg:
        ui.warn("no config yet, so there is no skill to generate — run 'jira-flow-report init'")
        return 0
    if st.skill_stale or args.force:
        if st.skill_stale:
            ui.info(f"skill: {st.skill_reason}")
        if args.dry_run:
            ui.info("dry run: would regenerate the skill")
            return 0
        ns = argparse.Namespace(
            skills_dir=args.skills_dir,
            desktop_zip=args.desktop_zip,
            desktop_zip_only=False,
            force=True,
        )
        install.run(ns)
        did_something = True
    else:
        ui.ok("skill is current")

    if not did_something:
        ui.info("nothing to do")
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
        ns = argparse.Namespace(
            server=None,
            project=None,
            labels=None,
            categories=None,
            jql=None,
            board=None,
            out="snapshot.json",
            rediscover_aliases=False,
        )
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
    ren += ["--palette", args.palette or cfg.get("palette", render.PALETTES[0])]
    if args.heading:
        ren += ["--heading", args.heading]
    if args.title:
        ren += ["--title", args.title]
    return render.main(ren)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--no-banner" in argv:
        argv.remove("--no-banner")
        os.environ[ui.NO_BANNER_ENV] = "1"
    p = argparse.ArgumentParser(
        prog="jira-flow-report",
        description="Kanban flow reports for any Jira board, plus the Claude skill "
        "that drives them.",
    )
    p.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s {buildinfo.get().short()}"
    )
    p.add_argument(
        "--no-banner",
        action="store_true",
        help="suppress the header (also: JIRA_FLOW_REPORT_NO_BANNER=1)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser(
        "init", help="interactive setup: asks what only you know, reads the rest off the Jira API"
    )
    i.add_argument("--server")
    i.add_argument("--project")
    i.add_argument("--board")
    i.add_argument(
        "--labels", help="comma-separated chart categories, skipping the interactive pick"
    )
    i.add_argument("--lang", help="report language (en/ru)")
    i.add_argument("--palette", help="stage colours: status or mono")
    i.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="accept every discovered default; needed when there is no terminal",
    )
    i.add_argument("--install", action="store_true", help="install the skill without asking")
    i.add_argument("--no-install", action="store_true", help="skip installing the skill")
    i.set_defaults(fn=cmd_init)

    sub.add_parser("show-config", help="print the resolved config").set_defaults(fn=cmd_show_config)

    stt = sub.add_parser(
        "status", help="version, build date, and whether the CLI or the skill is out of date"
    )
    stt.add_argument("--skills-dir", default="~/.claude/skills")
    stt.add_argument("--offline", action="store_true", help="skip the upstream check")
    stt.add_argument("--refresh", action="store_true", help="ignore the cached check")
    stt.set_defaults(fn=cmd_status)

    upd = sub.add_parser("update", help="update the CLI and regenerate the skill")
    upd.add_argument("--skills-dir", default="~/.claude/skills")
    upd.add_argument("--cli-only", action="store_true")
    upd.add_argument("--skill-only", action="store_true")
    upd.add_argument(
        "--desktop-zip",
        nargs="?",
        const="jira-flow-report-desktop.zip",
        help="also rebuild the Claude Desktop bundle",
    )
    upd.add_argument(
        "--force",
        action="store_true",
        help="reinstall and regenerate even when nothing looks stale",
    )
    upd.add_argument("--offline", action="store_true")
    upd.add_argument("--dry-run", action="store_true")
    upd.add_argument("-y", "--yes", action="store_true")
    upd.set_defaults(fn=cmd_update)

    ins = sub.add_parser("install", help="(re)generate and install the Claude skill")
    ins.add_argument("--skills-dir", default="~/.claude/skills")
    ins.add_argument(
        "--desktop-zip",
        nargs="?",
        const="jira-flow-report-desktop.zip",
        help="also build a Claude Desktop zip at this path",
    )
    ins.add_argument(
        "--desktop-zip-only",
        action="store_true",
        help="build only the zip, do not touch the skills dir",
    )
    ins.add_argument("--force", action="store_true")
    ins.set_defaults(fn=cmd_install)

    c = sub.add_parser("collect", help="step 1: Jira -> snapshot.json (needs network)")
    c.add_argument("--server")
    c.add_argument("--project")
    c.add_argument(
        "--labels", help="label spellings to query, comma-separated (JQL labels are case-sensitive)"
    )
    c.add_argument(
        "--categories",
        help="chart categories, comma-separated; defaults to the "
        "configured ones, else the fetched spellings folded",
    )
    c.add_argument("--board")
    c.add_argument("--jql")
    c.add_argument(
        "--rediscover-aliases",
        action="store_true",
        help="re-derive the status alias map instead of using the config's",
    )
    c.add_argument("-o", "--out", default="snapshot.json")
    c.set_defaults(fn=cmd_collect)

    sub.add_parser(
        "aggregate", add_help=False, help="step 2: snapshot + dates -> report.json (offline)"
    )
    sub.add_parser("render", add_help=False, help="step 3: report.json -> flow.html (offline)")

    r = sub.add_parser("report", help="run all three steps")
    r.add_argument("--from", dest="dfrom", required=True)
    r.add_argument("--to", dest="dto", required=True)
    r.add_argument("--snapshot", help="reuse this snapshot instead of fetching")
    r.add_argument("--parked-cutoff")
    r.add_argument("--restrict", action="append")
    r.add_argument("--report", default="report.json")
    r.add_argument("-o", "--out", default="flow.html")
    r.add_argument("--lang")
    r.add_argument("--palette", help="stage colours: status (default) or mono")
    r.add_argument("--title")
    r.add_argument("--heading")
    r.set_defaults(fn=None)

    # aggregate/render forward their argv untouched to the standalone modules
    if argv and argv[0] == "aggregate":
        from jira_flow_report import aggregate

        return aggregate.main(argv[1:])
    if argv and argv[0] == "render":
        from jira_flow_report import render

        return render.main(argv[1:])
    if not argv:
        ui.banner(force=True)
        p.print_help()
        return 0
    if argv and argv[0] == "report":
        args, rest = r.parse_known_args(argv[1:])
        return cmd_report(args, rest)

    args = p.parse_args(argv)
    ui.banner()
    try:
        rc = args.fn(args)
    except (prompts_aborted(), KeyboardInterrupt):
        ui.err().print()
        ui.warn("cancelled — nothing was written")
        return 130
    _passive_notice(args)
    return rc


def prompts_aborted() -> type[BaseException]:
    """Imported lazily so the offline paths never pull in prompt_toolkit."""
    from jira_flow_report.prompts import Aborted

    return Aborted


# Commands that already reach the network, or that a human is sitting in front
# of. The offline steps stay strictly offline: no notice, no lookup.
NOTICE_COMMANDS = {"init", "collect", "report", "install"}


def _passive_notice(args) -> None:
    if getattr(args, "cmd", None) not in NOTICE_COMMANDS:
        return
    if not ui.interactive():
        return
    try:
        from jira_flow_report import update

        ui.update_notice(update.check())
    except Exception:  # noqa: BLE001 - a notice must never break the command
        pass


def cmd_install(args) -> int:
    from jira_flow_report import install

    return install.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
