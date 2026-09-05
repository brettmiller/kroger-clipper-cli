# Backlog

State as of 2026-09-05. The tool works end to end: `login` captures a session,
`clip` enumerated 266 coupons and clipped 250 before hitting Kroger's per-card
limit. What follows is what is knowingly incomplete.

Ordered by what would bite first.

## Defects

### Exit code 2 is unreachable for an expired session

`CLAUDE.md` documents exit 2 as "session expired — run `login` again", but
nothing produces it in that case. `SessionMissing` is raised only when the
session *file is absent*. An expired session — file present, cookies stale —
reaches `coupons._fetch`, returns a non-200, and becomes a `StructuralError`,
which exits 3. So a routine re-auth is indistinguishable from "Kroger changed
their API", which is precisely the confusion the exit codes exist to prevent.

Fixing it needs an observation first: nobody has seen what this API returns for a
stale session. It could be 401, 403, or a 200 carrying an HTML sign-in page. Once
known, map it to `SessionMissing` (or a new `SessionExpired`) in `transport` so
both `clip` paths inherit it.

### A long run gives no progress output

Successful clips print nothing, so a 250-coupon run emits one line and then goes
quiet for four minutes. There is no way to tell working from hung. Failures
print immediately, so the silence is *technically* informative, but it is a mild
version of the sin this project was built to avoid.

Print a counter when stdout is a TTY; stay silent when it is not, per the output
contract.

## Testing gaps

### The fixture scrubber does not exist

This is the largest gap against what was agreed. All 50 tests run against
hand-written stubs, so nothing pins parsing to a *real* Kroger payload — a change
in their response shape would not fail a single test.

What was agreed (see the Q11/Q16 decisions):

- A capture mode that records real responses.
- A scrubber that **allowlists** fields: it keeps only what it recognises and
  refuses to write a fixture containing an unrecognised field. A denylist would
  leak the first new field Kroger adds.
- Tests for the scrubber itself, asserting both that known PII is removed *and*
  that an unrecognised field fails closed.
- Raw captures under `tests/captures/` (gitignored); scrubbed fixtures under
  `tests/fixtures/` (committed).

The scrubber must handle `x-laf-object`, which embeds the store's street address,
and the facility id, which identifies where the account shops. Both are already
excluded from the repo by hand; the scrubber should make that automatic.

### `transport.build()` is untested

Cookie loading, domain defaulting, and header merging have no coverage. It is
also the one module where a mistake is silent — a dropped cookie looks like an
auth failure, not a bug.

### `paths.config_dir()` is dead code

Nothing reads a configuration file; the function is exercised only by its own
tests. Either add config-file support or delete it. It was briefly documented in
`CLAUDE.md` as though it existed.

### No CLI-level tests

Exit codes and `--json` output shape are asserted nowhere, despite being the
documented interface for scheduled use.

## Unknowns needing observation

- **Pacing at 0.2-0.7s is unvalidated.** The one clean full run used 0.3-1.0s.
  The card filled at 250 before the faster rate could be exercised. The first
  real test is whenever enough coupons expire to leave room.
- **What `clip-unclip` returns for an already-clipped or expired coupon.**
  Never observed, because `filter.status=unclipped` means we never ask.
- **How long a session lasts.** Unknown; it determines whether weekly runs keep
  it alive, which ADR-0002 assumes.
- **Akamai cookie lifetime**, and therefore whether `login` will eventually need
  re-warming more often than expected.

## Deferred by decision, not oversight

- **Cash-back offers.** Scope was deliberately limited to digital coupons. The
  API exposes them via `filter.type=cash_back`, and `CONTEXT.md` already keeps
  them as a separate term so adding them widens scope explicitly rather than
  quietly.
- **Category or value filtering.** Clipping everything is free and filtering by
  value is impossible anyway — the compact projection has no numeric discount
  field, only prose. If wanted, it is a `filter.category` parameter, not a
  parser.
- **Unattended scheduling.** ADR-0002 records why authentication is interactive
  only, and what revisiting it would cost.
- **Banners other than kroger.com.** `--banner` exists and is threaded through,
  but has never been run against Ralphs, Fry's, or others.

## Housekeeping

- **No licence.** A public repo with no `LICENSE` file is all-rights-reserved by
  default, which is probably not the intent.
- **No CI.** Tests are fast and offline, so this is cheap to add — but it depends
  on committed fixtures existing first.
- **Playwright's bundled Chromium (~290MB) is unused.** `login` drives real
  Chrome; only the `playwright` library is needed, for CDP. `playwright
  uninstall chromium` reclaims the space.
- **Triage labels do not exist on the GitHub repo.** `docs/agents/triage-labels.md`
  declares five; `/triage` would create them on first run.

## Outside the repo

- **Rotate the Kroger account password.** It was exposed in an assistant
  transcript on 2026-09-05 when a config file from the previous project was
  dumped.
- **Nothing has been pushed.** All commits are local only.
