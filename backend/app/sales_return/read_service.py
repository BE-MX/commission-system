"""Return projections and current cumulative quotas."""
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, or_, select

from app.sales_return import access, policy
from app.sales_return.models import (ReturnAllocation, ReturnEffect, ReturnEvent, ReturnItem,
                                    ReturnReceipt, ReturnReceiving, SalesReturn)
from app.sales_return.schemas import Draft, Line


def serialize(row):
    return {column.name: (str(value) if isinstance(value, Decimal) else value.isoformat() if hasattr(value, "isoformat") else value)
            for column in row.__table__.columns if (value := getattr(row, column.name)) is not None}


def history(db, order_id, *, exclude=None):
    conditions = [SalesReturn.order_id == str(order_id), SalesReturn.status == "effective"]
    if exclude is not None:
        conditions.append(SalesReturn.id != exclude)
    returns = db.scalars(select(SalesReturn).where(*conditions).order_by(SalesReturn.id)).all()
    ids = [row.id for row in returns]
    quantities, reductions, reduction_usd, refunds, refunds_usd, physical_reductions = [defaultdict(lambda: Decimal(0)) for _ in range(6)]
    types = {row.id: row.return_type for row in returns}
    physical_rounding = defaultdict(lambda: Decimal(0))
    for row in db.scalars(select(ReturnItem).where(ReturnItem.return_id.in_(ids))).all() if ids else []:
        if types[row.return_id] == "return_refund":
            quantities[row.source_key] += row.quantity
            physical_reductions[row.source_key] += row.reduction_amount
            frozen = row.source_snapshot
            exact = Decimal(str(frozen["net_amount"])) * row.quantity / int(frozen.get("shipped_quantity", frozen["quantity"]))
            if row.reduction_amount == policy.money(exact):
                physical_rounding[row.source_key] += exact - row.reduction_amount
        reductions[row.source_key] += row.reduction_amount
        reduction_usd[row.source_key] += row.reduction_usd
    for row in db.scalars(select(ReturnAllocation).where(ReturnAllocation.return_id.in_(ids))).all() if ids else []:
        refunds[row.original_payment_id] += row.refund_amount
        refunds_usd[row.original_payment_id] += row.refund_amount_usd
    return {"quantities": dict(quantities), "physical_reductions": dict(physical_reductions),
            "physical_rounding": dict(physical_rounding),
            "reductions": dict(reductions), "reductions_usd": dict(reduction_usd),
            "refunds": dict(refunds), "refunds_usd": dict(refunds_usd),
            "reduction_amount": sum((row.reduction_amount for row in returns), Decimal(0))}


def draft_body(db, row):
    items = db.scalars(select(ReturnItem).where(ReturnItem.return_id == row.id).order_by(ReturnItem.id)).all()
    return Draft(order_id=row.order_id, return_type=row.return_type, reason_code=row.reason_code, reason=row.reason,
                 refund_amount=row.refund_amount,
                 lines=[Line(source_key=i.source_key, quantity=i.quantity, reduction_amount=i.reduction_amount) for i in items])


def receiving_status(items, receivings, return_type):
    if return_type == "refund_only":
        return "not_required"
    expected = sum(item.quantity for item in items)
    received = sum(item.quantity for item in receivings)
    if received == 0:
        return "awaiting_receipt"
    if received < expected:
        return "partially_received"
    if any(item.pending_quantity for item in receivings):
        return "pending_inspection"
    if any(item.accepted_quantity and item.stock_status != "stocked" for item in receivings):
        return "inspected"
    return "stocked" if any(item.accepted_quantity for item in receivings) else "rejected"


def describe(db, row, *, detail=True):
    result = serialize(row)
    result.pop("request_hash", None)
    result.pop("activate_hash", None)
    result.pop("snapshot", None)
    items = db.scalars(select(ReturnItem).where(ReturnItem.return_id == row.id).order_by(ReturnItem.id)).all()
    receivings = db.scalars(select(ReturnReceiving).where(ReturnReceiving.return_id == row.id)
                           .order_by(ReturnReceiving.id)).all()
    result["quantity"] = sum(item.quantity for item in items) if row.return_type == "return_refund" else 0
    result["receiving_status"] = receiving_status(items, receivings, row.return_type)
    if not detail:
        return result
    result["items"] = [{**serialize(item), "item_id": item.id} for item in items]
    for item in result["items"]:
        item.pop("source_snapshot", None)
    result["receivings"] = [serialize(item) for item in receivings]
    result["receipts"] = [{**serialize(item), "source": "sales_return", "sync_status": "local_only",
                            "detail_url": f"/invoice/sales-returns?return_id={row.id}"}
                           for item in db.scalars(select(ReturnReceipt).where(ReturnReceipt.return_id == row.id)
                                                  .order_by(ReturnReceipt.id)).all()]
    result["effects"] = [serialize(item) for item in db.scalars(select(ReturnEffect).where(ReturnEffect.return_id == row.id)).all()]
    allocations = db.scalars(select(ReturnAllocation).where(ReturnAllocation.return_id == row.id)).all()
    result["allocations"] = [{key: value for key, value in serialize(item).items() if key != "basis"}
                             | {"basis_status": item.basis.get("status", "pending_basis")} for item in allocations]
    result["commission_status"] = "pending_basis" if any(item.basis.get("status") != "frozen" for item in allocations) else "ready"
    result["events"] = [serialize(item) for item in db.scalars(select(ReturnEvent).where(ReturnEvent.return_id == row.id)
                                                             .order_by(ReturnEvent.id)).all()]
    return result


def list_rows(db, user, *, page=1, page_size=20, keyword="", status="", return_type="", customer_id="",
              order_id="", date_from=None, date_to=None, **unused):
    query = access.scope(select(SalesReturn).where(SalesReturn.status != "deleted"), db, user, SalesReturn)
    if keyword:
        term = f"%{keyword}%"
        query = query.where(or_(SalesReturn.return_no.like(term), SalesReturn.order_no.like(term),
                               SalesReturn.customer_name.like(term)))
    for column, value in ((SalesReturn.status, status), (SalesReturn.return_type, return_type),
                          (SalesReturn.customer_id, customer_id), (SalesReturn.order_id, order_id)):
        if value:
            query = query.where(column == value)
    if date_from:
        query = query.where(SalesReturn.effective_date >= date_from)
    if date_to:
        query = query.where(SalesReturn.effective_date <= date_to)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(SalesReturn.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
    return {"items": [describe(db, row, detail=False) for row in rows], "total": total}


def order_lines(db, order_id, user):
    from app.sales_return import sources
    snapshot = sources.snapshot(db, order_id, user)
    current = history(db, order_id)
    for item in snapshot["lines"]:
        key = item["source_key"]
        item["shipped_quantity"] = item["quantity"]
        item["remaining_quantity"] = item["quantity"] - int(current["quantities"].get(key, 0))
        item["remaining_amount"] = str(policy.money(item["net_amount"]) - current["reductions"].get(key, Decimal(0)))
    return snapshot


def describe_receiving(db, row, user):
    financial = "super_admin" in user.get("roles", []) or "sales_return:read" in user.get("permissions", [])
    result = describe(db, row)
    if financial:
        return result
    safe_keys = {"id", "return_no", "order_id", "order_no", "customer_id", "customer_name", "return_type",
                 "status", "version", "quantity", "receiving_status", "receivings"}
    safe = {key: value for key, value in result.items() if key in safe_keys}
    safe["items"] = [{key: value for key, value in item.items() if key in
                      {"id", "item_id", "product_id", "sku_id", "product_name", "specification", "quantity"}}
                     for item in result["items"]]
    return safe
