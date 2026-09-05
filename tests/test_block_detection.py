import pytest
from playwright.sync_api import Error as PlaywrightError

from kroger_clipper import session

RATE_LIMIT_BODY = (
    '{"message": "Too many requests", "referenceNum": "0.abc", "clientIP": "203.0.113.9"}'
)
DENIED_BODY = "<html><body>Access Denied ... https://errors.edgesuite.net/18.abc</body></html>"
NORMAL_BODY = "<html><body>Digital Coupons</body></html>"

REAL_HEADERS = {
    "x-facility-id": "09900999",
    "x-laf-object": '[{"modality":{"type":"IN_STORE"}}]',
    "x-modality": '{"type":"IN_STORE","locationId":"09900999"}',
    "x-modality-type": "IN_STORE",
    "x-kroger-channel": "WEB",
    "user-agent": "Mozilla/5.0",
    "traceparent": "00-deadbeef-01",
    "cookie": "should-never-be-captured",
}


class StubRequest:
    def __init__(self, url, headers, all_headers_raises=False):
        self.url = url
        self.headers = headers
        self._all_headers_raises = all_headers_raises

    def all_headers(self):
        if self._all_headers_raises:
            raise PlaywrightError("Target page, context or browser has been closed")
        return self.headers


class StubPage:
    """Minimal stand-in for a Playwright page: emits one request during goto()."""

    def __init__(self, body, request=None):
        self._body = body
        self._request = request
        self._handlers = []
        self.goto_calls = []

    def on(self, event, handler):
        self._handlers.append((event, handler))

    def remove_listener(self, event, handler):
        self._handlers.remove((event, handler))

    def wait_for_timeout(self, _ms):
        pass

    def goto(self, url, **_kwargs):
        self.goto_calls.append(url)
        if self._request is not None:
            for event, handler in list(self._handlers):
                if event == "request":
                    handler(self._request)

    def content(self):
        return self._body


def _coupons_request(headers=None):
    return StubRequest(
        "https://www.kroger.com/atlas/v1/savings-coupons/v1/coupons?page.size=24",
        headers if headers is not None else REAL_HEADERS,
    )


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (RATE_LIMIT_BODY, "rate limited"),
        (DENIED_BODY, "blocked"),
        (NORMAL_BODY, None),
    ],
)
def test_blocked_reason(body, expected):
    assert session._blocked_reason(StubPage(body)) == expected


def test_warm_reports_rate_limit_without_raising():
    result = session._warm(StubPage(RATE_LIMIT_BODY), "https://www.kroger.com")
    assert result["ok"] is False
    assert result["detail"] == "rate limited"
    assert result["headers"] == {}


def test_warm_captures_store_headers_from_the_pages_own_request():
    page = StubPage(NORMAL_BODY, _coupons_request())
    result = session._warm(page, "https://www.kroger.com")

    assert result["ok"] is True
    assert page.goto_calls == ["https://www.kroger.com/savings/cl/coupons/"]
    assert result["headers"]["x-facility-id"] == "09900999"
    assert result["headers"]["x-modality-type"] == "IN_STORE"


def test_warm_keeps_only_the_allowlisted_headers():
    result = session._warm(StubPage(NORMAL_BODY, _coupons_request()), "https://www.kroger.com")

    assert set(result["headers"]) <= set(session.CONTEXT_HEADERS)
    # Telemetry is stale on replay; the cookie header is a secret we already hold.
    assert "traceparent" not in result["headers"]
    assert "cookie" not in result["headers"]


def test_warm_fails_when_the_page_never_calls_the_coupons_api():
    result = session._warm(StubPage(NORMAL_BODY), "https://www.kroger.com")

    assert result["ok"] is False
    assert result["detail"] == "page made no coupons request"


def test_warm_ignores_unrelated_requests():
    unrelated = StubRequest("https://www.kroger.com/atlas/v1/product/v2/products", REAL_HEADERS)
    result = session._warm(StubPage(NORMAL_BODY, unrelated), "https://www.kroger.com")

    assert result["ok"] is False


def test_warm_falls_back_when_all_headers_raises():
    """A closing browser must not turn header capture into an unhandled callback error."""
    request = StubRequest(
        "https://www.kroger.com/atlas/v1/savings-coupons/v1/coupons",
        REAL_HEADERS,
        all_headers_raises=True,
    )
    result = session._warm(StubPage(NORMAL_BODY, request), "https://www.kroger.com")

    assert result["ok"] is True
    assert result["headers"]["x-facility-id"] == "09900999"
