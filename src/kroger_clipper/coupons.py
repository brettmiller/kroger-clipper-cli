import random
import time

from . import transport
from .errors import Blocked, StructuralError

API_PATH = "/atlas/v1/savings-coupons/v1/coupons"
CLIP_PATH = "/atlas/v1/savings-coupons/v1/clip-unclip"
PAGE_SIZE = 100

# The page loop must terminate even if hasMore is wrong forever.
MAX_PAGES = 50


def list_unclipped(http, banner: str) -> list[dict]:
    """Every coupon not yet on the card, following pagination to the end."""
    url = f"https://www.{banner}{API_PATH}"
    found: list[dict] = []

    for page in range(MAX_PAGES):
        payload = _fetch(http, url, offset=page * PAGE_SIZE)
        batch = _coupons(payload)
        found.extend(batch)
        if not batch or not _has_more(payload):
            return found

    raise StructuralError(f"pagination did not terminate within {MAX_PAGES} pages")


def fetch_page(http, banner: str, offset: int = 0, size: int = PAGE_SIZE) -> dict:
    """One page of the enumerate endpoint, validated. Used by list_unclipped and capture."""
    return _fetch(http, f"https://www.{banner}{API_PATH}", offset=offset, size=size)


def _fetch(http, url: str, offset: int, size: int = PAGE_SIZE) -> dict:
    try:
        resp = http.get(
            url,
            params={
                "projections": "coupons.compact",
                "filter.status": "unclipped",
                "page.size": size,
                "page.offset": offset,
            },
        )
    except transport.RequestException as exc:
        raise transport.translate(exc) from exc
    transport.raise_for_block(resp)
    if resp.status_code != 200:
        raise StructuralError(f"enumerate returned HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise StructuralError("enumerate returned a non-JSON body") from exc


def _coupons(payload: dict) -> list[dict]:
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("coupons"), list):
        raise StructuralError("response is missing data.coupons")
    return data["coupons"]


def _has_more(payload: dict) -> bool:
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return False
    page = meta.get("coupons", {}).get("page", {})
    return bool(page.get("hasMore"))


def describe(coupon: dict) -> str:
    """One line for a human. The API has no numeric value field, only prose."""
    brand = coupon.get("brandName") or coupon.get("brand") or "?"
    title = coupon.get("shortDescription") or coupon.get("title") or "(no description)"
    expires = coupon.get("expirationDate") or "?"
    return f"{brand}: {title} (expires {expires})"


# Clipping is one POST per coupon; there is no batch endpoint. Pacing is not
# throttling for its own sake - it keeps the traffic shape unremarkable. The
# request round-trip is itself ~0.6s, so shaving the delay buys less than it
# looks: the floor for a full card is a couple of minutes either way.
DELAY_RANGE_S = (0.2, 0.7)

# Individual coupons fail for their own reasons; five in a row is not
# coincidence, it means something systemic broke and the rest are futile.
MAX_CONSECUTIVE_FAILURES = 5

RETRY_BACKOFF_S = (5, 15, 45, 120)

# Kroger caps how many coupons a card may hold (observed: 250). Reaching it is a
# normal end to a run, not a fault - and once it is reached every further clip is
# guaranteed to fail, so stop on the first one rather than proving it five times.
CARD_FULL_CODE = "TooManyCouponsOnCard"

# filter.status=unclipped can return coupons that are in fact already on the
# card, so this is expected rather than exceptional. Counting it as a failure
# would let stale enumeration data trip the consecutive-failure abort.
ALREADY_ADDED_CODE = "CouponAlreadyAdded"


def clip_all(
    http,
    banner: str,
    items,
    *,
    limit=None,
    delay_range=DELAY_RANGE_S,
    sleep=time.sleep,
    on_result=None,
) -> dict:
    """Clip each coupon in turn, pacing between them and stopping on systemic failure."""
    low, high = delay_range
    if low < 0 or high < low:
        raise ValueError(f"invalid delay range: {delay_range}")

    url = f"https://www.{banner}{CLIP_PATH}"
    targets = list(items)[:limit] if limit else list(items)

    clipped = 0
    already = 0
    failures: list[dict] = []
    consecutive = 0

    for index, coupon in enumerate(targets):
        if index:
            sleep(random.uniform(low, high))

        outcome = _clip_one(http, url, coupon, sleep)

        if _has_code(outcome, CARD_FULL_CODE):
            return _summary(clipped, already, failures, index + 1, None, card_full=True)

        if on_result:
            on_result(outcome)

        if outcome["ok"]:
            clipped += 1
            consecutive = 0
            continue

        if _has_code(outcome, ALREADY_ADDED_CODE):
            already += 1
            consecutive = 0
            continue

        failures.append(outcome)
        consecutive += 1
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            reason = f"{consecutive} consecutive failures"
            return _summary(clipped, already, failures, index + 1, reason, card_full=False)

    return _summary(clipped, already, failures, len(targets), None, card_full=False)


def _summary(clipped, already, failures, attempted, stopped, *, card_full) -> dict:
    return {
        "clipped": clipped,
        "already_clipped": already,
        "failures": failures,
        "attempted": attempted,
        "stopped": stopped,
        "card_full": card_full,
    }


def _has_code(outcome: dict, code: str) -> bool:
    return outcome["status"] == 422 and code in (outcome["body"] or "")


def _clip_one(http, url: str, coupon, sleep) -> dict:
    coupon_id = coupon["id"] if isinstance(coupon, dict) else coupon
    payload = {"action": "CLIP", "couponId": coupon_id}

    for attempt in range(len(RETRY_BACKOFF_S) + 1):
        try:
            resp = http.post(url, json=payload)
        except transport.RequestException as exc:
            raise transport.translate(exc) from exc

        if transport.rate_limited(resp):
            if attempt == len(RETRY_BACKOFF_S):
                break
            sleep(RETRY_BACKOFF_S[attempt])
            continue

        marker = transport.denial(resp)
        if marker:
            raise Blocked(f"refused by Akamai ({marker})")

        transport.raise_for_auth(resp)

        return {
            "id": coupon_id,
            "ok": 200 <= resp.status_code < 300,
            "status": resp.status_code,
            "body": (resp.text or "")[:300],
        }

    raise Blocked("still rate limited after backing off")
