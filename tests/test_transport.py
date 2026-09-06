import json

import pytest
from curl_cffi.requests.exceptions import RequestException

from kroger_clipper import session, transport
from kroger_clipper.errors import Blocked, SessionExpired, StructuralError

HEADERS = {
    "x-facility-id": "09900999",
    "x-modality-type": "IN_STORE",
    "user-agent": "Mozilla/5.0",
}
COOKIES = [
    {"name": "loggedIn", "value": "true", "domain": "www.kroger.com", "path": "/"},
    {"name": "_abck", "value": "akamai", "domain": ".kroger.com", "path": "/"},
]


class StubResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


@pytest.fixture
def stored(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

    def write(cookies=COOKIES, headers=HEADERS):
        path = tmp_path / "kroger-clipper" / "session.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"storage_state": {"cookies": cookies}, "context_headers": headers})
        )

    return write


def test_build_carries_cookies_and_store_headers(stored):
    stored()
    http = transport.build("kroger.com")

    assert {c.name for c in http.cookies.jar} == {"loggedIn", "_abck"}
    assert http.headers["x-facility-id"] == "09900999"
    assert http.headers["referer"] == "https://www.kroger.com/savings/cl/coupons/"
    assert "json" in http.headers["accept"]


def test_build_refuses_a_session_with_no_store_headers(stored):
    """Without them the API returns an opaque 400; fail with a useful message instead."""
    stored(headers={})
    with pytest.raises(StructuralError, match="run `kroger-clipper login`"):
        transport.build("kroger.com")


def test_build_reports_a_missing_session_rather_than_crashing(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    with pytest.raises(session.SessionMissing):
        transport.build("kroger.com")


def test_build_honours_the_banner(stored):
    stored()
    assert transport.build("frysfood.com").headers["referer"].startswith("https://www.frysfood.com")


def test_raise_for_auth_on_401():
    with pytest.raises(SessionExpired):
        transport.raise_for_auth(StubResponse(401, ""))


def test_raise_for_auth_on_the_documented_code():
    body = '{"errors":{"reason":"The request must be authenticated","code":"AUTH_REQUIRED"}}'
    with pytest.raises(SessionExpired):
        transport.raise_for_auth(StubResponse(403, body))


def test_raise_for_auth_passes_a_healthy_response():
    transport.raise_for_auth(StubResponse(200, '{"data":{}}'))


def test_rate_limited_only_on_429():
    assert transport.rate_limited(StubResponse(429)) is True
    assert transport.rate_limited(StubResponse(200)) is False


@pytest.mark.parametrize(
    "body", ["Too many requests", "Access Denied", "errors.edgesuite.net/18.abc"]
)
def test_denial_detects_akamai_bodies(body):
    assert transport.denial(StubResponse(200, body)) is not None


def test_denial_ignores_ordinary_bodies():
    assert transport.denial(StubResponse(200, '{"data":{"coupons":[]}}')) is None


def test_raise_for_block_covers_both_rate_limit_and_denial():
    with pytest.raises(Blocked, match="429"):
        transport.raise_for_block(StubResponse(429, ""))
    with pytest.raises(Blocked, match="Akamai"):
        transport.raise_for_block(StubResponse(200, "Access Denied"))
    transport.raise_for_block(StubResponse(200, "{}"))


def test_stream_reset_becomes_a_block_with_advice():
    """Akamai refuses below HTTP, so curl error 92 is the only evidence of a block."""
    exc = RequestException("stream reset", transport.HTTP2_STREAM_RESET, None)
    blocked = transport.translate(exc)

    assert "kroger-clipper login" in str(blocked)
    assert "wait" in str(blocked)


def test_other_transport_errors_are_reported_plainly():
    blocked = transport.translate(RequestException("name resolution failed", 6, None))

    assert "could not reach Kroger" in str(blocked)
    assert "name resolution failed" in str(blocked)
