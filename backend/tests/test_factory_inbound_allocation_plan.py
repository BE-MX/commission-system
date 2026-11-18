import json
from datetime import date, datetime

import pytest

from app.factory_inbound.allocation_plan import PlanLine, Target, plan_allocations


def production_item(
    item_id, order_id, available, *, product_id=10, sku_id=20, order_date=date(2026, 11, 1), urgent=False
):
    return Target("production_item", item_id, order_id, product_id, sku_id, available, order_date, urgent)


def test_named_production_uses_only_its_order_and_blocks_excess():
    result = plan_allocations(
        [PlanLine(1, 10, 20, 8, "order", "production_order", 100)],
        [
            production_item(5, 100, 2),
            production_item(6, 100, 3, urgent=True),
            production_item(7, 101, 20, urgent=True),
            production_item(8, 100, 20, sku_id=21),
        ],
    )

    assert result == [{
        "line_id": 1,
        "allocations": [
            {"target_kind": "production_item", "target_id": 6, "order_id": 100, "quantity": 3},
            {"target_kind": "production_item", "target_id": 5, "order_id": 100, "quantity": 2},
        ],
        "unallocated_qty": 3,
        "blocking_reason": "production_order_capacity_exceeded",
    }]


def test_cross_production_prioritizes_urgency_then_order_time_then_item_id():
    lines = [PlanLine(1, 10, 20, 15, "cross")]
    targets = [
        production_item(5, 101, 2),
        production_item(4, 101, 2),
        production_item(6, 102, 2, order_date=datetime(2026, 11, 1, 0, 1)),
        production_item(7, 103, 2, order_date=date(2026, 11, 2), urgent=True),
        production_item(8, 104, 2, order_date=None),
        production_item(9, 105, 20, product_id=11),
        production_item(10, 106, 20, sku_id=30),
        production_item(11, 107, 0),
        Target("invoice_item", 12, 108, 10, 20, 20, date(2026, 10, 1), True),
    ]

    result = plan_allocations(lines, targets)

    assert [item["target_id"] for item in result[0]["allocations"]] == [7, 4, 5, 6, 8]
    assert result[0]["unallocated_qty"] == 5
    assert result[0]["blocking_reason"] is None
    assert result == plan_allocations(lines, reversed(targets))
    assert result == json.loads(json.dumps(result))


def test_named_production_retains_capacity_before_competing_cross_lines():
    lines = [
        PlanLine(1, 10, 20, 5, "cross"),
        PlanLine(2, 10, 20, 4, "order", "production_order", 100),
        PlanLine(3, 10, 20, 4, "cross"),
        PlanLine(4, 10, 20, 2, "inbound_only"),
    ]
    targets = [production_item(1, 100, 6), production_item(2, 200, 4)]

    result = plan_allocations(reversed(lines), targets)

    assert [line["line_id"] for line in result] == [1, 2, 3, 4]
    assert [
        [(item["target_id"], item["quantity"]) for item in line["allocations"]]
        for line in result
    ] == [[(1, 2), (2, 3)], [(1, 4)], [(2, 1)], []]
    assert [line["unallocated_qty"] for line in result] == [0, 0, 3, 2]
    assert [line["blocking_reason"] for line in result] == [None, None, None, None]


def test_invoice_fills_by_line_then_item_id_and_allows_excess():
    result = plan_allocations(
        [
            PlanLine(2, 10, 20, 3, "order", "invoice", 100),
            PlanLine(1, 10, 20, 3, "order", "invoice", 100),
            PlanLine(3, 10, 20, 1, "order", "production_order", 100),
        ],
        [
            Target("invoice_item", 2, 100, 10, 20, 2, None),
            Target("invoice_item", 1, 100, 10, 20, 2, None),
            Target("invoice_item", 3, 101, 10, 20, 20, None),
            production_item(1, 100, 1),
        ],
    )

    assert [
        [(item["target_kind"], item["target_id"], item["quantity"]) for item in line["allocations"]]
        for line in result
    ] == [
        [("invoice_item", 1, 2), ("invoice_item", 2, 1)],
        [("invoice_item", 2, 1)],
        [("production_item", 1, 1)],
    ]
    assert [line["unallocated_qty"] for line in result] == [0, 2, 0]
    assert all(line["blocking_reason"] is None for line in result)


def test_cross_replanning_uses_only_freshly_eligible_capacity():
    lines = [PlanLine(1, 10, 20, 5, "cross")]
    original = plan_allocations(lines, [production_item(1, 100, 2)])
    recomputed = plan_allocations(lines, [production_item(2, 200, 4)])

    assert original[0]["unallocated_qty"] == 3
    assert recomputed[0]["allocations"] == [
        {"target_kind": "production_item", "target_id": 2, "order_id": 200, "quantity": 4}
    ]
    assert recomputed[0]["unallocated_qty"] == 1


def test_duplicate_target_identity_is_rejected():
    with pytest.raises(ValueError, match="Duplicate allocation target"):
        plan_allocations(
            [PlanLine(1, 10, 20, 5, "cross")],
            [production_item(1, 100, 2), production_item(1, 100, 2)],
        )
