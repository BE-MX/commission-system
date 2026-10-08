"""One order, one currency, remote-ID dedupe and local intent reservations."""
import hashlib
import json
from decimal import Decimal

from app.receipt import remote
from app.receipt.models import Receipt, ReceiptIntent


def calculate(db, invoice, snapshot, *, exclude_receipt=None, exclude_intent=False, current=False):
    if snapshot.get("invoice_binding") and snapshot["invoice_binding"] != remote.invoice_binding(invoice):
        raise ValueError("订单信息已变化，请重新核验余额")
    remote_rows = snapshot["rows"]
    remote_ids, registered, effective = set(), Decimal("0"), Decimal("0")
    for row in remote_rows:
        identity = str(row.get("cash_collection_id") or "")
        if not identity or identity in remote_ids or row.get("currency") != invoice.currency:
            raise ValueError("远端回款 ID 或币种异常，余额待核验")
        remote_ids.add(identity)
        value = remote.money(row.get("amount"))
        registered += value
        if str(row.get("collect_status")) == "1":
            effective += value
    query = db.query(Receipt).filter(Receipt.invoice_id == invoice.id, Receipt.status == "active", Receipt.purpose != "freight")
    if current:
        query = query.order_by(Receipt.id).populate_existing().with_for_update()
    local = query.all()
    for row in local:
        if row.currency != invoice.currency or row.customer_id != invoice.customer_id:
            raise ValueError("方舟回款与订单身份不一致，请核对")
        if row.xiaoman_receipt_id and row.sync_status == "uncertain":
            raise ValueError("关联小满回款待核对，余额暂冻结，请先处理原单")
        if row.xiaoman_receipt_id in remote_ids:
            counterpart = next(r for r in remote_rows if str(r["cash_collection_id"]) == row.xiaoman_receipt_id)
            if remote.money(counterpart["amount"]) != remote.net_amount(row):
                raise ValueError("小满已修改关联回款金额，请先核对原单，余额暂冻结")
            # Remote totals are net, while the local order/intent ledger is gross.
            registered += row.bank_charge
            if str(counterpart.get("collect_status")) == "1":
                effective += row.bank_charge
            continue
        if row.xiaoman_receipt_id:
            raise ValueError("小满关联回款已缺失或转移，请管理员核实远端变更后再登记")
        if row.id == exclude_receipt:
            continue
        registered += row.amount
    query = db.query(ReceiptIntent).filter(ReceiptIntent.invoice_id == invoice.id)
    if current:
        query = query.populate_existing().with_for_update()
    intent = query.first()
    if not exclude_intent and intent and intent.eligible and intent.status in {"armed", "ready"}:
        registered += intent.amount or Decimal("0")
    fingerprint = {
        "invoice": [invoice.id, invoice.xiaoman_order_id, str(invoice.total_amount), str(invoice.surcharge_amount or 0), invoice.currency, invoice.customer_id, invoice.sync_status],
        "remote": sorted((str(r["cash_collection_id"]), str(r["amount"]), str(r.get("collect_status"))) for r in remote_rows),
        "local": sorted((r.id, r.version, r.sync_status, r.status, str(r.amount), str(r.bank_charge)) for r in local),
        "intent": [intent.status, str(intent.amount)] if intent else None,
    }
    return {"invoice_id": invoice.id, "total_amount": str(invoice.total_amount), "currency": invoice.currency,
            "registered_amount": str(registered), "effective_amount": str(effective),
            "pending_amount": str(registered - effective),
            "remaining_amount": str(invoice.total_amount - registered),
            "version": hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()}


def ensure_available(summary, amount):
    if amount > Decimal(summary["remaining_amount"]):
        raise ValueError("本次回款超过可登记余额，请刷新金额；待同步、失败和待核对单仍占用余额")


def calculate_target(db, target, snapshot, *, exclude_receipt=None, current=False):
    """Freight has its own order cap; it never consumes the goods invoice cap."""
    binding = [target.id, target.remote_order_id, str(target.amount),
               target.currency, target.customer_id, target.version]
    if snapshot.get("target_binding") != binding:
        raise ValueError("运费目标身份已变化，请重新核验余额")
    query = db.query(Receipt).filter(Receipt.receivable_id == target.id,
        Receipt.status == "active")
    if current:
        query = query.order_by(Receipt.id).populate_existing().with_for_update()
    local = query.all()
    by_remote = {str(row.xiaoman_receipt_id): row for row in local if row.xiaoman_receipt_id}
    registered = effective = Decimal(0)
    seen = set()
    for row in snapshot["rows"]:
        identity = str(row.get("cash_collection_id") or "")
        if not identity or identity in seen or identity not in by_remote:
            raise ValueError("运费目标存在未分配或重复的远端回款，请先核对")
        seen.add(identity)
        local_row = by_remote[identity]
        if (row.get("currency") != target.currency
                or remote.money(row.get("amount")) != remote.net_amount(local_row)):
            raise ValueError("运费目标远端回款金额或币种已变化")
        registered += local_row.amount
        if str(row.get("collect_status")) == "1":
            effective += local_row.amount
    for row in local:
        if (row.customer_id != target.customer_id or row.currency != target.currency
                or row.xiaoman_order_id != target.remote_order_id):
            raise ValueError("运费回款目标身份不一致")
        if row.xiaoman_receipt_id:
            if row.xiaoman_receipt_id not in seen or row.sync_status == "uncertain":
                raise ValueError("运费远端回款缺失或待核对")
        elif row.id != exclude_receipt:
            registered += row.amount
    remaining = Decimal(target.amount) - registered
    if remaining < 0:
        raise ValueError("运费目标回款已超额，请核对")
    fingerprint = {"target": binding, "remote": sorted(seen),
        "local": sorted((row.id, row.version, row.sync_status, str(row.amount)) for row in local)}
    return {"registered_amount": str(registered), "effective_amount": str(effective),
            "remaining_amount": str(remaining), "currency": target.currency,
            "version": hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()}
