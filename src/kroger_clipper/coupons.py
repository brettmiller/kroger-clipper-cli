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


def _fetch(http, url: str, offset: int) -> dict:
    resp = http.get(
        url,
        params={
            "projections": "coupons.compact",
            "filter.status": "unclipped",
            "page.size": PAGE_SIZE,
            "page.offset": offset,
        },
    )
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
# throttling for its own sake - a few hundred milliseconds between requests
# costs nothing on a weekly run and keeps the traffic shape unremarkable.
DELAY_RANGE_S = (0.3, 1.0)

# Individual coupons fail for their own reasons; five in a row is not
# coincidence, it means something systemic broke and the rest are futile.
MAX_CONSECUTIVE_FAILURES = 5

RETRY_BACKOFF_S = (5, 15, 45, 120)

# Kroger caps how many coupons a card may hold (observed: 250). Reaching it is a
# normal end to a run, not a fault - and once it is reached every further clip is
# guaranteed to fail, so stop on the first one rather than proving it five times.
CARD_FULL_CODE = "TooManyCouponsOnCard"


def clip_all(http, banner: str, items, *, limit=None, sleep=time.sleep, on_result=None) -> dict:
    """Clip each coupon in turn, pacing between them and stopping on systemic failure."""
    url = f"https://www.{banner}{CLIP_PATH}"
    targets = list(items)[:limit] if limit else list(items)

    clipped = 0
    failures: list[dict] = []
    consecutive = 0

    for index, coupon in enumerate(targets):
        if index:
            sleep(random.uniform(*DELAY_RANGE_S))

        outcome = _clip_one(http, url, coupon, sleep)

        if _card_full(outcome):
            return {
                "clipped": clipped,
                "failures": failures,
                "attempted": index + 1,
                "stopped": None,
                "card_full": True,
            }

        if on_result:
            on_result(outcome)

        if outcome["ok"]:
            clipped += 1
            consecutive = 0
            continue

        failures.append(outcome)
        consecutive += 1
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            return {
                "clipped": clipped,
                "failures": failures,
                "attempted": index + 1,
                "stopped": f"{consecutive} consecutive failures",
                "card_full": False,
            }

    return {
        "clipped": clipped,
        "failures": failures,
        "attempted": len(targets),
        "stopped": None,
        "card_full": False,
    }


def _card_full(outcome: dict) -> bool:
    return outcome["status"] == 422 and CARD_FULL_CODE in (outcome["body"] or "")


def _clip_one(http, url: str, coupon, sleep) -> dict:
    coupon_id = coupon["id"] if isinstance(coupon, dict) else coupon
    payload = {"action": "CLIP", "couponId": coupon_id}

    for attempt in range(len(RETRY_BACKOFF_S) + 1):
        resp = http.post(url, json=payload)

        if transport.rate_limited(resp):
            if attempt == len(RETRY_BACKOFF_S):
                break
            sleep(RETRY_BACKOFF_S[attempt])
            continue

        marker = transport.denial(resp)
        if marker:
            raise Blocked(f"refused by Akamai ({marker})")

        return {
            "id": coupon_id,
            "ok": 200 <= resp.status_code < 300,
            "status": resp.status_code,
            "body": (resp.text or "")[:300],
        }

    raise Blocked("still rate limited after backing off")
