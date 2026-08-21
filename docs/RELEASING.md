<!-- Kept in the tree on purpose: this is the procedure for the code in this
repository, so it is versioned alongside it. .claude/commands/release.md (local, untracked) is a
pointer to this file. -->

# Releasing

Releasing is a tag. Everything else is CI. The job of this runbook is to make
sure the tag is one you can live with, because **a published version can never be
replaced** — PyPI refuses to reuse a version number. A bad release can only be
yanked, and a yank still leaves the file downloadable by exact version.

## 1. Preconditions

```bash
cd ~/github/jira-flow-report
git switch main && git pull
git status --short          # must be empty
```

Do not release from a dirty tree or a detached HEAD. If `git status` shows
anything, decide whether it belongs in the release and commit it first.

## 2. Pick the number

Semver, judged by what changed since the last tag:

```bash
git log --oneline "$(git describe --tags --abbrev=0)"..HEAD
```

| Change | Bump |
|---|---|
| a behaviour someone relied on now differs — CLI flags, snapshot/report JSON shape, config keys | **major** |
| new command, new flag, new discovery, anything additive | **minor** |
| fix, docs, internals, dependency bump | **patch** |

The snapshot and report JSON are a public interface: the offline steps read
snapshots produced by other people's tooling, and the schema is documented in
`references/snapshot-schema.md`. Changing a field name there is a major bump, not
a patch. Bump `schema` in the payload at the same time.

## 3. Bump and verify

Edit `version` in `pyproject.toml`, then refresh the lockfile — it records the
project's own version, so the bump makes it stale and `uv lock --check` will fail
until you do:

```bash
uv lock
```

Now run exactly what CI runs, so a failure costs seconds instead of a burnt
version number:

```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pytest
rm -rf dist && uv build && uvx twine check --strict dist/* && rm -rf dist
```

All five must pass. `test_packaging.py` covers the metadata rules that PyPI
rejects rather than warns about; if it fails, fix it now — that is the whole
reason it exists.

Commit the bump on its own:

```bash
git add pyproject.toml uv.lock && git commit -m "Release <version>" && git push
```

## 4. Tag

The tag must match `pyproject.toml` exactly, `v` prefix included. CI checks this
in its first job and refuses to build otherwise — that guard exists because
publishing `0.2.0` from a tag reading `v0.3.0` is unrecoverable.

```bash
git tag -a v<version> -m "v<version>

<a few lines on what changed and why anyone should care>"
git push origin v<version>
```

## 5. Watch it land

```bash
gh run watch "$(gh run list --workflow=release.yml --limit 1 --json databaseId -q '.[0].databaseId')" --exit-status
```

Four jobs: verify the tag and the tree → build → publish to PyPI → GitHub
release. Publishing uses PyPI Trusted Publishing, so there is no token to rotate
or leak; PyPI verifies the workflow's OIDC identity instead.

## 6. Confirm from the outside

Do not trust a green check. Install it the way a stranger would:

```bash
curl -s https://pypi.org/pypi/jira-flow-report/json | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["info"]; print(d["name"], d["version"])'

export UV_TOOL_DIR=$(mktemp -d) UV_TOOL_BIN_DIR=$(mktemp -d)
uv tool install jira-flow-report && "$UV_TOOL_BIN_DIR/jira-flow-report" --version
unset UV_TOOL_DIR UV_TOOL_BIN_DIR
```

The version line should carry the build date and the commit. An empty commit or
an unknown build date means the build hook did not run and the wheel is missing
its stamp — worth a patch release, since the CLI then cannot tell anyone what it
is.

Check the wheel still carries what it needs, since this is the failure that only
appears once installed rather than run from a checkout:

```bash
python3 -c "
import jira_flow_report, pathlib
d = pathlib.Path(jira_flow_report.__file__).parent
print('templates:', [p.name for p in (d/'skill').rglob('*.tmpl')])
print('stamp    :', (d/'_build.py').exists())"
```

## 7. Afterwards

Update the local install and regenerate the skill, or `status` will keep
reporting the old version as current:

```bash
uv tool install --force jira-flow-report
jira-flow-report update
```

## When it goes wrong

- **Workflow failed before the publish job** — nothing was uploaded. Delete the
  tag (`git tag -d v<v> && git push --delete origin v<v>`), fix, tag again.
- **Publish job failed halfway** — check PyPI before retrying. If the version is
  there, it is spent; bump to the next patch rather than trying to overwrite.
- **Published something broken** — `yank` it on PyPI so resolvers skip it, then
  release a fix. Do not delete the release: deletion frees nothing, and anyone
  pinned to that exact version gets a broken install instead of a clear error.
- **Trusted publishing rejected** — the pending publisher on pypi.org must match
  owner `ya-makariy`, repo `jira-flow-report`, workflow `release.yml`, and an
  **empty** environment name, because the workflow declares no environment.
