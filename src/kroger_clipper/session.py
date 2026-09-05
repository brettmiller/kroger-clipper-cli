import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from . import paths

SIGNIN_TIMEOUT_S = 300
POLL_INTERVAL_S = 2
CHROME_READY_TIMEOUT_S = 30

COUPONS_PAGE = "/savings/cl/coupons/"
COUPONS_API = "/atlas/v1/savings-coupons/"
WARM_SETTLE_MS = 12000

# Captured from the page's own request rather than reconstructed. Telemetry
# headers (traceparent, x-dtpc, x-ab-test, x-call-origin) are deliberately not
# kept: replaying a stale trace id is worse than sending none.
CONTEXT_HEADERS = (
    "x-facility-id",
    "x-laf-object",
    "x-modality",
    "x-modality-type",
    "x-kroger-channel",
    "user-agent",
)
# The old kroger-cli probed /accountmanagement/api/profile; it now returns 404.
# Probe the endpoint we actually depend on instead, so a green login means something.
PROBE_PATH = (
    "/atlas/v1/savings-coupons/v1/coupons"
    "?projections=coupons.compact&filter.status=unclipped&page.size=1&page.offset=0"
)

_SIGNIN_MARKERS = ("/signin", "/login")

_CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "google-chrome-stable",
)


class SessionMissing(Exception):
    pass


class SignInAbandoned(Exception):
    pass


class ChromeNotFound(Exception):
    pass


class Blocked(Exception):
    pass


def login(banner: str) -> dict:
    """Launch Chrome so a human can sign in, then attach only to read the Session.

    Chrome is started as an ordinary subprocess rather than driven by Playwright.
    That keeps navigator.webdriver false without modifying anything: nothing
    automated the launch, so there is nothing to misreport. See docs/adr/0003.
    """
    base = f"https://www.{banner}"
    profile_dir = paths.browser_dir()
    profile_dir.mkdir(parents=True, exist_ok=True)

    port = _free_port()
    proc = _launch_chrome(_chrome_binary(), port, profile_dir, f"{base}/signin")
    try:
        _await_chrome(port, proc)
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            ctx = browser.contexts[0]
            page = _wait_for_signin(ctx, base)

            # Signing in costs a human their attention, so bank it before doing
            # anything else. Everything below is enrichment and must not be able
            # to discard a session that was already established.
            state = _scope_state(ctx.storage_state(), banner)
            _write_session(state)

            # Akamai mints its cookies on a real page load, so a jar captured
            # after one is worth more — but only overwrite on success.
            warm = _warm(page, base)
            probe = _probe(page, warm["headers"]) if warm["ok"] else None
            if warm["ok"]:
                state = _scope_state(ctx.storage_state(), banner)
                _write_session(state, warm["headers"])
            browser.close()
    finally:
        _stop(proc)

    return {
        "session_file": str(paths.session_file()),
        "cookies": sorted({c["name"] for c in state.get("cookies", [])}),
        "warm": warm,
        "probe": probe,
        "context_headers": sorted(warm["headers"]),
    }


def _scope_state(state: dict, banner: str) -> dict:
    """Keep only the banner's own cookies.

    storage_state() returns every domain the browser touched, which drags in
    unrelated third-party cookies. Persisting someone else's credentials is a
    liability we get nothing for.
    """
    kept = [c for c in state.get("cookies", []) if c.get("domain", "").lstrip(".").endswith(banner)]
    return {**state, "cookies": kept}


def _warm(page, base: str) -> dict:
    """Load the coupons page, then keep the store headers the SPA itself sent.

    The store context is not reconstructed from the modality endpoint: the page
    already builds it, and observing one real request is both simpler and more
    faithful than deriving it ourselves.
    """
    captured: dict[str, str] = {}

    def on_request(req):
        if captured or COUPONS_API not in req.url:
            return
        # This runs on the event loop, so anything raised here escapes as an
        # unhandled callback error rather than failing the run. all_headers()
        # round-trips to a browser that may already be closing.
        try:
            headers = req.all_headers()
        except PlaywrightError:
            headers = req.headers
        captured.update({k: v for k, v in headers.items() if k in CONTEXT_HEADERS})

    page.on("request", on_request)
    try:
        page.goto(base + COUPONS_PAGE, wait_until="domcontentloaded")
        page.wait_for_timeout(WARM_SETTLE_MS)
        body = page.content()
    except PlaywrightError as exc:
        return {"ok": False, "detail": exc.__class__.__name__, "headers": {}}
    finally:
        page.remove_listener("request", on_request)

    if "Too many requests" in body:
        return {"ok": False, "detail": "rate limited", "headers": {}}
    if "Access Denied" in body or "edgesuite" in body:
        return {"ok": False, "detail": "blocked", "headers": {}}
    if not captured:
        return {"ok": False, "detail": "page made no coupons request", "headers": {}}
    return {"ok": True, "detail": "ok", "headers": captured}


def _chrome_binary() -> str:
    override = os.environ.get("KROGER_CLIPPER_CHROME")
    candidates = (override, *_CHROME_CANDIDATES) if override else _CHROME_CANDIDATES
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    raise ChromeNotFound("no Google Chrome found; set KROGER_CLIPPER_CHROME to its path")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _launch_chrome(binary: str, port: int, profile_dir: Path, url: str) -> subprocess.Popen:
    # A dedicated profile is not optional: Chrome refuses --remote-debugging-port
    # against the default user data directory.
    return subprocess.Popen(
        [
            binary,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _await_chrome(port: int, proc: subprocess.Popen) -> None:
    deadline = time.monotonic() + CHROME_READY_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SignInAbandoned(f"Chrome exited immediately (status {proc.returncode})")
        if _cdp_ready(port):
            return
        time.sleep(0.25)
    raise SignInAbandoned(f"Chrome did not open a debugging port within {CHROME_READY_TIMEOUT_S}s")


def _cdp_ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1):
            return True
    except (urllib.error.URLError, OSError):
        return False


def _wait_for_signin(ctx, base: str):
    deadline = time.monotonic() + SIGNIN_TIMEOUT_S
    while time.monotonic() < deadline:
        for page in ctx.pages:
            try:
                url = page.url
            except PlaywrightError:
                continue
            # A block renders on the identity provider's own URL, so without this
            # the loop would poll past a plainly visible answer until it timed out.
            blocked = _blocked_reason(page)
            if blocked:
                raise Blocked(blocked)
            if url.startswith(base) and not any(m in url for m in _SIGNIN_MARKERS):
                return page
        time.sleep(POLL_INTERVAL_S)
    raise SignInAbandoned(f"no sign-in detected within {SIGNIN_TIMEOUT_S}s")


def _blocked_reason(page) -> str | None:
    try:
        body = page.content()
    except PlaywrightError:
        return None
    if "Too many requests" in body:
        return "rate limited"
    if "Access Denied" in body or "edgesuite" in body:
        return "blocked"
    return None


def _probe(page, headers: dict) -> dict:
    """Prove the captured headers actually work, using the endpoint clip depends on."""
    try:
        return page.evaluate(
            """async ({path, headers}) => {
                const r = await fetch(path, {
                    credentials: 'include',
                    headers: {accept: 'application/json', ...headers},
                });
                return {status: r.status, ok: r.ok};
            }""",
            {"path": PROBE_PATH, "headers": headers},
        )
    except PlaywrightError as exc:
        return {"status": None, "ok": False, "error": exc.__class__.__name__}


def _stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def _write_session(state: dict, headers: dict | None = None) -> None:
    path = paths.session_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump({"storage_state": state, "context_headers": headers or {}}, fh)
    os.chmod(path, 0o600)  # O_CREAT mode does not apply to a pre-existing file


def load_session() -> dict:
    path: Path = paths.session_file()
    if not path.exists():
        raise SessionMissing(f"no session at {path}")
    return json.loads(path.read_text())
