"""Overlay credits and cash returns without reopening settled receivables."""
from decimal import Decimal

from sqlalchemy import select

from app.sales_return.models import ReturnEffect, ReturnReceipt, SalesReturn
from app.sales_return.policy import digest, money


def totals(db, order_id):
    effects = db.scalars(select(ReturnEffect).where(ReturnEffect.order_id == str(order_id))).all()
    receipts = db.scalars(select(ReturnReceipt).where(ReturnReceipt.order_id == str(order_id))).all()
    return {"goods_adjustment": sum((row.amount for row in effects), Decimal(0)),
            "cash_adjustment": sum((row.amount for row in receipts), Decimal(0)),
            "version": digest([[row.id, str(row.amount)] for row in effects] +
                              [[row.id, str(row.amount)] for row in receipts])}


def overlay(db, order_id, summary):
    if not order_id:
        return summary
    changes = totals(db, order_id)
    if not changes["goods_adjustment"] and not changes["cash_adjustment"]:
        return summary
    result = dict(summary)
    result["original_total_amount"] = summary["total_amount"]
    result["return_reduction_amount"] = str(-changes["goods_adjustment"])
    result["local_refund_amount"] = str(-changes["cash_adjustment"])
    result["total_amount"] = str(money(summary["total_amount"]) + changes["goods_adjustment"])
    result["registered_amount"] = str(money(summary["registered_amount"]) + changes["cash_adjustment"])
    result["effective_amount"] = str(money(summary["effective_amount"]) + changes["cash_adjustment"])
    result["remaining_amount"] = str(money(result["total_amount"]) - money(result["registered_amount"]))
    result["version"] = digest([summary["version"], changes["version"]])
    if money(result["remaining_amount"]) < 0:
        if money(summary.get("pending_amount", 0)) > 0:
            raise ValueError("退货前未收预登记款超过净应收，请先核对并更正原款，不能按旧金额收款")
        raise ValueError("退货后的净应收与净已收存在差异，请先核对原单及退款")
    return result
