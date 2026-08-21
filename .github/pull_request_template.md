## What and why

<!-- What changes, and the failure mode it prevents or the need it serves. -->

## Checks

Run locally (about a second — the suite is offline and needs no Jira):

- [ ] `uv lock --check`
- [ ] `uv run ruff check .`
- [ ] `uv run ruff format .`
- [ ] `uv run pytest` — with new files **staged**, since one test reads `git ls-files`

## Invariants this touches

<!-- Tick anything relevant; see CONTRIBUTING.md. -->

- [ ] adds an import to `aggregate.py` or `render.py` — these must stay stdlib-only
- [ ] widens `ALLOWED_HOSTS` / `ALLOWED_KEYS` in `tests/test_no_instance_data.py`
- [ ] changes a `skill/*.tmpl` template
- [ ] changes the snapshot or report JSON shape — **needs a `schema` bump**
- [ ] changes a CLI flag, subcommand, or config key
- [ ] adds a prompt — resolves to a default with no TTY, and has a flag
- [ ] adds a runtime dependency

## Tests

- [ ] new behaviour has a test
- [ ] a bug fix includes the case that was broken
