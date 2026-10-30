"""Read-only net funding over immutable presale receipts and applications.

Cash refunds consume their original receipt; goods reductions retire the original
batch debt first. Paid surplus is credit backed by that same receipt and return.
"""
from collections import defaultdict
from decimal import Decimal

from app.invoice.presale_funding import FundingLot
from app.invoice.settlement_models import SettlementApplication, ShipmentOutbound, ShipmentSettlement
from app.receipt.models import Receipt
from app.sales_return.models import ReturnAllocation, ReturnItem, SalesReturn

ZERO = Decimal(0)
POOL = {"presale_deposit", "presale_advance"}


def _rows(query, current):
    return (query.populate_existing().with_for_update() if current else query).all()


def credit_application(settlement, application, receipt):
    """A credit reference never changes the original payment's sending owner."""
    if settlement is None:
        return False
    sources = (settlement.quote or {}).get("return_credit_sources", {})
    return (receipt.purpose == "presale_goods" and str(receipt.id) in sources
            and any(p.get("receipt_id") == receipt.id and p.get("component") == application.component
                    and p.get("purpose") == "presale_advance"
                    for p in (settlement.quote or {}).get("pool_applications", [])))


def projection(db, invoice, *, current=False):
    result = {"reductions": {}, "refunds": {}, "releases": {}, "credits": {}, "credit_used": {},
              "credit_returns": {}, "returned_batches": set(), "version": [], "issues": {}, "uncollected_excess": {}}
    if invoice is None:
        raise ValueError("预售资金所属订单不存在，请核对原批次")
    if invoice.order_type != "presale" or not invoice.xiaoman_order_id:
        return result
    returns = _rows(db.query(SalesReturn).filter(SalesReturn.order_id == str(invoice.xiaoman_order_id),
                                                SalesReturn.status == "effective").order_by(SalesReturn.id), current)
    if not returns:
        batches = _rows(db.query(ShipmentSettlement).filter(ShipmentSettlement.invoice_id == invoice.id), current)
        credit_batches = [b.id for b in batches if (b.quote or {}).get("return_credit_sources")]
        if credit_batches:
            owners = {batch.id: batch for batch in batches}
            applications = _rows(db.query(SettlementApplication, Receipt).join(Receipt,
                Receipt.id == SettlementApplication.receipt_id).filter(
                SettlementApplication.settlement_id.in_(credit_batches), SettlementApplication.status != "released"), current)
            if any(credit_application(owners[app.settlement_id], app, receipt) for app, receipt in applications):
                raise ValueError("后批仍占用退货信用，不能冲销或释放原退货依据")
        return result
    documents = {r.id: r for r in returns}
    if any(r.invoice_id != invoice.id or r.customer_id != invoice.customer_id or r.currency != invoice.currency for r in returns):
        raise ValueError("预售退货的订单、客户或币种不一致，请核对原退货单")
    items = _rows(db.query(ReturnItem).filter(ReturnItem.return_id.in_(documents)).order_by(ReturnItem.id), current)
    allocations = _rows(db.query(ReturnAllocation).filter(ReturnAllocation.return_id.in_(documents)).order_by(ReturnAllocation.id), current)
    outbounds = _rows(db.query(ShipmentOutbound).filter(ShipmentOutbound.invoice_id == invoice.id).order_by(ShipmentOutbound.id), current)
    by_outbound = {str(o.remote_id): o for o in outbounds if o.remote_id}
    settlements = {r.id: r for r in _rows(db.query(ShipmentSettlement).filter(ShipmentSettlement.invoice_id == invoice.id)
                                        .order_by(ShipmentSettlement.id), current)}
    receipts = {r.id: r for r in _rows(db.query(Receipt).filter(Receipt.invoice_id == invoice.id).order_by(Receipt.id), current)}
    by_remote = {str(r.xiaoman_receipt_id): r for r in receipts.values() if r.xiaoman_receipt_id}
    applications = _rows(db.query(SettlementApplication).filter(SettlementApplication.settlement_id.in_(settlements))
                         .order_by(SettlementApplication.id), current)
    reduction = defaultdict(lambda: ZERO)
    doc_reduction = defaultdict(lambda: ZERO)
    refunds = defaultdict(lambda: ZERO)
    refund_edges = defaultdict(lambda: ZERO)
    doc_refund = defaultdict(lambda: ZERO)
    batch_returns = defaultdict(set)
    for item in items:
        frozen = item.source_snapshot or {}
        outbound = by_outbound.get(str(frozen.get("outbound_id", item.outbound_id)))
        if not outbound or outbound.settlement_id not in settlements:
            raise ValueError("退货原批次缺少精确出库资金映射，请核对该旧批次")
        batch = settlements[outbound.settlement_id]
        if batch.state != "shipped" or outbound.status != "shipped":
            raise ValueError("已退货原批次不能取消或释放资金，请核对原批次")
        value = Decimal(item.reduction_amount)
        reduction[batch.id] += value
        doc_reduction[item.return_id] += value
        batch_returns[batch.id].add(item.return_id)
    for allocation in allocations:
        receipt = by_remote.get(str(allocation.original_payment_id))
        if receipt is None:
            raise ValueError("退货原款缺少本地预售资金映射，请核对原款")
        funding = allocation.funding
        if not isinstance(funding, list) or not funding:
            raise ValueError("退货原款缺少批次资金分摊，请核对原退款")
        total = ZERO
        for part in funding:
            batch_id, value = int(part["settlement_id"]), Decimal(str(part["amount"]))
            if batch_id not in reduction or value < 0:
                raise ValueError("退款批次或金额与退货原批次不一致")
            refund_edges[(receipt.id, batch_id)] += value
            total += value
        if total != allocation.refund_amount:
            raise ValueError("退款资金分摊不完整，请核对原退款")
        refunds[receipt.id] += total
        doc_refund[allocation.return_id] += total
    for rid, row in documents.items():
        if doc_reduction[rid] != row.reduction_amount or doc_refund[rid] != row.refund_amount:
            raise ValueError("退货货款或退款与原批次冻结分摊不一致")
    release = defaultdict(lambda: ZERO)
    primary_release = defaultdict(lambda: ZERO)
    borrowed = defaultdict(lambda: ZERO)
    borrowed_release = defaultdict(lambda: ZERO)
    credit_returns = defaultdict(set)
    from app.invoice.shipment_payment_policy import receipt_effective
    for batch_id, d in reduction.items():
        batch = settlements[batch_id]
        quote = batch.quote or {}
        known_target = quote.get("funding_version") == 2 and quote.get("currency") == invoice.currency and all(
            key in quote for key in ("goods_amount", "packaging_amount", "handling_amount"))
        if known_target:
            goods = Decimal(quote["goods_amount"])
            target = goods + Decimal(quote["packaging_amount"]) + Decimal(quote["handling_amount"])
        else:
            result["issues"][batch_id] = "该退货旧批次缺少可核验的商品与费用拆分；仅保留已证明退款，额外信用待核对"
        if known_target and not ZERO <= d <= goods:
            raise ValueError("退货商品冲减超过原批次商品本金")
        linked = [a for a in applications if a.settlement_id == batch_id and a.status != "released" and a.component != "freight"]
        effective = [a for a in linked if a.receipt_id in receipts and receipt_effective(receipts[a.receipt_id])]
        if any(receipts[a.receipt_id].customer_id != invoice.customer_id
               or receipts[a.receipt_id].currency != invoice.currency
               or str(receipts[a.receipt_id].xiaoman_order_id) != str(invoice.xiaoman_order_id)
               or a.bank_charge < 0 or a.amount <= a.bank_charge for a in effective):
            raise ValueError("原批次商品资金身份或手续费不一致，请核对该旧批次")
        paid = sum((Decimal(a.amount) for a in effective), ZERO)
        batch_refund = sum((v for (rid, bid), v in refund_edges.items() if bid == batch_id), ZERO)
        to_release = max(batch_refund, d - max(ZERO, target - paid)) if known_target else batch_refund
        if known_target and sum((Decimal(a.amount) for a in linked), ZERO) - to_release > target - d:
            result["uncollected_excess"][batch_id] = "退货前未收预登记款超过该批净应收，请先核对或更正原款；禁止按原登记金额继续收款"
        # First retire the exact refunded source edges, never another receipt.
        for (rid, bid), amount in refund_edges.items():
            if bid != batch_id:
                continue
            left = amount
            for app in [a for a in effective if a.receipt_id == rid]:
                used = min(left, Decimal(app.amount) - Decimal(app.bank_charge))
                release[app.id] += used
                left -= used
            if left:
                raise ValueError("退款超过原批次实际商品本金，不能复用原资金")
        left = to_release - batch_refund
        for app in reversed(effective):
            used = min(left, Decimal(app.amount) - Decimal(app.bank_charge) - release[app.id])
            release[app.id] += used
            left -= used
        if left:
            raise ValueError("原批次商品与手续费资金无法确证，请核对该批次")
    for app in applications:
        receipt = receipts.get(app.receipt_id)
        if receipt is None or app.status == "released":
            continue
        batch = settlements[app.settlement_id]
        if receipt.purpose == "presale_goods":
            if credit_application(batch, app, receipt):
                borrowed[receipt.id] += Decimal(app.amount)
                borrowed_release[receipt.id] += release[app.id]
            else:
                primary_release[receipt.id] += release[app.id]
                if release[app.id]:
                    credit_returns[receipt.id].update(batch_returns[batch.id])
    for rid, released in primary_release.items():
        credit = released - refunds[rid]
        used = borrowed[rid] - borrowed_release[rid]
        if credit < 0 or used < 0 or used > credit:
            raise ValueError("退货信用余额已被后批占用，不能恢复、冲销或重复释放原资金")
        result["credits"][rid] = credit
        result["credit_used"][rid] = used
        result["credit_returns"][rid] = sorted(credit_returns[rid])
    # A borrowed credit without its still-effective original return is invalid.
    if set(borrowed) - set(primary_release):
        raise ValueError("后批退货信用的原退货依据已失效，请核对原资金")
    for app in applications:
        receipt = receipts.get(app.receipt_id)
        if receipt is None or app.status == "released":
            continue
        owner = settlements[app.settlement_id]
        if credit_application(owner, app, receipt):
            expected = owner.quote["return_credit_sources"][str(receipt.id)].get("return_ids")
            if (not isinstance(expected, list) or not expected
                    or not set(expected).issubset(credit_returns[receipt.id])):
                raise ValueError("后批仍引用已失效退货信用，不能冲销或释放原退货依据")
    result.update(reductions=dict(reduction), refunds=dict(refunds), releases=dict(release),
                  returned_batches=set(reduction), receipts=receipts, applications=applications,
                  settlements=settlements)
    result["version"] = [[r.id, r.version, str(r.reduction_amount), str(r.refund_amount)] for r in returns]
    return result


def project_pool(db, invoice, receipts, lots, *, current=False):
    data = projection(db, invoice, current=current)
    if not data["returned_batches"]:
        return receipts, lots
    result = []
    for lot in lots:
        refund = data["refunds"].get(lot.receipt_id, ZERO)
        released = sum((data["releases"].get(a.id, ZERO) for a in data["applications"] if a.receipt_id == lot.receipt_id), ZERO)
        amount, allocated = Decimal(lot.amount) - refund, Decimal(lot.allocated_amount) - released
        if amount < allocated or allocated < 0 or amount < Decimal(lot.bank_charge):
            raise ValueError("退货原款净资金已超分配，请核对原批次")
        if amount == Decimal(lot.bank_charge):
            continue
        result.append(FundingLot(lot.receipt_id, lot.purpose, str(amount), lot.bank_charge,
                                 str(allocated), lot.allocated_charge, lot.effective))
    known = {r.id for r in receipts}
    for rid, credit in data["credits"].items():
        if credit <= 0:
            continue
        receipt = data["receipts"][rid]
        if rid not in known:
            receipts = receipts + [receipt]
        result.append(FundingLot(rid, "presale_advance", str(credit), "0", str(data["credit_used"][rid]), "0", True, goods_only=True))
    return receipts, result


def credit_sources(db, invoice, receipt_ids, *, current=False):
    data = projection(db, invoice, current=current)
    return {str(rid): {"return_ids": data["credit_returns"][rid]} for rid in receipt_ids if rid in data["credits"]}


def validate_credit(db, settlement, application, receipt, *, current=False):
    if not credit_application(settlement, application, receipt):
        return False
    from app.invoice.models import Invoice
    invoice = db.get(Invoice, settlement.invoice_id)
    data = projection(db, invoice, current=current)
    expected = settlement.quote["return_credit_sources"][str(receipt.id)]
    if (receipt.id not in data["credits"] or not set(expected.get("return_ids", []))
            or not set(expected["return_ids"]).issubset(data["credit_returns"][receipt.id])
            or receipt.invoice_id != invoice.id or receipt.customer_id != invoice.customer_id
            or receipt.currency != invoice.currency or application.bank_charge or application.component != "goods"):
        raise ValueError("后批退货信用与原款或原退货依据不一致")
    return True


def ensure_releasable(db, settlement, *, current=False):
    from app.invoice.models import Invoice
    if settlement.id in projection(db, db.get(Invoice, settlement.invoice_id), current=current)["returned_batches"]:
        raise ValueError("原批次已有生效退货，不能整体取消或释放退款资金")
