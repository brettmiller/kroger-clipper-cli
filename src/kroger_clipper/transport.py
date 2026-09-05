from curl_cffi import requests

from . import session
from .errors import Blocked, StructuralError

# A stock Python TLS fingerprint is dropped at the Akamai edge before any HTTP
# status comes back, so the client has to look like the browser we logged in
# with. See docs/adr/0001. "chrome" tracks the newest profile curl_cffi ships.
IMPERSONATE = "chrome"
TIMEOUT_S = 30

_BLOCK_MARKERS = ("Too many requests", "Access Denied", "edgesuite")


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


def raise_for_block(resp) -> None:
    """Stop on backpressure rather than pushing through it. See CLAUDE.md."""
    if resp.status_code == 429:
        raise Blocked("rate limited (HTTP 429)")
    body = resp.text[:2000] if resp.text else ""
    for marker in _BLOCK_MARKERS:
        if marker in body:
            raise Blocked(f"refused by Akamai ({marker})")
