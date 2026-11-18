from decimal import Decimal

import pytest

from app.factory_inbound.matching_rules import (
    Candidate, color_keys, extract_invoice_ref, match_candidates, parse_ref,
)


@pytest.mark.parametrize(("raw", "expected"), [
    ("983单", {(9, 83)}), ("0983", {(9, 83)}),
    ("1158", {(11, 58), (1, 158)}), ("9100", {(9, 100)}),
    ("11100", {(11, 100)}), ("13", set()), ("2026", set()),
])
def test_handwritten_reference(raw, expected):
    assert parse_ref(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("SC-11100", "11100"), ("ly#1151生产单", "1151"), ("翟 1113 生产", "1113"),
    ("生产单#1158", "1158"), ("生产单2026", None), ("李-KC-1158", None),
    ("INV20261101-123", None), ("SC-1154~DEL~8421", "1154"),
])
def test_invoice_reference(raw, expected):
    assert extract_invoice_ref(raw) == expected


@pytest.mark.parametrize(("raw", "exact", "converted"), [
    ("４＃", "4", set()), ("878-18", "878-18", {"8TP8/18", "878T18"}),
    ("5A-18B-62", "5A-18B-62", {"5ATP18B/62"}),
    ("5A760", "5A760", {"5AT60"}), ("GC", "COOKIESCREAM", set()),
])
def test_color_normalization(raw, exact, converted):
    assert color_keys(raw, {"GC": "Cookies Cream"}) == (exact, converted)


def test_quantity_hint_never_selects_grade_and_rule_is_not_green():
    candidates = [
        Candidate(1, 2, "Super Double Drawn Genius Weft", "22", "#8TP8/18", "20g", 90, 40),
        Candidate(2, 3, "Standard Double Drawn Genius Weft", "22", "#8TP8/18", "20g", 150, 90),
    ]
    kwargs = dict(length=Decimal(22), weight=Decimal(20), color="878-18",
                  process="Genius Weft", grade=None, quantity=90)
    status, matches = match_candidates(candidates, **kwargs)
    assert status == "choose"
    assert [row.sku_id for row in matches] == [3, 2]
    assert match_candidates(candidates, **{**kwargs, "grade": "Super Double Drawn"})[0] == "confirm"
    assert match_candidates(candidates, **{**kwargs, "color": "8TP8/18", "grade": "Super Double Drawn"})[0] == "matched"
