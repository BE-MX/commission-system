"""Allocate invoice handling fees in original currency, with final-payment rounding."""
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


def allocate(db, invoice, amount, *, exclude_receipt=None):
    fee = invoice.surcharge_amount or Decimal("0")
    rows = remote.order_receipts(db, invoice.xiaoman_order_id)
    ids, registered, charged = {}, Decimal("0"), Decimal("0")
    for row in rows:
        identity = str(row["cash_collection_id"])
        # The persistent index intentionally contains no fee detail. Fetch only
        # this order's receipts; never rebuild the global index for a new field.
        detail = remote.receipt_info(db, identity)
        if (str(detail.get("order_id")) != str(invoice.xiaoman_order_id)
                or detail.get("currency") != invoice.currency
                or remote.money(detail.get("amount")) != remote.money(row["amount"])):
            raise ValueError("小满回款已变化，请重新核对手续费")
        value, charge = remote.money(detail.get("amount")), remote.money(detail.get("bank_charge"))
        if charge > value or remote.money(detail.get("real_amount")) != value - charge or identity in ids:
            raise ValueError("小满回款手续费或实到账金额异常")
        ids[identity] = (value, charge); registered += value; charged += charge
    for row in db.query(Receipt).filter(Receipt.invoice_id == invoice.id, Receipt.status == "active").all():
        if row.id == exclude_receipt:
            continue
        if row.sync_status == "uncertain":
            raise ValueError("已有回款结果待核对，暂不能分摊手续费")
        if row.xiaoman_receipt_id in ids:
            if ids[row.xiaoman_receipt_id] != (row.amount, row.bank_charge):
                raise ValueError("小满已修改关联回款金额或手续费，请先核对原单")
            continue
        if row.xiaoman_receipt_id:
            raise ValueError("已有回款结果待核对，暂不能分摊手续费")
        registered += row.amount; charged += row.bank_charge
    return proportional(invoice.total_amount, fee, amount, registered, charged)
