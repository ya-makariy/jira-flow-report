# Contributing

Thanks for looking. This is a small tool with a few load-bearing invariants; if a
change respects them it is usually easy to merge.

## Setup

```bash
git clone https://github.com/ya-makariy/jira-flow-report && cd jira-flow-report
uv sync
uv run jira-flow-report --help
```

Python 3.11+ and [uv](https://docs.astral.sh/uv/). Nothing else, and no Jira
access: the whole test suite is offline.

## Before you open a PR

Run what CI runs. It takes about a second:

```bash
uv lock --check                 # the lockfile matches pyproject.toml
uv run ruff check .
uv run ruff format .
uv run pytest
```

If you touched packaging, add:

```bash
uv build && uvx twine check --strict dist/*
```

Stage your files before running the suite. One of the tests reads `git ls-files`,
so an unstaged new file is invisible to it — and that is exactly how a leak would
slip through.

## The four invariants

CI enforces all of these. They are not style preferences; each one fails silently
in production, which is why they are tests rather than review notes.

**1. `aggregate.py` and `render.py` import nothing but the standard library.**
They must run in a sandbox with no packages installed and no network — that is
what lets someone produce a report on a machine that cannot reach Jira at all. If
you need a library, put the code in another module. The interactive layer
(`rich`, `questionary`) lives in `ui.py` and `prompts.py` for this reason.

**2. Nothing about a particular Jira in the tree.** No hostnames beyond
`example.com`, no private or CGNAT addresses, no real email domains, no real
project keys. Everything instance-specific comes from
`~/.config/jira-flow-report/config.toml` or is discovered from the API at `init`
time. `tests/test_no_instance_data.py` scans every tracked file.

**3. The generated skill has to stay valid.** `SKILL.md` is rendered from
`skill/*.tmpl`. A malformed one does not raise — Claude simply does not load it,
or loads it and follows stale instructions. If you change a template, add or
adjust the assertions in `tests/test_skill.py`.

**4. Status names are never hardcoded.** The changelog and the REST fields can
spell the same status differently, and which one is localised varies by instance.
The mapping is discovered at `init` and travels inside the snapshot. Do not add a
lookup table, and do not put a status name in JQL.

## Style

`ruff` decides formatting and lint; the config is pinned in `pyproject.toml` so
it cannot drift with a ruff release. Beyond that:

- comments explain *why*, not *what* — the code says what;
- prefer a named function to a clever expression, especially in the offline pair
  where there is no library to hide behind;
- error messages say what went wrong **and** the next command to run;
- output that is chrome goes to stderr, so stdout stays pipeable.

## Tests

New behaviour needs a test, and the useful ones here assert something that would
otherwise fail quietly. Fixtures are synthetic — `tests/test_pipeline.py` builds
snapshots inline; there is no recorded Jira traffic and nothing hits the network.

If you fix a bug, add the case that was broken. Every regression test in this
repository corresponds to something that shipped wrong once.

## Commits and PRs

Say what changed and why it matters. A commit body explaining the failure mode a
change prevents is worth more than a tidy subject line.

Keep a PR to one concern. Two unrelated fixes in one branch means neither can be
reverted independently.

## Releases

Maintainers only, and it is just a tag — see [docs/RELEASING.md](docs/RELEASING.md).
