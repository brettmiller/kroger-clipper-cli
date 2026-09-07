import pytest

from kroger_clipper import select
from kroger_clipper.errors import StructuralError


def coupon(cid, categories=(), modalities=()):
    return {"id": cid, "categories": list(categories), "modalities": list(modalities)}


CATALOGUE = [
    coupon("a", ["Dairy"], ["IN_STORE", "PICKUP"]),
    coupon("b", ["Dairy", "Frozen"], ["IN_STORE"]),
    coupon("c", ["Beverages"], ["DELIVERY"]),
    coupon("d", [], ["IN_STORE"]),
]


def ids(items):
    return [c["id"] for c in items]


def test_no_filters_keeps_everything():
    assert ids(select.select(CATALOGUE)) == ["a", "b", "c", "d"]


def test_department_include():
    assert ids(select.select(CATALOGUE, departments=("Dairy",))) == ["a", "b"]


def test_department_matching_is_case_insensitive():
    """Nobody is going to type DEPARTMENT names exactly as Kroger cases them."""
    assert ids(select.select(CATALOGUE, departments=("dairy",))) == ["a", "b"]
    assert ids(select.select(CATALOGUE, departments=("  DAIRY  ",))) == ["a", "b"]


def test_department_exclude():
    assert ids(select.select(CATALOGUE, exclude_departments=("Dairy",))) == ["c", "d"]


def test_a_coupon_in_several_departments_is_excluded_by_any_of_them():
    assert ids(select.select(CATALOGUE, exclude_departments=("Frozen",))) == ["a", "c", "d"]


def test_include_and_exclude_compose():
    kept = select.select(CATALOGUE, departments=("Dairy",), exclude_departments=("Frozen",))
    assert ids(kept) == ["a"]


def test_ways_to_shop():
    assert ids(select.select(CATALOGUE, ways_to_shop=("IN_STORE",))) == ["a", "b", "d"]
    assert ids(select.select(CATALOGUE, ways_to_shop=("DELIVERY",))) == ["c"]


def test_filters_across_dimensions_are_all_required():
    kept = select.select(CATALOGUE, departments=("Dairy",), ways_to_shop=("PICKUP",))
    assert ids(kept) == ["a"]


def test_a_coupon_with_no_departments_survives_an_exclude():
    """Belonging to no department is not the same as belonging to the excluded one."""
    assert "d" in ids(select.select(CATALOGUE, exclude_departments=("Dairy",)))


def test_a_coupon_with_no_departments_fails_an_include():
    assert "d" not in ids(select.select(CATALOGUE, departments=("Dairy",)))


def test_a_missing_field_is_tolerated():
    assert select.select([{"id": "x"}], departments=("Dairy",)) == []


def test_tally_counts_and_orders_by_frequency():
    assert select.tally(CATALOGUE, select.DEPARTMENTS) == {"Dairy": 2, "Beverages": 1, "Frozen": 1}


def test_tally_of_ways_to_shop():
    assert select.tally(CATALOGUE, select.WAYS_TO_SHOP)["IN_STORE"] == 3


def test_tally_reports_krogers_spelling_not_a_folded_one():
    """--list-filters output gets pasted back onto the command line."""
    coupons = [coupon("a", ["Health & Beauty"]), coupon("b", ["Health & Beauty"])]
    assert select.tally(coupons, select.DEPARTMENTS) == {"Health & Beauty": 2}


def test_tally_merges_values_that_differ_only_in_case():
    coupons = [coupon("a", ["Dairy"]), coupon("b", ["DAIRY"])]
    assert select.tally(coupons, select.DEPARTMENTS) == {"Dairy": 2}


AMPERSAND = [
    coupon("a", ["Health & Beauty"], ["IN_STORE"]),
    coupon("b", ["Meat & Seafood"], ["PICKUP"]),
    coupon("c", ["Dairy"], ["IN_STORE"]),
]


def test_departments_with_spaces_and_ampersands_match():
    assert ids(select.select(AMPERSAND, departments=("Health & Beauty",))) == ["a"]


def test_such_names_match_case_insensitively_too():
    assert ids(select.select(AMPERSAND, departments=("health & BEAUTY",))) == ["a"]


def test_internal_spacing_is_significant():
    """Only surrounding whitespace is trimmed; "Health &Beauty" is a different name."""
    assert select.select(AMPERSAND, departments=("Health &Beauty",)) == []


def test_surrounding_whitespace_is_trimmed_on_both_sides():
    values = select.select(AMPERSAND, departments=("  Health & Beauty  ",))
    assert ids(values) == ["a"]


def test_a_non_list_field_is_structural_not_silently_empty():
    with pytest.raises(StructuralError, match="expected categories to be a list"):
        select.select([{"id": "x", "categories": "Dairy"}], departments=("Dairy",))


def test_objects_where_strings_were_expected_fail_loudly():
    """If Kroger switches to {"name": ...} we must not quietly clip nothing."""
    payload = [{"id": "x", "categories": [{"name": "Dairy"}]}]

    with pytest.raises(StructuralError, match="Kroger changed the payload"):
        select.select(payload, departments=("Dairy",))


def test_unfiltered_runs_never_touch_the_fields():
    """A payload change must not break a plain `clip` that filters nothing."""
    assert select.select([{"id": "x", "categories": [{"name": "Dairy"}]}]) != []


def test_tally_is_as_strict_as_filtering():
    """Both read the same fields; a shape change should not be reported as normal."""
    with pytest.raises(StructuralError):
        select.tally([{"id": "a", "categories": [{"name": "Dairy"}]}], select.DEPARTMENTS)


def test_a_coupon_in_two_departments_is_counted_under_both():
    """Counts can sum to more than the number of coupons; they are not a partition."""
    coupons = [coupon("a", ["General", "Dairy"]), coupon("b", ["General"])]
    assert select.tally(coupons, select.DEPARTMENTS) == {"General": 2, "Dairy": 1}
