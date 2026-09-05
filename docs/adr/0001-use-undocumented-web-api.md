# Use kroger.com's undocumented web API, not the public developer API

Kroger's public developer API (developer.kroger.com) exposes Products,
Locations, Cart, and Identity — and no coupon endpoints whatsoever, in any tier
we can access. Clipping is therefore only reachable through the same
undocumented `/atlas/v1/savings-coupons/` endpoints that kroger.com's own
frontend calls, authenticated with ordinary session cookies.

## Considered Options

- **Public developer API** — rejected: it cannot clip coupons. This is not a
  preference; the capability does not exist.
- **DOM automation** (drive a browser and click Clip buttons) — rejected: this is
  what the previously forked tool did, and its selectors and button-label string
  matching broke on essentially every Kroger frontend release.
- **Undocumented JSON API** — chosen: structured responses, real pagination, an
  explicit `addedToCard` already-clipped flag, and a surface that changes far
  more slowly than presentation markup.

## Consequences

Kroger sits behind Akamai Bot Manager, which blocks at the TLS fingerprint layer
before returning any HTTP status — a stock Python HTTP client cannot reach these
endpoints at all, regardless of cookies. Requests must therefore carry a
browser-shaped TLS fingerprint, which is why HTTP transport is isolated behind
its own module rather than being a bare `httpx` call at each call site.

This API is undocumented and unsupported. It will break without notice. The
design goal is not to prevent that but to make it unmistakable when it happens —
see the fail-loudly rules in `CLAUDE.md`.
