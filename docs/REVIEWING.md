# Reviewing and merging a PR

What has to be green, and what green does not tell you.

## Required: every CI job

`ci.yml` runs four jobs on each PR. All must pass — none of them is advisory.

| Job | What a failure means |
|---|---|
| **lint & format** | `uv lock --check`, `ruff check`, `ruff format --check`. A lockfile failure usually means `pyproject.toml` was edited without re-running `uv lock` |
| **test (py3.11 … 3.14)** | The suite on every version the package claims to support. A single-version failure is real, not flaky — there is no network and no clock dependence in these tests |
| **offline scripts on a bare interpreter** | `aggregate.py` / `render.py` were run inside a `venv --without-pip`. A failure means one of them grew an import and the sandbox path is broken |
| **package** | Builds, `twine check --strict`, the build stamp is baked in, the skill templates are inside the wheel, and a skill can be generated from that wheel |

If a contributor's fork cannot run CI, do not merge on inspection alone. Push the
branch to this repository and let CI run, or run the four local commands from
[CONTRIBUTING.md](../CONTRIBUTING.md) against their branch yourself.

## Not covered by CI — read these yourself

CI proves the code runs. It cannot judge these.

**Did an interface change without a version consequence?** The snapshot and
report JSON are public: the offline steps consume snapshots other tooling
produces, and the shape is documented in `references/snapshot-schema.md`. A
renamed or removed field is a **major** bump, and the `schema` number in the
payload should move with it. Same for CLI flags and config keys.

**Does the generated skill still say something true?** Templates in `skill/` are
prose that a model acts on. `tests/test_skill.py` checks that placeholders
resolve and the frontmatter parses — it cannot check that the instructions are
still accurate. If the PR changes behaviour the skill describes, the template
needed changing too.

**Did the instance-data gate get widened?** An addition to `ALLOWED_HOSTS`,
`ALLOWED_KEYS` or `NOT_TICKET_KEYS` in `tests/test_no_instance_data.py` is the
one change that makes the guard weaker. Each entry should be a generic example
(`example.com`, `ABC-123`) or a public infrastructure host — never a real
company's domain or a real project key.

**Is a new prompt usable without a terminal?** Every prompt must resolve to a
stated default when there is no TTY, and print what it chose. A prompt that
blocks turns any script or agent run into a hang. There should be a flag for it
too.

**Does new output go to the right stream?** Anything that is not data belongs on
stderr. `show-config` and the report steps get piped.

**Is a new dependency worth it?** Runtime dependencies are a cost for every
installer. They are also forbidden outright in the offline pair — check which
module the import landed in.

## Before merging

- Every job green, and the diff is what the PR description says it is.
- Behaviour change → a test that fails without the fix.
- Bug fix → the regression case, not just a corrected implementation.
- Interface change → decide the bump now and say so in the PR, so whoever
  releases next does not have to reconstruct it.
- Docs match: `README.md` for users, `CONTRIBUTING.md` for contributors, the
  `skill/` templates for the model.

Squash unless the individual commits each tell a story worth keeping. Keep the
body of the message — the reasoning is the part that is expensive to recover.

## Enforcing it

The check names above are advisory until branch protection requires them.
To require them on `main`:

```bash
gh api -X PUT repos/ya-makariy/jira-flow-report/branches/main/protection \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "lint & format",
      "test (py3.11)", "test (py3.12)", "test (py3.13)", "test (py3.14)",
      "offline scripts on a bare interpreter",
      "package"
    ]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
JSON
```

`enforce_admins: false` deliberately: it keeps direct pushes to `main` possible
for the maintainer. Set it to `true` once the flow is PR-only, and be aware that
it then applies to you as well.
