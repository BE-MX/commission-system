"""Allocate invoice handling fees in original currency, with final-payment rounding."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from app.receipt import remote
from app.receipt.models import Receipt


def proportional(total, fee, amount, registered=Decimal("0"), charged=Decimal("0")):
    total, fee, amount = remote.money(total), remote.money(fee), remote.money(amount)
    remaining, fee_left = total - registered, fee - charged
    if total <= 0 or fee > total or amount > remaining or fee_left < 0:
        raise ValueError("订单手续费或剩余金额异常，请核对已有回款")
    charge = fee_left if amount == remaining else min(
        (amount * fee / total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), fee_left)
    if charge > amount:
        raise ValueError("剩余手续费超过本次回款金额，请核对已有回款")
    return charge


@dataclass(frozen=True)
class FeeEvidence:
    binding: tuple
    rows: tuple


def read_evidence(db, binding):
    """External monetary facts for an independently captured invoice binding."""
    binding = tuple(binding)
    order_id, _, currency, _, _ = binding
    rows = remote.order_receipts(db, order_id)
    if not isinstance(rows, list):
        raise ValueError("小满回款证据格式不完整")
    ids = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("cash_collection_id") or "amount" not in row:
            raise ValueError("小满回款证据字段不完整")
        identity = str(row["cash_collection_id"])
        detail = remote.receipt_info(db, identity)
        if not isinstance(detail, dict):
            raise ValueError("小满回款手续费详情格式不完整")
        if (str(detail.get("order_id")) != str(order_id)
                or detail.get("currency") != currency
                or remote.money(detail.get("amount")) != remote.money(row["amount"])):
            raise ValueError("小满回款已变化，请重新核对手续费")
        value, charge = remote.money(detail.get("amount")), remote.money(detail.get("bank_charge"))
        if charge > value or remote.money(detail.get("real_amount")) != value - charge or identity in ids:
            raise ValueError("小满回款手续费或实到账金额异常")
        ids[identity] = (value, charge)
    return FeeEvidence(binding, tuple((identity, value, charge) for identity, (value, charge) in sorted(ids.items())))


def calculate(db, invoice, amount, evidence, *, exclude_receipt=None, current=False):
    """Pure local allocation; retry uses current locked participating receipts."""
    if tuple(remote.invoice_binding(invoice)) != evidence.binding:
        raise ValueError("订单手续费目标已变化，请重新核对")
    fee = invoice.surcharge_amount or Decimal("0")
    ids = {identity: (value, charge) for identity, value, charge in evidence.rows}
    registered = sum((value for value, _ in ids.values()), Decimal("0"))
    charged = sum((charge for _, charge in ids.values()), Decimal("0"))
    query = db.query(Receipt).filter(Receipt.invoice_id == invoice.id,
        Receipt.status == "active", Receipt.purpose != "freight").order_by(Receipt.id)
    if current:
        query = query.populate_existing().with_for_update()
    for row in query.all():
        if row.sync_status == "uncertain":
            raise ValueError("已有回款结果待核对，暂不能分摊手续费")
        if row.xiaoman_receipt_id in ids:
            if ids[row.xiaoman_receipt_id] != (remote.net_amount(row), Decimal("0")):
                raise ValueError("小满已修改关联回款金额或手续费，请先核对原单")
            registered += row.bank_charge
            charged += row.bank_charge
            continue
        if row.id == exclude_receipt:
            continue
        if row.xiaoman_receipt_id:
            raise ValueError("已有回款结果待核对，暂不能分摊手续费")
        registered += row.amount; charged += row.bank_charge
    return proportional(invoice.total_amount, fee, amount, registered, charged)


def allocate(db, invoice, amount, *, exclude_receipt=None):
    # Existing create/delivery callers retain their original transaction contract.
    evidence = read_evidence(db, tuple(remote.invoice_binding(invoice)))
    return calculate(db, invoice, amount, evidence, exclude_receipt=exclude_receipt)
