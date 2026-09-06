# kroger-clipper

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `brettmiller/kroger-clipper-cli`, managed with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles, each label string equal to its name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Coding standards

### Fail loudly

The governing invariant: **a run that clipped nothing because the API changed
must never look like a run that clipped nothing because there was nothing to
clip.**

- No bare `except`. No catch-log-continue around structural failures.
- Exactly one class of failure is survivable: an individual coupon failing to
  clip. Log its status code and response body, skip it, continue.
- Everything structural aborts the run — endpoint returning 404, a response
  missing expected fields, zero coupons found where the account should have many.
- Five consecutive clip failures aborts the run. That is not throttling; it means
  something systemic broke and the remaining requests are useless.
- A full card (`TooManyCouponsOnCard`, HTTP 422) ends the run normally with exit
  0. It is a terminal condition, not an error, and it stops on the first
  rejection because every subsequent clip is guaranteed to fail.
- HTTP 429 is honored, not worked around: exponential backoff and retry. Never
  continue issuing requests through explicit backpressure.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success, including a legitimate nothing-to-clip |
| 2 | Session expired — run `login` again |
| 3 | Structural failure; the API changed under us |
| 4 | Rate limited or blocked |

### File locations

Nothing the tool writes at runtime lives in the repository. Paths follow the XDG
base directory spec, with the environment variables honoured when set:

| What | Path |
| --- | --- |
| Session | `${XDG_STATE_HOME:-~/.local/state}/kroger-clipper/session.json` (mode 0600) |
| Browser profile | `${XDG_STATE_HOME:-~/.local/state}/kroger-clipper/browser/` |

There is no configuration file. `paths.config_dir()` exists for one but nothing
reads it — do not document a config file until something does.

`platformdirs` is deliberately not used: on macOS it resolves to
`~/Library/Application Support`, and this project wants the XDG paths on every
platform. The repo's `.gitignore` still lists `config.ini` and `.env` as
defence in depth, but the tool never writes either.

### Output

Human-readable to stdout by default, `--json` for machines, all logging to
stderr. Suppress colour and spinners when stdout is not a TTY.

### Test fixtures

Fixtures are scrubbed at capture time and the scrubber **allowlists** fields —
it keeps only what it recognizes and refuses to write a fixture containing an
unrecognized field. A denylist would leak the first new field Kroger adds. Raw
captures stay in `tests/captures/` and are gitignored; scrubbed fixtures in
`tests/fixtures/` are committed.

This repository is public. Treat every committed fixture as world-readable.
