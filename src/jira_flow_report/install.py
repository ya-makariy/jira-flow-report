"""Render the skill from templates and install it, for Claude Code or as a
Claude Desktop zip. All instance-specific values come from the config, so the
templates in the repository stay generic."""

from __future__ import annotations

import json
import shutil
import string
import sys
import zipfile
from pathlib import Path

from jira_flow_report import config, ui, update

RUN_CODE = """```bash
S=~/.claude/skills/jira-flow-report/scripts
jira-flow-report collect -o snapshot.json
python3 $S/aggregate.py -i snapshot.json -o report.json \\
    --from 2026-08-10 --to 2026-08-21 \\
    --parked-cutoff 2026-08-17
python3 $S/render.py -i report.json -o flow.html --lang ${lang} --palette ${palette}
```

`jira-flow-report report --from ... --to ...` runs all three in one go.

Step 1 needs `JIRA_API_TOKEN` in the environment — never print it, never write it
into a file. Steps 2 and 3 are stdlib-only, so any `python3` works.

Then publish `flow.html` with the **Artifact** tool (favicon `📊`) and give the
user the link.

Report the headline numbers in chat as well — total, percent closed, and what
is stuck — because handing over a file or a link does not answer the question.
"""

RUN_DESKTOP = """Step 1 does not run in this environment — see **Environment** below. Start from
a `snapshot.json` the user provides, then:

```bash
python3 scripts/aggregate.py -i snapshot.json -o report.json \\
    --from 2026-08-10 --to 2026-08-21 \\
    --parked-cutoff 2026-08-17
python3 scripts/render.py -i report.json -o flow.html --lang ${lang} \\
    --palette ${palette}
```

Both are stdlib-only — no install, no network. Paths are relative to this skill's
own directory.

Then offer `flow.html` to the user as a file to download.

Report the headline numbers in chat as well — total, percent closed, and what
is stuck — because handing over a file or a link does not answer the question.
"""

FRONTMATTER_CODE = (
    'argument-hint: "[from] [to] [--parked-cutoff DATE] '
    '[--restrict LABEL=USER,...]"\nallowed-tools: Bash, Read, Write, Edit, Artifact\n'
)


def template_dir() -> Path:
    """Works both from an installed wheel and from a source checkout."""
    for cand in (Path(__file__).parent / "skill", Path(__file__).parent.parent.parent / "skill"):
        if (cand / "SKILL.md.tmpl").exists():
            return cand
    sys.exit("Cannot locate the skill templates. Reinstall the package.")


def _fmt_list(xs) -> str:
    return ", ".join(f"`{x}`" for x in xs) if xs else "_not set_"


def build_vars(cfg: dict, target: str) -> dict:
    aliases = cfg.get("status_aliases") or {}
    if aliases:
        rows = "\n".join(f"| `{k}` | `{v}` |" for k, v in sorted(aliases.items()))
        aliases_table = "| Changelog spelling | Field spelling |\n|---|---|\n" + rows
        aliases_note = (
            "The changelog and the REST fields spell some statuses differently on this "
            "instance — the mapping was discovered from the data and travels inside the "
            "snapshot. See `references/jira-quirks.md`."
        )
    else:
        aliases_table = (
            "_No differing spellings were observed — the changelog and the "
            "fields agree on this instance._"
        )
        aliases_note = (
            "No status spelling differences were observed on this instance, so "
            "no alias mapping is applied."
        )
    stages = cfg.get("stages") or []
    stage_meta = cfg.get("stage_meta") or []
    if stage_meta:
        stages_table = "| # | Status | Category | Board column |\n|---|---|---|---|\n" + "\n".join(
            f"| {i} | `{s['name']}` | {s['category']} | {s['column']} |"
            for i, s in enumerate(stage_meta, 1)
        )
    else:
        stages_table = "\n".join(f"{i}. `{s}`" for i, s in enumerate(stages, 1)) or "_not set_"
    labels = cfg.get("labels") or []
    return {
        "server": cfg.get("server", ""),
        "project": cfg.get("project", ""),
        "board": cfg.get("board", "—"),
        "board_json": json.dumps(cfg.get("board")),
        "parked": cfg.get("parked", ""),
        "done": cfg.get("done", ""),
        "lang": cfg.get("lang", "en"),
        "palette": cfg.get("palette", "status"),
        "stages": _fmt_list(stages),
        "track": _fmt_list(cfg.get("track") or []),
        "labels": ", ".join(labels) if labels else "_not set_",
        "stages_json": json.dumps(stages, ensure_ascii=False),
        "track_json": json.dumps(cfg.get("track") or [], ensure_ascii=False),
        "labels_json": json.dumps(labels, ensure_ascii=False),
        "aliases_json": json.dumps(aliases, ensure_ascii=False),
        "aliases_table": aliases_table,
        "aliases_note": aliases_note,
        "stages_table": stages_table,
        "filter_note": cfg.get("board_filter") or "not recorded",
        "sample_key": f"{cfg.get('project', 'ABC')}-1234",
        "sample_labels": json.dumps(labels[:1] or ["backend"], ensure_ascii=False),
        "frontmatter_extra": "" if target == "desktop" else FRONTMATTER_CODE,
        "run_block": RUN_DESKTOP if target == "desktop" else RUN_CODE,
    }


def render_skill(cfg: dict, dest: Path, target: str) -> None:
    tdir = template_dir()
    v = build_vars(cfg, target)

    # two passes: run_block itself carries ${lang}
    def sub(text: str) -> str:
        out = string.Template(text).safe_substitute(v)
        return string.Template(out).safe_substitute(v)

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "SKILL.md").write_text(sub((tdir / "SKILL.md.tmpl").read_text()))
    refs = dest / "references"
    refs.mkdir(exist_ok=True)
    for tpl in sorted((tdir / "references").glob("*.md.tmpl")):
        (refs / tpl.name[: -len(".tmpl")]).write_text(sub(tpl.read_text()))
    scripts = dest / "scripts"
    scripts.mkdir(exist_ok=True)
    here = Path(__file__).parent
    for name in ("aggregate.py", "render.py"):
        shutil.copy2(here / name, scripts / name)
    # so `status` can tell whether this copy still matches the CLI and the config
    update.write_stamp(dest, cfg)


def run(args) -> int:
    cfg = config.load()
    made = []

    if not args.desktop_zip_only:
        dest = Path(args.skills_dir).expanduser() / "jira-flow-report"
        if dest.exists() and not args.force:
            ui.info(f"{dest} exists — overwriting its generated files")
        render_skill(cfg, dest, target="code")
        made.append(str(dest))

    if args.desktop_zip or args.desktop_zip_only:
        out = Path(args.desktop_zip or "jira-flow-report-desktop.zip").expanduser()
        staging = out.parent / ".jfr-desktop-staging"
        if staging.exists():
            shutil.rmtree(staging)
        render_skill(cfg, staging / "jira-flow-report", target="desktop")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(staging.rglob("*")):
                if p.is_file() and "__pycache__" not in p.parts:
                    z.write(p, p.relative_to(staging))
        shutil.rmtree(staging)
        made.append(str(out))

    for m in made:
        ui.ok(f"installed [bold]{m}[/bold]")
    if not args.desktop_zip_only:
        ui.info(
            "restart Claude Code (or start a new session) for "
            "[bold]/jira-flow-report[/bold] to appear"
        )
    return 0
