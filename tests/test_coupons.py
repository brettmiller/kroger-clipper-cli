import pytest
from curl_cffi.requests.exceptions import RequestException

from kroger_clipper import coupons, transport
from kroger_clipper.errors import Blocked, StructuralError


class StubResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class StubHttp:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        return self._responses.pop(0)


def page(coupon_ids, has_more):
    return StubResponse(
        payload={
            "data": {"coupons": [{"id": i, "brandName": "Acme"} for i in coupon_ids]},
            "meta": {"coupons": {"page": {"hasMore": has_more}}},
        }
    )


def test_single_page_returns_everything():
    http = StubHttp([page(["a", "b"], has_more=False)])
    assert [c["id"] for c in coupons.list_unclipped(http, "kroger.com")] == ["a", "b"]
    assert len(http.calls) == 1


def test_pagination_follows_has_more_and_advances_offset():
    http = StubHttp([page(["a"], has_more=True), page(["b"], has_more=False)])
    found = coupons.list_unclipped(http, "kroger.com")

    assert [c["id"] for c in found] == ["a", "b"]
    assert [call[1]["page.offset"] for call in http.calls] == [0, coupons.PAGE_SIZE]


def test_only_unclipped_is_requested():
    http = StubHttp([page([], has_more=False)])
    coupons.list_unclipped(http, "kroger.com")
    assert http.calls[0][1]["filter.status"] == "unclipped"


def test_empty_page_stops_even_when_has_more_lies():
    http = StubHttp([page([], has_more=True)])
    assert coupons.list_unclipped(http, "kroger.com") == []


def test_runaway_pagination_raises_rather_than_looping_forever():
    http = StubHttp([page(["x"], has_more=True) for _ in range(coupons.MAX_PAGES + 1)])
    with pytest.raises(StructuralError, match="did not terminate"):
        coupons.list_unclipped(http, "kroger.com")


def test_non_200_is_structural_not_silent():
    http = StubHttp([StubResponse(status_code=400, payload={}, text="")])
    with pytest.raises(StructuralError, match="HTTP 400"):
        coupons.list_unclipped(http, "kroger.com")


def test_rate_limit_raises_blocked():
    http = StubHttp([StubResponse(status_code=429, text="Too many requests")])
    with pytest.raises(Blocked, match="429"):
        coupons.list_unclipped(http, "kroger.com")


def test_akamai_denial_in_a_200_body_still_raises_blocked():
    http = StubHttp([StubResponse(status_code=200, text="Access Denied ... edgesuite")])
    with pytest.raises(Blocked):
        coupons.list_unclipped(http, "kroger.com")


def test_missing_data_coupons_is_structural():
    http = StubHttp([StubResponse(payload={"meta": {}})])
    with pytest.raises(StructuralError, match="data.coupons"):
        coupons.list_unclipped(http, "kroger.com")


def test_non_json_body_is_structural():
    http = StubHttp([StubResponse(status_code=200, payload=None, text="<html>")])
    with pytest.raises(StructuralError, match="non-JSON"):
        coupons.list_unclipped(http, "kroger.com")


def test_describe_uses_prose_because_there_is_no_numeric_value():
    line = coupons.describe(
        {"brandName": "Acme", "shortDescription": "$1.00 off 2", "expirationDate": "2026-10-01"}
    )
    assert line == "Acme: $1.00 off 2 (expires 2026-10-01)"


class ExplodingHttp:
    def __init__(self, exc):
        self._exc = exc

    def get(self, url, params=None):
        raise self._exc

    def post(self, url, json=None):
        raise self._exc


def test_enumerate_reports_a_reset_connection_instead_of_a_traceback():
    http = ExplodingHttp(RequestException("reset", transport.HTTP2_STREAM_RESET, None))

    with pytest.raises(Blocked, match="kroger-clipper login"):
        coupons.list_unclipped(http, "kroger.com")


def test_clip_reports_a_reset_connection_instead_of_a_traceback():
    http = ExplodingHttp(RequestException("reset", transport.HTTP2_STREAM_RESET, None))

    with pytest.raises(Blocked, match="kroger-clipper login"):
        coupons.apply_all(http, "kroger.com", [{"id": "c0"}], sleep=lambda _s: None)
