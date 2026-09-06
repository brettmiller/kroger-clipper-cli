# Backlog

State as of 2026-09-05. The tool works end to end: `login` captures a session,
`clip` enumerated 266 coupons and clipped 250 before hitting Kroger's per-card
limit. What follows is what is knowingly incomplete.

Fixed since the first draft: the unreachable exit code 2, missing progress
output, the untested `transport.build()`, the absent CLI tests, and the dead
`paths.config_dir()`. The fixture scrubber now exists; only the capture itself is
outstanding.

Ordered by what would bite first.

## Open

### No real captured fixture yet

The scrubber and a hidden `capture` command exist and are tested, but no real
response has been recorded — the account was rate limited when the work was done.
When it clears:

```sh
kroger-clipper capture
```

That writes the raw response to `tests/captures/` (gitignored) and a scrubbed
copy to `tests/fixtures/coupons_page.json` (committed). If Kroger has added a
field the allowlist does not know, it will refuse to write the fixture and name
the field — which is the design working, not a bug. Once the fixture exists, add
a test that runs it through `list_unclipped`'s parsing so a response-shape change
fails the suite.

## Unknowns needing observation

- **Pacing at 0.2-0.7s is unvalidated.** The one clean full run used 0.3-1.0s.
  The card filled at 250 before the faster rate could be exercised. The first
  real test is whenever enough coupons expire to leave room.
- **What `clip-unclip` returns for an already-clipped or expired coupon.**
  Never observed, because `filter.status=unclipped` means we never ask.
- **How long a session lasts.** Under ~16 hours, measured once. This undercuts
  ADR-0002's assumption that weekly runs would keep a session warm - in practice
  `login` will be needed before most runs.
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
