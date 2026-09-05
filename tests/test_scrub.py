import pytest

from kroger_clipper import scrub

COUPON = {
    "id": "4235901",
    "krogerCouponNumber": "1234567",
    "brand": "Kroger Brand",
    "brandName": "Kroger Brand",
    "shortDescription": "$1.00 off 2",
    "expirationDate": "2026-10-15T03:59:59Z",
    "addedToCard": False,
    "categories": ["General"],
}

PAYLOAD = {
    "data": {"coupons": [COUPON]},
    "meta": {
        "coupons": {
            "page": {"hasMore": True},
            "filterSummaryByType": {"totalCount": 266, "newCouponsCount": 12},
        }
    },
}


def test_a_known_payload_survives_scrubbing():
    out = scrub.scrub_payload(PAYLOAD)
    assert out["data"]["coupons"][0]["shortDescription"] == "$1.00 off 2"


def test_pagination_is_kept_because_the_parser_reads_it():
    assert scrub.scrub_payload(PAYLOAD)["meta"]["coupons"]["page"]["hasMore"] is True


def test_per_shopper_meta_is_dropped():
    """totalCount is a fact about this account, and nothing in the code reads it."""
    out = scrub.scrub_payload(PAYLOAD)
    assert "filterSummaryByType" not in out["meta"]["coupons"]


def test_an_unrecognised_coupon_field_fails_closed():
    """The whole point: a new Kroger field must stop the capture, not ride along."""
    payload = {**PAYLOAD, "data": {"coupons": [{**COUPON, "householdId": "H-99887766"}]}}

    with pytest.raises(scrub.UnknownField, match="householdId"):
        scrub.scrub_payload(payload)


def test_the_error_says_what_to_do_about_it():
    payload = {**PAYLOAD, "data": {"coupons": [{**COUPON, "loyaltyId": "x"}]}}

    with pytest.raises(scrub.UnknownField, match="shopper-identifying"):
        scrub.scrub_payload(payload)


def test_an_unrecognised_top_level_field_fails_closed():
    with pytest.raises(scrub.UnknownField, match="cpr_chlge"):
        scrub.scrub_payload({**PAYLOAD, "cpr_chlge": "true"})


def test_a_challenge_body_is_refused_rather_than_written():
    with pytest.raises(scrub.UnknownField):
        scrub.scrub_payload({"cpr_chlge": "true", "t": "291758601"})


def test_a_payload_without_coupons_is_refused():
    with pytest.raises(scrub.UnknownField, match="no data.coupons"):
        scrub.scrub_payload({"data": {}, "meta": {}})


def test_scrubbing_does_not_mutate_the_original():
    original = {**COUPON}
    scrub.scrub_coupon(original)["brand"] = "MUTATED"
    assert original["brand"] == "Kroger Brand"


def test_every_allowlisted_field_is_documented_as_safe():
    """A guard on the allowlist itself: these must stay non-identifying."""
    suspicious = {
        f
        for f in scrub.COUPON_FIELDS
        if any(t in f.lower() for t in ("household", "loyalty", "customer", "shopper", "email"))
    }
    assert suspicious == set()
