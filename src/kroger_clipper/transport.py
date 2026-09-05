from curl_cffi import requests

from . import session
from .errors import Blocked, SessionExpired, StructuralError

# A stock Python TLS fingerprint is dropped at the Akamai edge before any HTTP
# status comes back, so the client has to look like the browser we logged in
# with. See docs/adr/0001. "chrome" tracks the newest profile curl_cffi ships.
IMPERSONATE = "chrome"
TIMEOUT_S = 30

# cpr_chlge is Akamai's rate-limit challenge body. It arrives with a 429 today,
# but matching the body too costs nothing if that ever changes.
_BLOCK_MARKERS = ("Too many requests", "Access Denied", "edgesuite", "cpr_chlge")

# Observed: an unauthenticated clip returns 401 with this code. Enumeration is
# anonymous, so this is the only place a dead session actually shows up.
AUTH_REQUIRED_CODE = "AUTH_REQUIRED"


def build(banner: str) -> requests.Session:
    """An HTTP client carrying the cookies and store headers login captured."""
    saved = session.load_session()
    headers = saved.get("context_headers") or {}
    if not headers:
        raise StructuralError("session has no store headers — run `kroger-clipper login` again")

    http = requests.Session(impersonate=IMPERSONATE, timeout=TIMEOUT_S)
    for cookie in saved.get("storage_state", {}).get("cookies", []):
        http.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain", f".{banner}"),
            path=cookie.get("path", "/"),
        )
    http.headers.update(headers)
    http.headers.update(
        {
            "accept": "application/json, text/plain, */*",
            "referer": f"https://www.{banner}/savings/cl/coupons/",
        }
    )
    return http


def raise_for_auth(resp) -> None:
    """A stale session is a routine re-login, not a structural surprise."""
    if resp.status_code == 401 or AUTH_REQUIRED_CODE in (resp.text or "")[:500]:
        raise SessionExpired("Kroger rejected the session")


def rate_limited(resp) -> bool:
    return resp.status_code == 429


def denial(resp) -> str | None:
    """Akamai serves its refusals as page bodies, sometimes under a 200."""
    body = resp.text[:2000] if resp.text else ""
    return next((m for m in _BLOCK_MARKERS if m in body), None)


def raise_for_block(resp) -> None:
    """Stop on backpressure rather than pushing through it. See CLAUDE.md.

    Enumeration cannot proceed without a page, so a 429 here is terminal. The
    clip loop handles 429 differently: it backs off and retries.
    """
    if rate_limited(resp):
        raise Blocked("rate limited (HTTP 429)")
    marker = denial(resp)
    if marker:
        raise Blocked(f"refused by Akamai ({marker})")
