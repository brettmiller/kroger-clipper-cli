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
git clone git@github.com:brettmiller/kroger-clipper.git
cd kroger-clipper
uv sync
```

Optionally put it on your `PATH` — the launcher resolves its own symlink, so it
works from anywhere:

```sh
ln -s "$PWD/kroger-clipper" ~/.local/bin/kroger-clipper
```

The examples below use `uv run kroger-clipper`; with the symlink in place, plain
`kroger-clipper` works identically from any directory.

## Use

Sign in once. A real Chrome window opens; sign in by hand and leave it alone.

```sh
uv run kroger-clipper login
```

Then clip:

```sh
uv run kroger-clipper clip                  # clip everything unclipped
uv run kroger-clipper clip --dry-run        # list what would be clipped, clip nothing
uv run kroger-clipper clip --max-clips 20   # stop after 20
uv run kroger-clipper clip --json           # machine-readable summary
uv run kroger-clipper clip --delay 0.2 0.5  # seconds between clips (default 0.2 0.7)
```

`--banner` targets another Kroger-owned chain (`--banner frysfood.com`). Only
`kroger.com` has actually been tested.

Sign-in is required on every `login`, because Kroger's session cookies are
discarded when the browser closes. Your password is never stored by this tool.

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

Note: a session that has *expired* currently exits 3 rather than 2. See
[docs/BACKLOG.md](docs/BACKLOG.md).

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
uv run pytest        # 50 tests, offline, no account needed
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
