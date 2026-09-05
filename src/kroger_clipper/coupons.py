from . import transport
from .errors import StructuralError

API_PATH = "/atlas/v1/savings-coupons/v1/coupons"
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
