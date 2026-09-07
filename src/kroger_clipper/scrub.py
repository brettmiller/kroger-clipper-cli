"""Turn a real API response into something safe to commit.

The rule is allowlist, never denylist: only recognised fields survive, and an
unrecognised one aborts rather than passing through. A denylist would leak the
first new field Kroger adds. This repository is public.
"""

from .errors import KrogerClipperError

# Observed on real responses. Every one is public catalogue data or a boolean;
# nothing here identifies a shopper. Anything outside this set is refused on
# sight, which is the point - a new field might not be so harmless.
COUPON_FIELDS = frozenset(
    {
        "addedToCard",
        "brand",
        "brandName",
        "canBeAddedToCard",
        "canBeRemoved",
        "cashbackCashoutType",
        "categories",
        "clickListCoupon",
        "displayDescription",
        "displayEndDate",
        "displayStartDate",
        "expirationDate",
        "id",
        "imageUrl",
        "krogerCouponNumber",
        "modalities",
        "requirementDescription",
        "shortDescription",
        "specialSavings",
        "title",
        "upcs",
    }
)

TOP_LEVEL_FIELDS = frozenset({"data", "meta"})


class UnknownField(KrogerClipperError):
    """A field we do not recognise, so we cannot vouch for it being safe."""


def scrub_payload(payload: dict) -> dict:
    """A committable copy of an enumerate response, or an exception."""
    unknown = set(payload) - TOP_LEVEL_FIELDS
    if unknown:
        raise UnknownField(f"unrecognised top-level field(s): {sorted(unknown)}")

    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("coupons"), list):
        raise UnknownField("payload has no data.coupons to scrub")

    return {
        "data": {"coupons": [scrub_coupon(c) for c in data["coupons"]]},
        "meta": scrub_meta(payload.get("meta") or {}),
    }


def scrub_coupon(coupon: dict) -> dict:
    unknown = set(coupon) - COUPON_FIELDS
    if unknown:
        raise UnknownField(
            f"unrecognised coupon field(s): {sorted(unknown)}. "
            "Check whether they are shopper-identifying before adding them to COUPON_FIELDS."
        )
    for name, value in coupon.items():
        _check_shape(name, value)
    return dict(coupon)


def _check_shape(name: str, value) -> None:
    """The allowlist covers field names, not what is nested inside them.

    specialSavings holds objects whose keys nobody has vetted. Refuse them rather
    than copy an unexamined structure into a public repository.
    """
    if isinstance(value, list):
        for item in value:
            if not _scalar(item):
                raise UnknownField(
                    f"{name} contains a {type(item).__name__}, not a scalar: {item!r}. "
                    "Vet its keys for shopper-identifying data before allowing it."
                )
    elif not _scalar(value):
        raise UnknownField(f"{name} is a {type(value).__name__}, not a scalar")


def _scalar(value) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def scrub_meta(meta: dict) -> dict:
    """Keep only pagination.

    The rest of meta carries per-shopper counts and filter summaries, and nothing
    in this project reads them.
    """
    page = meta.get("coupons", {}).get("page", {})
    return {"coupons": {"page": {"hasMore": bool(page.get("hasMore"))}}}
