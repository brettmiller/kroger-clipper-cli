import pytest

from kroger_clipper import coupons
from kroger_clipper.errors import Blocked

from .test_coupons import StubResponse


class StubHttp:
    def __init__(self, responses):
        self._responses = list(responses)
        self.posts = []

    def post(self, url, json=None):
        self.posts.append((url, json))
        return self._responses.pop(0)


class Clock:
    def __init__(self):
        self.slept = []

    def __call__(self, seconds):
        self.slept.append(seconds)


def ok():
    return StubResponse(status_code=200, text="{}")


def fail(status=400):
    return StubResponse(status_code=status, text='{"error":"nope"}')


def items(count):
    return [{"id": f"c{i}"} for i in range(count)]


def test_clips_every_coupon_once():
    http = StubHttp([ok(), ok(), ok()])
    result = coupons.clip_all(http, "kroger.com", items(3), sleep=Clock())

    assert result["clipped"] == 3
    assert result["stopped"] is None
    assert len(http.posts) == 3


def test_sends_the_documented_payload():
    http = StubHttp([ok()])
    coupons.clip_all(http, "kroger.com", items(1), sleep=Clock())

    url, body = http.posts[0]
    assert url.endswith("/atlas/v1/savings-coupons/v1/clip-unclip")
    assert body == {"action": "CLIP", "couponId": "c0"}


def test_paces_between_coupons_but_not_before_the_first():
    clock = Clock()
    coupons.clip_all(StubHttp([ok(), ok(), ok()]), "kroger.com", items(3), sleep=clock)

    assert len(clock.slept) == 2
    assert all(coupons.DELAY_RANGE_S[0] <= s <= coupons.DELAY_RANGE_S[1] for s in clock.slept)


def test_individual_failure_is_survivable_and_recorded():
    http = StubHttp([ok(), fail(), ok()])
    result = coupons.clip_all(http, "kroger.com", items(3), sleep=Clock())

    assert result["clipped"] == 2
    assert [f["status"] for f in result["failures"]] == [400]
    assert result["failures"][0]["body"]  # status *and* body, so max-reached is diagnosable
    assert result["stopped"] is None


def test_stops_after_five_consecutive_failures():
    http = StubHttp([fail() for _ in range(5)])
    result = coupons.clip_all(http, "kroger.com", items(20), sleep=Clock())

    assert result["clipped"] == 0
    assert result["attempted"] == 5
    assert "consecutive" in result["stopped"]
    assert len(http.posts) == 5


def test_a_success_resets_the_consecutive_counter():
    http = StubHttp([fail(), fail(), fail(), fail(), ok(), fail(), fail()])
    result = coupons.clip_all(http, "kroger.com", items(7), sleep=Clock())

    assert result["clipped"] == 1
    assert result["stopped"] is None
    assert len(http.posts) == 7


def test_rate_limit_backs_off_and_retries_rather_than_aborting():
    clock = Clock()
    http = StubHttp([StubResponse(status_code=429, text=""), ok()])
    result = coupons.clip_all(http, "kroger.com", items(1), sleep=clock)

    assert result["clipped"] == 1
    assert clock.slept == [coupons.RETRY_BACKOFF_S[0]]


def test_backoff_is_exponential_then_gives_up():
    clock = Clock()
    attempts = len(coupons.RETRY_BACKOFF_S) + 1
    http = StubHttp([StubResponse(status_code=429, text="") for _ in range(attempts)])

    with pytest.raises(Blocked, match="still rate limited"):
        coupons.clip_all(http, "kroger.com", items(1), sleep=clock)

    assert clock.slept == list(coupons.RETRY_BACKOFF_S)


def test_akamai_denial_aborts_immediately():
    http = StubHttp([StubResponse(status_code=200, text="Access Denied edgesuite")])
    with pytest.raises(Blocked, match="Akamai"):
        coupons.clip_all(http, "kroger.com", items(3), sleep=Clock())


def test_limit_caps_the_run():
    http = StubHttp([ok(), ok()])
    result = coupons.clip_all(http, "kroger.com", items(10), limit=2, sleep=Clock())

    assert result["clipped"] == 2
    assert len(http.posts) == 2


def test_on_result_sees_every_outcome():
    seen = []
    http = StubHttp([ok(), fail()])
    coupons.clip_all(http, "kroger.com", items(2), sleep=Clock(), on_result=seen.append)

    assert [o["ok"] for o in seen] == [True, False]
