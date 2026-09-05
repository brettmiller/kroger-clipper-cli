# Sign in through a self-launched Chrome, attached over CDP

Akamai blocks the Kroger identity provider outright when `navigator.webdriver`
is true, which rules out driving the sign-in with Playwright. Instead, `login`
starts real Google Chrome as an ordinary subprocess with a debugging port and a
dedicated profile, the human signs in, and Playwright attaches over CDP
afterwards purely to read the cookie jar.

`navigator.webdriver` is false in that browser because nothing automated its
launch. No fingerprint is modified and nothing is disguised — the browser is
exactly what it reports itself to be.

## Considered Options

- **Playwright-launched browser** — rejected: measured directly, both an
  unmodified Playwright Chromium and an unmodified real Chrome receive an Akamai
  "Access Denied" at `login.kroger.com`.
- **Suppress the flag with `--disable-blink-features=AutomationControlled`** —
  verified to work, and rejected anyway. It is fingerprint modification, and it
  was avoidable: changing which process launches the browser dissolves the
  problem rather than trading against it.
- **Read cookies from the user's everyday Firefox profile** — viable, since
  Firefox stores cookies unencrypted, but it reaches into an unrelated browser
  profile and breaks when the user changes browsers.
- **Self-launched Chrome plus CDP attach** — chosen.

## Consequences

Chrome must be installed; there is no bundled-browser fallback, and
`KROGER_CLIPPER_CHROME` overrides the search path. Chrome refuses
`--remote-debugging-port` against the default user data directory, so the tool
keeps its own profile under `$XDG_STATE_HOME`. Sign-in completion is detected by
polling page URLs over CDP rather than by awaiting navigation.

## The escalation limit

This is a ceiling, not a first step. If reaching Kroger later requires
suppressing automation flags, a stealth plugin suite, CAPTCHA-solving services,
or rotating or residential proxies — anything whose purpose is defeating bot
detection rather than behaving like an ordinary client — the project stops rather
than escalating. A change crossing that line must supersede this ADR explicitly
and argue the case, not extend it by increments.
