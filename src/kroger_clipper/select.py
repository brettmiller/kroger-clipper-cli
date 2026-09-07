"""Narrow a list of coupons down, without asking Kroger to do it.

Filtering happens here rather than through `filter.category` / `filter.modality`
for two reasons: the fields are already on every coupon we fetch, so it costs no
requests; and the server answers HTTP 500 for a category that is not stocked at
the active store, which turns a typo into a failed run.

Kroger's UI calls these "Departments" and "Ways to shop"; the API calls the same
things `categories` and `modalities`. "General" is a real entry in Kroger's own
Departments list, not a placeholder.
"""

from .errors import StructuralError

DEPARTMENTS = "categories"
WAYS_TO_SHOP = "modalities"

# Reported by --list-filters but not filterable: nobody has needed it yet.
SPECIAL_SAVINGS = "specialSavings"


def select(
    coupons: list[dict],
    *,
    departments: tuple[str, ...] = (),
    exclude_departments: tuple[str, ...] = (),
    ways_to_shop: tuple[str, ...] = (),
) -> list[dict]:
    """Coupons matching every filter given. No filters means everything."""
    keep = list(coupons)
    if departments:
        keep = [c for c in keep if _values(c, DEPARTMENTS) & _fold(departments)]
    if exclude_departments:
        keep = [c for c in keep if not _values(c, DEPARTMENTS) & _fold(exclude_departments)]
    if ways_to_shop:
        keep = [c for c in keep if _values(c, WAYS_TO_SHOP) & _fold(ways_to_shop)]
    return keep


def tally(coupons: list[dict], field: str) -> dict[str, int]:
    """How many coupons carry each value, so the vocabulary is discoverable.

    Counts case-insensitively but reports Kroger's own spelling: this output is
    meant to be copied back onto the command line, so "Health & Beauty" must not
    come back as "health & beauty".
    """
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for coupon in coupons:
        for value in _labels(coupon, field):
            key = value.casefold()
            labels.setdefault(key, value)
            counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {labels[key]: count for key, count in ordered}


# Kroger is not consistent: categories and modalities are plain strings, but
# specialSavings holds objects. Reporting is best-effort on purpose - refusing to
# print a vocabulary because one display-only field changed shape is a worse
# outcome than showing it imperfectly. Filtering stays strict; see _raw.
_LABEL_KEYS = ("name", "displayName", "label", "title", "description", "value", "type")


def _labels(coupon: dict, field: str) -> list[str]:
    """Human-readable values for display. Tolerates shapes _raw would reject."""
    raw = coupon.get(field) or []
    if not isinstance(raw, list):
        return []
    return [label for value in raw if (label := _label(value))]


def _label(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in _LABEL_KEYS:
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                return found.strip()
    return str(value)


def _fold(values) -> set[str]:
    return {v.strip().casefold() for v in values}


def _values(coupon: dict, field: str) -> set[str]:
    """The coupon's values for a field, case-folded for comparison."""
    return _fold(_raw(coupon, field))


def _raw(coupon: dict, field: str) -> list[str]:
    """The coupon's values as Kroger spells them, validated.

    Missing is fine — a coupon in no department simply matches no department
    filter. A value that is not a string is not: silently matching nothing would
    turn a changed payload into an empty run, which is the one failure this
    project refuses to allow.
    """
    raw = coupon.get(field) or []
    if not isinstance(raw, list):
        raise StructuralError(f"expected {field} to be a list, got {type(raw).__name__}")
    for value in raw:
        if not isinstance(value, str):
            raise StructuralError(
                f"expected {field} to hold strings, found {type(value).__name__}. "
                "Kroger changed the payload; filtering cannot be trusted until this is checked."
            )
    return [value.strip() for value in raw]
