# jira-flow-report

[![CI](https://github.com/ya-makariy/jira-flow-report/actions/workflows/ci.yml/badge.svg)](https://github.com/ya-makariy/jira-flow-report/actions/workflows/ci.yml)

Kanban flow reports for any Jira board — and the [Claude
skill](https://code.claude.com/docs/en/skills) that drives them.

Pick a date window. Get one donut per label showing what stage that label's work
is at and what share of it is closed, a 100%-stacked bar so the labels can
actually be compared, the full issue table, and a written record of every
selection rule that produced those numbers.

Built for retro prep, where the question is "where does our work actually stand"
and the answer has to survive someone asking how it was counted.

```
┌─ backend ──────────┐  ┌─ frontend ─────────┐  ┌─ devops ───────────┐
│      ╭─────╮       │  │      ╭─────╮       │  │      ╭─────╮       │
│     │  81%  │      │  │     │  54%  │      │  │     │  50%  │      │
│      ╰─────╯       │  │      ╰─────╯       │  │      ╰─────╯       │
│  ■ Selected     1  │  │  ■ Selected     3  │  │  ■ In Progress  2  │
│  ■ In Progress 10  │  │  ■ In Progress  6  │  │  ■ Testing      1  │
│  ■ In Review    3  │  │  ■ In Review    3  │  │  ■ Done         3  │
│  ■ Done        58  │  │  ■ Testing      4  │  └────────────────────┘
└────────────────────┘  │  ■ Done        19  │
                        └────────────────────┘
```

## Why not just read the board

Three things a board will not tell you, and this will:

- **What moved in a period**, not what is on screen now. Selection runs off the
  changelog, so a window is a real window.
- **What is stuck versus what was just groomed.** A bulk move into the queued
  column stamps a fresh date on every issue it touches, which looks exactly like
  stagnation. There is an explicit cutoff for that, and the report names the
  value it used.
- **Percent closed per discipline**, with the filtering rules written on the page
  rather than living in someone's head.

## Install

Python 3.11+. Either package manager works:

```bash
uv tool install jira-flow-report      # recommended: isolated, on PATH
pipx install jira-flow-report         # same idea, without uv
pip install jira-flow-report          # into the current environment
```

Run it once without installing anything:

```bash
uvx jira-flow-report status
```

`uv tool` and `pipx` are the right choice for a CLI: the tool and its
dependencies land in their own environment instead of whatever `pip` happens to
be pointing at. Plain `pip install` works too — you just get `jira-flow-report`
on the PATH of that environment only.

Unreleased code, or a fork:

```bash
uv tool install git+https://github.com/ya-makariy/jira-flow-report
pip install     git+https://github.com/ya-makariy/jira-flow-report

git clone https://github.com/ya-makariy/jira-flow-report && cd jira-flow-report
uv tool install .
```

### Authentication

The tool reads a personal access token from the environment and never writes it
to disk:

```bash
export JIRA_API_TOKEN='...'
```

On Jira Server / Data Center, create one under **Profile → Personal Access
Tokens**. On Jira Cloud, use an API token and check that your deployment accepts
it as a bearer token.

### Setup

```bash
jira-flow-report init
```

`init` is interactive: **↑↓** to move, **Space** to mark in a multi-select,
**Enter** to submit. Text prompts show the default and take it on an empty Enter.
Ctrl-C at any prompt exits without writing anything.

Every prompt has a flag, so nothing about it blocks a script or an agent. With no
terminal each prompt resolves to its default and says so on stderr rather than
hanging:

```bash
jira-flow-report init --server https://jira.example.com --board 42 \
    --labels backend,frontend,ops --lang en --yes
```

`init` asks only for what an API cannot tell it — the base URL, which board, and
which labels are the report's categories — and reads everything else off Jira:

| Discovered | From |
|---|---|
| the stage scale, in order | the board's column configuration |
| each stage's category (queued / in progress / done) | `/rest/api/2/status` |
| the project key | an issue actually on the board |
| the label list, with counts | a scan of the project's issues |
| the board's saved filter | `/rest/api/2/filter/{id}` |
| **the status name alias map** | paired from issue changelogs — see below |

It writes `~/.config/jira-flow-report/config.toml` (mode 600) and offers to
install the Claude skill. Re-run it after a workflow change.

Non-interactive, for scripts and agents:

```bash
jira-flow-report init --server https://jira.example.com --board 42 --yes
```

## Staying current

```bash
jira-flow-report status     # version, build date, and what is stale
jira-flow-report update     # update the CLI, then regenerate the skill
```

Two things go stale independently, and the second one is the dangerous one:

- the **CLI**, when a newer release exists upstream;
- the **skill**, which is *generated* — so it drifts when either the tool version
  or your config moves on. Nothing errors when that happens. Claude simply keeps
  following instructions that no longer match the code, which is why `status`
  reports it and why the generated skill carries a `.generated.json` stamp
  recording the version, commit and a fingerprint of the config that produced it.

`update` handles both, asks before replacing anything, and takes `--cli-only`,
`--skill-only`, `--dry-run`, `--force` and `-y`. Because updating the CLI swaps
the code out from under the running process, it stops there and asks you to
re-run so the skill is regenerated by the new version rather than the old one.

### When a step takes a while

`init` and `collect` ask Jira for issues with `expand=changelog`, which is the
expensive call — measured at roughly **20x** a plain page, and up to 12s for 50
issues on a healthy server. Both show a spinner with a running count, so a slow
server looks slow rather than wedged.

Alias discovery stops as soon as it has seen every stage on the board, which is
usually one or two pages instead of six. On one real board that is 3.6s instead
of 14.3s, for the identical result.

Every request carries a 60-second timeout. The Jira library defaults to no
timeout at all and three silent retries, which together turn one stalled TCP
connection into an unbounded hang. Override with `JIRA_FLOW_REPORT_TIMEOUT`
seconds, or `timeout` in the config file; `0` disables it.

The upstream check is deliberately timid: stderr only, cached for 24 hours, a
four-second timeout, never fatal, and only on commands that already reach the
network. Turn it off entirely with `JIRA_FLOW_REPORT_NO_UPDATE_CHECK=1`, or use
`--offline`.

The banner shows the name, version, build date and commit. It goes to **stderr**,
so it never corrupts a piped `show-config` or a redirected report; suppress it
with `--no-banner` or `JIRA_FLOW_REPORT_NO_BANNER=1`.

## Use

One command for the whole pipeline:

```bash
jira-flow-report report --from 2026-08-10 --to 2026-08-21 \
    --parked-cutoff 2026-08-17 \
    --restrict devops=a.smith,unassigned
```

Writes `snapshot.json`, `report.json`, `flow.html`. Open the HTML, or hand it to
Claude to publish.

### The three steps, separately

The slow step is separated on purpose:

| Step | Command | Network | Deps |
|---|---|---|---|
| 1 | `jira-flow-report collect` | yes | the `jira` package |
| 2 | `jira-flow-report aggregate` | no | **stdlib only** |
| 3 | `jira-flow-report render` | no | **stdlib only** |

```bash
jira-flow-report collect -o snapshot.json
jira-flow-report aggregate -i snapshot.json -o report.json \
    --from 2026-08-10 --to 2026-08-21
jira-flow-report render -i report.json -o flow.html --lang en
```

The snapshot holds **every** status transition plus the stage scale and the alias
map, which buys two things:

- **any window can be re-sliced without refetching** — and two reports built from
  one snapshot agree with each other, which two separate fetches will not, because
  the board moves;
- steps 2 and 3 run **anywhere** — no config, no network, no dependencies. That is
  what makes the report reproducible on a machine that cannot reach Jira at all.

### What gets selected

An issue is in the report if **either** rule matches:

1. it **transitioned into** one of the tracked stages inside the window, per the
   changelog; or
2. it is **still** in the parked column and got there **before**
   `--parked-cutoff`.

Rule 2 is the one that needs a decision. `--parked-cutoff` defaults to `--to`
minus 4 days, which is a guess — the report prints the value it used, and so
should you when you present it.

| Flag | Default | Meaning |
|---|---|---|
| `--from` / `--to` | required | the window, inclusive. `YYYY-MM-DD` or `DD.MM.YYYY` |
| `--parked-cutoff` | `--to` − 4 days | entries on/after this are not "stuck". `none` disables |
| `--restrict LABEL=USER,...` | none | for that label only, keep just these assignees. `unassigned` is valid. Repeatable |
| `--parked` / `--done` | from config | which stage is the queue, which is closed |
| `--stages` / `--track` | from config | the scale, and which transitions select |
| `--labels` | from config | chart categories, in display order |
| `--no-fold-case` | off | treat `devops` and `devOps` as different labels |
| `--lang` | from config | `en` or `ru` |

`--restrict` applies **per label**. An issue tagged both `backend` and `devops`
that fails the `devops` restriction still counts in `backend` — a filter on one
label must not evict issues from another. Everything it drops is listed on the
page.

## Reading the output honestly

The report is designed to be hard to misread, but three things still need saying
out loud when you present it:

- **The stage is the issue's status *now*,** not its status at the end of the
  window. Report a window that closed weeks ago and "% closed" means "closed by
  today". That is a different question from "closed by the end of the window".
- **`--restrict` can invert the picture.** If a label's unclosed work all belongs
  to filtered-out assignees, that label reads 100% closed. Report what the filter
  dropped, not just the percentage.
- **Small labels give meaningless percentages.** Anything under 5 issues is
  flagged on the page. Do not quote "33% closed" off a base of 3.

An issue with several labels is counted in each of them, so the per-label total
can exceed the unique issue count. Statuses outside the configured scale are
prepended to it with a warning rather than dropped, so the charts always sum to
the row count.

## The status-name trap

Jira renders status names through its localisation layer in the REST **fields**
while the **changelog** keeps the underlying English names. The same status can
therefore arrive spelled two ways:

```python
issue.fields.status.name                        # 'Готово'
changelog.histories[-1].items[0].toString       # 'Done'
```

Match on one spelling and you lose every transition of that class **with no
error** — the surviving rows still look plausible. On one real 12-day window this
silently dropped 50 of 129 issues.

Rather than shipping a lookup table, `init` derives the map from the data: an
issue's **last** status transition and its **current** status are by definition
the same status, so pairing them across a few hundred issues recovers the mapping
and flags anything ambiguous. It lands in the snapshot, so the offline steps
inherit it.

## The Claude skill

```bash
jira-flow-report install                     # ~/.claude/skills/jira-flow-report
jira-flow-report install --desktop-zip       # zip for Claude Desktop
```

The skill is **generated from your config**, so its documentation names your
server, board, stage scale and alias map instead of placeholders. In Claude Code:

```
/jira-flow-report 10.08 21.08 --restrict devops=a.smith,unassigned
```

It tells the model how to pick dates, when to reuse an existing snapshot, and
which of the caveats above to repeat in chat. Restart Claude Code after
installing.

For **Claude Desktop**, upload the zip under *Settings → Capabilities → Skills*.
Its `SKILL.md` differs deliberately: if your Jira is only reachable from a private
network, step 1 cannot run in a hosted sandbox, so the Desktop copy documents the
two paths that do work — upload a `snapshot.json`, or pull through a locally
configured Jira MCP connector. Steps 2 and 3 run in the sandbox unchanged, which
is the whole reason they are dependency-free.

## Colour

Stages are an **ordered** scale, so the charts use an ordinal single-hue ramp, not
categorical hues — the further along the scale, the further along the flow. The
5-stage default is validated in both light and dark: monotone lightness, visible
step gaps, and the step nearest the surface still clearing 2:1 contrast. Dark mode
reverses the ramp so the closing stage is the lightest step on a dark ground.

Other stage counts fall back to even spacing over the same ramp. If you change
`--stages`, revalidate.

## Privacy

- The token lives in the environment, never in the config file.
- `snapshot.json`, `report.json` and `*.html` carry real ticket data, summaries
  and usernames. They are in `.gitignore`. Published HTML is a page anyone with
  the link can read — check before sharing.
- Nothing is sent anywhere except your Jira host.

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) covers setup, the four invariants CI enforces,
and what to run before opening a PR. Maintainers: [docs/REVIEWING.md](docs/REVIEWING.md)
for merge criteria, [docs/RELEASING.md](docs/RELEASING.md) for cutting a release.

## Development

```bash
uv sync
uv run pytest              # 88 tests, all offline
uv run ruff check .
uv run ruff format .
uv run jira-flow-report --help
```

Version, build date and commit are baked into `src/jira_flow_report/_build.py` by
a hatchling build hook (`hatch_build.py`); it is generated, gitignored, and
regenerated on every build. Running from a checkout there is no such file, so the
CLI asks git instead and marks the build `+dirty` when the tree is. `uv build`
builds the wheel from a copied sdist where no `.git` exists, so the commit is
carried forward from the sdist stage or taken from `GITHUB_SHA` — CI asserts the
stamp is populated, because an empty one is invisible until someone asks a user
what version they are on.

CI runs exactly those commands, plus a build, across Python 3.11–3.14. Nothing in
the suite touches the network or needs a Jira, so it all runs on a laptop in
under a second.

Three invariants are enforced by tests rather than by review, because each one
fails silently:

- **`aggregate.py` and `render.py` import nothing but the standard library.**
  This is also why the interactive layer (`rich`, `questionary`) lives in
  separate modules: those two files must never grow a dependency.
  Checked by walking their ASTs, by running them as loose scripts, and in CI by
  running them inside a `venv --without-pip`. Break it and the sandbox path stops
  working without any local symptom.
- **The generated skill is valid.** Every `${placeholder}` resolves, the
  frontmatter parses and carries a usable `name`/`description`, the Desktop
  variant keeps only portable keys, the shipped scripts are byte-identical to the
  package copies, and every subcommand and `references/…` path the docs mention
  actually exists. A malformed `SKILL.md` does not error — Claude just silently
  does not load it.
- **No instance data in the tree.** `tests/test_no_instance_data.py` scans every
  tracked file for non-example hostnames, private and CGNAT addresses, real email
  domains and Jira-key-shaped tokens, and asserts snapshots and reports stay
  gitignored. The gate is written generically: an allowlist naming real companies
  would publish the very thing it guards.

If you change `--stages`, revalidate the colour ramp (see **Colour**).

## Releasing

Full procedure in [docs/RELEASING.md](docs/RELEASING.md). Tagging is the whole of it:

```bash
git tag v0.3.0 && git push --tags
```

`release.yml` then checks that the tag matches the project version, runs the full
suite and the linters, builds, verifies the build stamp, publishes to PyPI, and
cuts a GitHub release with the artefacts attached.

Publishing uses [PyPI Trusted
Publishing](https://docs.pypi.org/trusted-publishers/): PyPI verifies the
workflow's OIDC identity, so there is no API token in the repository or its
secrets. The tag/version guard exists because a mismatch is unrecoverable — PyPI
never lets a version number be reused, so publishing `0.2.0` from a tag that says
`v0.3.0` cannot be undone, only yanked.

## Licence

MIT
