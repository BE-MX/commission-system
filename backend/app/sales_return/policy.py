"""Pure return pricing: goods credits, cash refunds and debt waivers differ."""
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json

CENT = Decimal("0.01")
ZERO = Decimal(0)


def money(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("金额不是有效数字")
    return result.quantize(CENT, rounding=ROUND_HALF_UP)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, default=str,
                                    separators=(",", ":")).encode()).hexdigest()


def price(snapshot, body, history=None):
    history = history or {}
    sources = {str(row["source_key"]): row for row in snapshot["lines"]}
    if len(sources) != len(snapshot["lines"]):
        raise ValueError("实际出库明细存在重复身份，请先核验")
    used_quantities = history.get("quantities", {})
    used_reductions = history.get("reductions", {})
    used_reductions_usd = history.get("reductions_usd", {})
    used_refunds = history.get("refunds", {})
    used_refunds_usd = history.get("refunds_usd", {})
    lines, total, total_usd = [], ZERO, ZERO
    for item in body.lines:
        source = sources.get(item.source_key)
        if source is None:
            raise ValueError("所选产品已不在核验的实际出库明细中")
        shipped = int(source["quantity"])
        remaining_qty = shipped - int(used_quantities.get(item.source_key, 0))
        maximum_qty = remaining_qty if body.return_type == "return_refund" else shipped
        if item.quantity > maximum_qty:
            raise ValueError("本次数量超过该明细剩余可处理的实际出库数量")
        original = money(source["net_amount"])
        if shipped <= 0 or original < 0:
            raise ValueError("原出库货款或数量待核验")
        remaining = original - money(used_reductions.get(item.source_key, 0))
        per_quantity = money(original * item.quantity / shipped)
        if body.return_type == "return_refund":
            cumulative_quantity = int(used_quantities.get(item.source_key, 0)) + item.quantity
            if cumulative_quantity == shipped:
                # Only rounding from previously fully priced pieces follows the
                # final piece. Negotiated reductions never enlarge its value.
                tail = Decimal(str(history.get("physical_rounding", {}).get(item.source_key, 0)))
                per_quantity = max(ZERO, money(original * item.quantity / shipped + tail))
        reduction = money(item.reduction_amount)
        if reduction > min(remaining, per_quantity):
            raise ValueError("货款冲减超过本次数量对应净货值或累计可冲减额度")
        if body.return_type == "refund_only" and reduction <= 0:
            raise ValueError("仅退款明细的货款冲减必须大于零")
        previous_reduction = money(used_reductions.get(item.source_key, 0))
        previous_usd = money(used_reductions_usd.get(item.source_key, 0))
        original_usd = money(source["net_amount_usd"])
        usd = money(original_usd * (previous_reduction + reduction) / original) - previous_usd if original else ZERO
        if usd < 0 or usd + previous_usd > original_usd:
            raise ValueError("原出库美元货款累计分摊异常")
        lines.append({**source, "quantity": item.quantity, "shipped_quantity": shipped,
                      "remaining_quantity": remaining_qty, "remaining_amount": str(remaining),
                      "reduction_amount": str(reduction), "reduction_usd": str(usd)})
        total += reduction
        total_usd += usd
    original_goods = money(snapshot["goods_amount"])
    reduction_to_date = money(history.get("reduction_amount", 0))
    current_receivable = original_goods - reduction_to_date
    payments = sorted(snapshot["payments"], key=lambda row: (str(row["collection_date"]), str(row["payment_id"])))
    if len({str(row["payment_id"]) for row in payments}) != len(payments):
        raise ValueError("原回款身份重复，退款额度待核验")
    paid = sum((money(row["principal"]) for row in payments), ZERO) - sum(map(money, used_refunds.values()), ZERO)
    outstanding = current_receivable - paid
    available = ZERO
    payment_available = {}
    for row in payments:
        identity = str(row["payment_id"])
        if row["currency"] != snapshot["currency"]:
            raise ValueError("原回款币种与订单不一致")
        principal = money(row["principal"])
        refunded = money(used_refunds.get(identity, 0))
        cap = min(principal, money(row.get("refundable_amount", principal))) - refunded
        if principal < 0 or cap < 0 or money(row["principal_usd"]) < 0:
            raise ValueError("原回款本金或累计退款额度待核验")
        payment_available[identity] = cap
        available += cap
    if outstanding < 0 or paid < 0 or total > current_receivable:
        raise ValueError("订单净已收、货款冲减或未收余额存在差异，请先核对")
    presale = "funding_batches" in snapshot
    if presale:
        from app.sales_return.cash_allocation import match
        available, _ = match(payments, payment_available, snapshot["funding_batches"], lines)
    lower, upper = max(ZERO, total - outstanding), min(total, available)
    if lower > upper:
        raise ValueError("可退款本金不足以覆盖本次冲减，请先核对预售资金分配")
    refund = money(upper if body.refund_amount is None else body.refund_amount)
    if not lower <= refund <= upper:
        raise ValueError(f"实际退款必须在 {lower:.2f} 至 {upper:.2f} 之间")
    matched = {}
    if presale:
        funded, matched = match(payments, payment_available, snapshot["funding_batches"], lines, refund)
        if funded != refund:
            raise ValueError("所选批次的实际退款资金不足，请核对原分配")
    allocations, left, refund_usd = [], refund, ZERO
    for payment in payments:
        identity = str(payment["payment_id"])
        assigned = matched[identity]["amount"] if presale else min(left, payment_available[identity])
        if assigned <= 0:
            continue
        principal = money(payment["principal"])
        original_usd = money(payment["principal_usd"])
        previous = money(used_refunds.get(identity, 0))
        previous_usd = money(used_refunds_usd.get(identity, 0))
        usd = money(original_usd * (previous + assigned) / principal) - previous_usd
        if usd < 0 or usd + previous_usd > original_usd:
            raise ValueError("原回款美元本金累计分摊异常")
        allocations.append({"original_payment_id": identity, "original_principal": str(principal),
                            "original_principal_usd": str(original_usd), "refund_amount": str(assigned),
                            "refund_amount_usd": str(usd), "funding": matched[identity]["funding"] if presale else []})
        left -= assigned
        refund_usd += usd
    if left:
        raise ValueError("原回款分配不完整，请刷新后重试")
    result = {"order": snapshot, "lines": lines, "reduction_amount": str(total),
              "refund_amount": str(refund), "waived_amount": str(total - refund),
              "refund_min": str(lower), "refund_max": str(upper),
              "reduction_usd": str(total_usd), "refund_usd": str(refund_usd), "allocations": allocations,
              "balance": {"original_goods_amount": str(original_goods), "registered_amount": str(paid),
                          "current_receivable": str(current_receivable), "current_outstanding": str(outstanding),
                          "net_receivable": str(current_receivable-total), "net_received": str(paid-refund),
                          "net_outstanding": str(outstanding-total+refund)}}
    canonical = body.model_dump(mode="json", exclude={"request_key", "version"})
    canonical["refund_amount"] = str(refund)
    canonical["lines"] = sorted(({"source_key": line.source_key, "quantity": line.quantity,
                                  "reduction_amount": str(money(line.reduction_amount))} for line in body.lines),
                                key=lambda line: line["source_key"])
    result["quote_version"] = digest({"snapshot": snapshot, "body": canonical,
                                      "history": history})
    return result
