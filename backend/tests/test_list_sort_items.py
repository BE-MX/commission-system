from datetime import date

import pytest

from app.core.list_sort import apply_items_sort


def test_natural_sort_compares_numbers_and_ignores_case():
    rows = [
        {"id": 10, "name": "item10"},
        {"id": 3, "name": "Item3"},
        {"id": 2, "name": "item2"},
    ]

    result = apply_items_sort(rows, "name", "asc", {"name": "name"})

    assert [row["id"] for row in result] == [2, 3, 10]


@pytest.mark.parametrize(
    "order, expected_ids",
    [("asc", [3, 2, 1]), ("desc", [2, 3, 1])],
)
def test_none_values_remain_last_in_both_directions(order, expected_ids):
    rows = [
        {"id": 1, "value": None},
        {"id": 2, "value": 10},
        {"id": 3, "value": 0},
    ]

    result = apply_items_sort(rows, "value", order, {"value": "value"})

    assert [row["id"] for row in result] == expected_ids


def test_descending_sort_keeps_tied_ids_ascending():
    rows = [
        {"id": 3, "value": 20},
        {"id": 1, "value": 2},
        {"id": 2, "value": 20},
    ]

    result = apply_items_sort(rows, "value", "desc", {"value": "value"})

    assert [row["id"] for row in result] == [2, 3, 1]


def test_custom_tie_breaker_sorts_by_code():
    rows = [
        {"id": 1, "value": 20, "code": "B"},
        {"id": 2, "value": 20, "code": "A"},
    ]

    result = apply_items_sort(
        rows, "value", "asc", {"value": "value"}, tie_breaker="code"
    )

    assert [row["id"] for row in result] == [2, 1]


def test_mixed_int_and_float_values_sort_numerically():
    rows = [
        {"id": 1, "value": 2},
        {"id": 2, "value": 10.5},
        {"id": 3, "value": 3},
    ]

    result = apply_items_sort(rows, "value", "asc", {"value": "value"})

    assert [row["id"] for row in result] == [1, 3, 2]


def test_date_values_sort_chronologically():
    rows = [
        {"id": 1, "value": date(2026, 1, 1)},
        {"id": 2, "value": date(2025, 12, 31)},
        {"id": 3, "value": date(2026, 1, 2)},
    ]

    result = apply_items_sort(rows, "value", "asc", {"value": "value"})

    assert [row["id"] for row in result] == [2, 1, 3]


@pytest.mark.parametrize(
    "sort_field, sort_order",
    [("value", "up"), ("unknown", "asc")],
)
def test_invalid_sort_returns_new_list_and_preserves_input(sort_field, sort_order):
    rows = [{"id": 2, "value": 20}, {"id": 1, "value": 10}]
    original = [row.copy() for row in rows]

    result = apply_items_sort(rows, sort_field, sort_order, {"value": "value"})

    assert [row["id"] for row in result] == [2, 1]
    assert result is not rows
    assert rows == original


def test_callable_accessor_sorts_by_derived_value():
    rows = [
        {"id": 1, "name": "aaa"},
        {"id": 2, "name": "z"},
        {"id": 3, "name": "bb"},
    ]

    result = apply_items_sort(
        rows, "length", "asc", {"length": lambda row: len(row["name"])}
    )

    assert [row["id"] for row in result] == [2, 3, 1]
