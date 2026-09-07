# kroger-clipper

Clip Kroger digital coupons from the command line, so the savings are already on
your card before you get to the store.

> **This uses Kroger's undocumented internal web API.** There is no public
> coupon API — Kroger's developer platform offers Products, Locations, Cart and
> Identity, and nothing for coupons. That means this tool works by talking to
> the same endpoints kroger.com's own frontend uses. It is unsupported, it will
> break without warning, and automated access is very likely contrary to
> Kroger's terms of service. It operates on one account, with that account
> holder's own credentials. Decide for yourself whether that trade is one you
> want to make.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Google Chrome (used for sign-in only; there is no bundled-browser fallback)

## Install

```sh
git clone git@github.com:brettmiller/kroger-clipper-cli.git
cd kroger-clipper-cli
uv tool install --editable .
```

That puts `kroger-clipper` on your `PATH` and, because the install is editable,
it keeps running whatever is in the working tree — no reinstall after a change.
Remove it with `uv tool uninstall kroger-clipper-cli` — the distribution is
`kroger-clipper-cli` even though the command it installs is `kroger-clipper`.

To run it without installing anything, `uv sync` and then prefix the commands
below with `uv run`.

## Use

Sign in once. A real Chrome window opens; sign in by hand and leave it alone.

```sh
kroger-clipper login
```

Then clip:

```sh
kroger-clipper clip                  # clip everything unclipped
kroger-clipper clip --dry-run        # list what would be clipped, clip nothing
kroger-clipper clip --max-clips 20   # stop after 20
kroger-clipper clip --json           # machine-readable summary
kroger-clipper clip --delay 0.2 0.5  # seconds between clips (default 0.2 0.7)
```

### Removing coupons

```sh
kroger-clipper unclip --dry-run                  # what is on the card
kroger-clipper unclip --department Beer          # remove just those
kroger-clipper unclip --limit 5                  # stop after 5
kroger-clipper unclip --yes                      # skip the confirmation
```

`unclip` takes every option `clip` does — the filters below, plus `--dry-run`,
`--delay`, `--json` and `--list-filters` — and asks before removing anything.
Useful because the card holds only 250 coupons: what is already on it decides
what will fit.

Note the flag is `--limit` here and `--max-clips` on `clip`. Removing 250 coupons
is 250 requests and about four minutes, so `--dry-run` or a small `--limit` is
the cheap way to start.

### Filtering

Kroger's site filters by "Departments" and "Ways to shop"; both are available
here on both commands, applied locally to the coupons already fetched:

```sh
kroger-clipper clip --list-filters                    # what exists, with counts
kroger-clipper clip --department Dairy,Bakery         # only these
kroger-clipper clip --exclude-department Beer,Wine    # skip these
kroger-clipper clip --ways-to-shop IN_STORE,PICKUP
```

Values are comma-separated; passing an option more than once works too, and the
two can be mixed.

Department names contain spaces and `&`, which the shell would otherwise treat as
a command separator. **Quote the whole comma-separated list once** — the split on
commas happens after the shell is finished with it:

```sh
kroger-clipper clip --department "Health & Beauty,Meat & Seafood"
```

Quoting each name separately (`"Health & Beauty","Meat & Seafood"`) also works,
but only because the shell joins adjacent quoted strings into one word — it is
the same single argument, not two. Repeating the option is the explicit
alternative:

```sh
kroger-clipper clip --department "Health & Beauty" --department "Meat & Seafood"
```

`--list-filters` prints the values exactly as Kroger spells them, so its output
can be pasted straight back. "General" is one of Kroger's real departments, not a
stand-in for a missing value.

Values within one option are OR-ed (Dairy *or* Bakery); different options are
AND-ed (in that department *and* available that way to shop). Names are matched
case-insensitively. Filtering happens on this side rather than
through the API's own `filter.category`, which answers HTTP 500 for a department
that is not stocked at your store — a typo would fail the run instead of matching
nothing. Pair any of these with `--dry-run` to see what would be clipped.

### Sessions

Sign-in is required on every `login`, because Kroger's session cookies are
discarded when the browser closes. Your password is never stored by this tool.

Sessions do not last long — under about 16 hours in practice. If `clip` or
`unclip` finds the session stale it offers to sign you in again and then retries,
but only when you are at a terminal. Run unattended it exits instead, so a
scheduled job never opens a browser nobody will see.

### Other banners

`--banner` targets another Kroger-owned chain (`--banner frysfood.com`). Only
`kroger.com` has actually been tested.

## What to expect

- **Kroger caps a card at 250 coupons.** When the card is full, the run stops on
  the first rejection and exits 0 — a full card is a normal end to a run, not an
  error.
- **Re-running is safe and cheap.** Only unclipped coupons are requested, so
  already-clipped ones cost nothing.
- **A full run takes about 4-5 minutes.** Clipping is one request per coupon;
  there is no batch endpoint, and the requests are deliberately paced.
- **Only digital coupons.** Cash-back offers are a different thing and are out
  of scope.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success, including a full card or nothing to clip |
| 2 | No session — run `login` |
| 3 | Something structural: the API did not look as expected |
| 4 | Rate limited or blocked; wait before retrying |

An expired session exits 2, the same as a missing one: both are fixed by signing
in again, not by investigating the API.

## Files

Nothing sensitive is written inside the repository.

| What | Where |
| --- | --- |
| Session (cookies + store headers) | `${XDG_STATE_HOME:-~/.local/state}/kroger-clipper/session.json`, mode 0600 |
| Chrome profile for sign-in | `${XDG_STATE_HOME:-~/.local/state}/kroger-clipper/browser/` |

There is no configuration file; everything is a command-line option.

## How it works

`login` starts Chrome as an ordinary subprocess with a debugging port, waits for
you to sign in, then attaches over CDP purely to read the cookie jar. Chrome is
not driven by automation, so `navigator.webdriver` is false without anything
being disguised — which matters, because Akamai refuses automated browsers at
Kroger's identity provider.

While the coupons page loads, `login` also records the store-context headers the
page sends for itself (`x-laf-object`, `x-facility-id`, `x-modality`), rather
than trying to reconstruct them.

`clip` then needs no browser at all. It replays those cookies and headers over
HTTP with a browser-shaped TLS fingerprint, because a stock Python client is
dropped at the Akamai edge before any HTTP status comes back.

## Development

```sh
uv run pytest        # offline, no account needed
uv run ruff check .
uv run ruff format .
```

Design decisions live in [docs/adr/](docs/adr/), the reverse-engineered API is
documented in [docs/research/kroger-internal-api.md](docs/research/kroger-internal-api.md),
project vocabulary in [CONTEXT.md](CONTEXT.md), and known gaps in
[docs/BACKLOG.md](docs/BACKLOG.md).

## Licence

MIT. See [LICENSE](LICENSE).

## Prior art

[Shmakov/kroger-cli](https://github.com/Shmakov/kroger-cli) does the same job by
driving a browser and clicking Clip buttons. This project was written from
scratch after that approach proved too brittle to maintain: DOM selectors and
button-label text change with every frontend release, whereas the JSON API
underneath changes far more slowly.
