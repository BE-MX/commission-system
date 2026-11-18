"""Deterministic allocation from eligible, resolved order-item snapshots."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal, TypedDict


OrderKind = Literal["production_order", "invoice"]
TargetKind = Literal["production_item", "invoice_item"]
LineRoute = Literal["order", "cross", "inbound_only"]


@dataclass(frozen=True)
class PlanLine:
    id: int
    product_id: int
    sku_id: int
    quantity: int
    route: LineRoute
    order_kind: OrderKind | None = None
    order_id: int | None = None


@dataclass(frozen=True)
class Target:
    kind: TargetKind
    id: int
    order_id: int
    product_id: int
    sku_id: int
    available: int
    order_date: datetime | date | None
    urgent: bool = False


class Allocation(TypedDict):
    target_kind: TargetKind
    target_id: int
    order_id: int
    quantity: int


class LineAllocationPlan(TypedDict):
    line_id: int
    allocations: list[Allocation]
    unallocated_qty: int
    blocking_reason: Literal["production_order_capacity_exceeded"] | None


_ORDER_TARGET_KIND: dict[OrderKind, TargetKind] = {
    "production_order": "production_item",
    "invoice": "invoice_item",
}


def _production_priority(target: Target) -> tuple[bool, datetime, int]:
    order_date = target.order_date
    if order_date is None:
        order_date = datetime.max
    elif not isinstance(order_date, datetime):
        order_date = datetime.combine(order_date, time.min)
    return not target.urgent, order_date, target.id


def plan_allocations(
    lines: Iterable[PlanLine], targets: Iterable[Target]
) -> list[LineAllocationPlan]:
    """Plan a batch using capacities net of existing receipts and reservations.

    The caller supplies eligible, uniquely resolved targets and naive Beijing
    order times. Reuse with fresh snapshots to recompute under transaction locks.
    Named production lines have first claim on their order's capacity. Lines
    receive capacity in ID order within each route, and results are in ID order.
    """
    remaining_by_target: dict[tuple[TargetKind, int], int] = {}
    production_targets: list[Target] = []
    invoice_targets: list[Target] = []
    for target in targets:
        key = (target.kind, target.id)
        if key in remaining_by_target:
            raise ValueError(f"Duplicate allocation target {key}")
        remaining_by_target[key] = target.available
        if target.available > 0:
            if target.kind == "production_item":
                production_targets.append(target)
            elif target.kind == "invoice_item":
                invoice_targets.append(target)

    production_targets.sort(key=_production_priority)
    invoice_targets.sort(key=lambda target: target.id)
    by_order: dict[tuple[TargetKind, int, int, int], list[Target]] = defaultdict(list)
    production_by_sku: dict[tuple[int, int], list[Target]] = defaultdict(list)
    for target in production_targets:
        production_by_sku[target.product_id, target.sku_id].append(target)
    for target in (*production_targets, *invoice_targets):
        by_order[target.kind, target.order_id, target.product_id, target.sku_id].append(target)

    plans: dict[int, LineAllocationPlan] = {}
    for line in sorted(lines, key=lambda line: (line.route == "cross", line.id)):
        if line.id in plans:
            raise ValueError(f"Duplicate allocation line {line.id}")
        if line.quantity <= 0:
            raise ValueError(f"Allocation line {line.id} must have a positive quantity")

        candidates: Iterable[Target]
        if line.route == "order":
            if line.order_kind not in _ORDER_TARGET_KIND or line.order_id is None:
                raise ValueError(f"Allocation line {line.id} requires a supported order kind and ID")
            target_kind = _ORDER_TARGET_KIND[line.order_kind]
            candidates = by_order.get((target_kind, line.order_id, line.product_id, line.sku_id), ())
        elif line.route == "cross":
            candidates = production_by_sku.get((line.product_id, line.sku_id), ())
        elif line.route == "inbound_only":
            candidates = ()
        else:
            raise ValueError(f"Unsupported allocation route {line.route!r}")

        unallocated_qty = line.quantity
        allocations: list[Allocation] = []
        for target in candidates:
            if unallocated_qty == 0:
                break
            key = (target.kind, target.id)
            quantity = min(unallocated_qty, remaining_by_target[key])
            if quantity == 0:
                continue
            allocations.append({
                "target_kind": target.kind,
                "target_id": target.id,
                "order_id": target.order_id,
                "quantity": quantity,
            })
            remaining_by_target[key] -= quantity
            unallocated_qty -= quantity

        blocking_reason = None
        if unallocated_qty and line.route == "order" and line.order_kind == "production_order":
            blocking_reason = "production_order_capacity_exceeded"
        plans[line.id] = {
            "line_id": line.id,
            "allocations": allocations,
            "unallocated_qty": unallocated_qty,
            "blocking_reason": blocking_reason,
        }

    return [plans[line_id] for line_id in sorted(plans)]
