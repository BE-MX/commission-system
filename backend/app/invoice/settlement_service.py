"""Order-locked presale settlements. No remote writes in request transactions."""
import hashlib
import json
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from app.invoice.models import Invoice
from app.invoice.service import get_invoice
from app.invoice.settlement_models import (ShipmentSettlement, SettlementItem, Receivable,
    SettlementApplication, ShipmentOutbound, SettlementEvent)
from app.invoice.settlement_pricing import quote_settlement
from app.invoice.settlement_policy import require_enabled, capabilities
from app.receipt import access, remote, service as receipts
from app.receipt.models import Receipt


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def get_order(db, identity, user, *, lock=False, writable=True):
    invoice = get_invoice(db, identity, for_update=lock)
    if not invoice:
        raise HTTPException(404, "订单不存在")
    access.ensure_invoice(db, invoice, user)
    if invoice.order_type != "presale":
        raise ValueError("仅预售单支持分批发货结算")
    if writable:
        receipts.ensure_order_ready(db, invoice)
    if invoice.shipping_fee:
        raise ValueError("预售主单运费必须为零")
    return invoice


def _current(query, enabled, *order):
    if enabled:
        return query.order_by(*order).populate_existing().with_for_update()
    return query


def deposit_for(db, invoice, *, current=False):
    query = db.query(Receipt).filter(Receipt.invoice_id == invoice.id,
        Receipt.purpose == "presale_deposit", Receipt.status == "active")
    rows = _current(query, current, Receipt.id).all()
    if len(rows) != 1:
        raise ValueError("预售首款尚未生成或身份异常，请先核对预付款")
    return rows[0]


def goods_balance(db, invoice, snapshot, *, current=False):
    """An unallocated remote payment cannot silently become batch funding."""
    from app.receipt.balance import calculate
    result = calculate(db, invoice, snapshot, current=current)
    query = db.query(Receipt).filter(Receipt.invoice_id == invoice.id, Receipt.status == "active",
        Receipt.purpose != "freight", Receipt.xiaoman_receipt_id.isnot(None))
    if current:
        query = query.order_by(Receipt.id).populate_existing().with_for_update()
    mapped = {r.xiaoman_receipt_id for r in query.all()}
    if any(str(r["cash_collection_id"]) not in mapped for r in snapshot["rows"]):
        raise ValueError("预售主单存在未分配的远端回款，请先核对，不能重复登记")
    if Decimal(result["remaining_amount"]) < 0:
        raise ValueError("预售主单回款已超额，请先核对")
    return result


def fetch_evidence(db, invoice):
    from app.invoice.linked_outbound_service import find_related
    snapshot = remote.order_snapshot(db, invoice)
    order = remote.read(db, "/v1/invoices/order/info", {"order_id": invoice.xiaoman_order_id})
    if not remote.order_active(db, order):
        raise ValueError("小满预售主单已删除或活动列表未确认，请先核对原单")
    evidence = {"receipt": snapshot, "order": order, "outbounds": find_related(db, order),
                "freight": {}}
    shipped = db.query(ShipmentSettlement.id).filter_by(invoice_id=invoice.id, state="shipped").all()
    for (settlement_id,) in shipped:
        target = db.query(Receivable).filter_by(settlement_id=settlement_id, kind="freight").first()
        if target:
            evidence["freight"][settlement_id] = remote.target_snapshot(db, target)
    return evidence


def check_shipped_funding(db, invoice, evidence, shipped, *, current=False):
    """Prior physically shipped batches must retain their exact active funding."""
    from app.receipt.balance import calculate_target

    goods_rows = {str(row["cash_collection_id"]): row for row in evidence["receipt"]["rows"]}
    for settlement in shipped:
        freight = _current(db.query(Receivable).filter_by(settlement_id=settlement.id, kind="freight"), current, Receivable.id).first()
        freight_rows = {}
        if freight:
            snapshot = evidence.get("freight", {}).get(settlement.id)
            if snapshot is None:
                raise ValueError("历史运费回款尚未实时核验，不能继续安排")
            calculate_target(db, freight, snapshot, current=current)
            freight_rows = {str(row["cash_collection_id"]): row for row in snapshot["rows"]}
        applications = db.query(SettlementApplication, Receipt).join(
            Receipt, Receipt.id == SettlementApplication.receipt_id).filter(
            SettlementApplication.settlement_id == settlement.id,
            SettlementApplication.status != "released")
        applications = _current(applications, current, SettlementApplication.id, Receipt.id).all()
        expected = Decimal(settlement.quote["new_payment_due"]) + Decimal(settlement.quote["deposit_applied"])
        if sum((Decimal(app.amount) for app, _ in applications), Decimal(0)) != expected:
            raise ValueError("历史已出库批次的资金分配已变化，不能继续安排")
        for app, receipt in applications:
            rows = freight_rows if app.component == "freight" else goods_rows
            remote_row = rows.get(str(receipt.xiaoman_receipt_id))
            if (app.status != "applied" or receipt.status != "active"
                    or receipt.sync_status != "synced" or receipt.collect_status != 1
                    or receipt.last_error or not remote_row
                    or str(remote_row.get("collect_status")) != "1"):
                raise ValueError("历史已出库批次的回款已失效，不能继续安排")
        balance = funding_balance(db, settlement, current=current)
        if (Decimal(balance["remaining_amount"]) != 0
                or Decimal(balance["effective_amount"]) != expected):
            raise ValueError("历史已出库批次回款不足，不能继续安排")


def check_outbounds(db, invoice, evidence, *, pending=None, current=False):
    known = db.query(ShipmentOutbound).filter(ShipmentOutbound.invoice_id == invoice.id,
        ShipmentOutbound.remote_id.isnot(None))
    known = _current(known, current, ShipmentOutbound.id).all()
    live = {str(x["outbound_invoice_id"]): x for x in evidence["outbounds"]}
    if set(live) != {x.remote_id for x in known}:
        raise ValueError("存在尚未核对的远端出库，请先核对出库数量，不能继续安排")
    for outbound in known:
        if pending and outbound.id == pending.id:
            if str(live[outbound.remote_id].get("status")) != "1":
                raise ValueError("当前待出库单状态已变化，请先核对原单")
            continue
        if outbound.status != "shipped" or str(live[outbound.remote_id].get("status")) != "2":
            raise ValueError("前批尚未确认实际出库，请先完成前批")
        expected = {str(x["order_record_id"]): int(x["outbound_count"]) for x in outbound.payload["record_list"]}
        rows = live[outbound.remote_id].get("record_list", [])
        if len(rows) != len(expected) or any(str(x.get("order_id")) != invoice.xiaoman_order_id for x in rows):
            raise ValueError("远端出库明细关联已变化")
        actual = {str(x.get("order_record_id")): Decimal(str(x.get("outbound_count"))) for x in rows}
        if actual != expected:
            raise ValueError("远端出库数量已变化")


def build_quote(db, invoice, body, evidence, *, current=False):
    remote_line_ids = set()
    for item in invoice.items:
        if not item.product_id or not item.sku_id or not item.xiaoman_unique_id:
            raise ValueError("预售分批出库暂不支持未映射到独立 OKKI 产品行的明细")
        identity = str(item.xiaoman_unique_id)
        if identity in remote_line_ids:
            raise ValueError("预售分批出库暂不支持共享 OKKI 明细的通用产品合并行")
        remote_line_ids.add(identity)
    active = db.query(ShipmentSettlement.id).filter(ShipmentSettlement.invoice_id == invoice.id,
        ShipmentSettlement.state.notin_(["shipped", "cancelled"]))
    active = _current(active, current, ShipmentSettlement.id).first()
    if active:
        raise ValueError("已有未完成的活动发货结算，请先处理原批次")
    check_outbounds(db, invoice, evidence, current=current)
    deposit = deposit_for(db, invoice, current=current)
    # A changed/missing remote payment freezes new allocations too.
    available = goods_balance(db, invoice, evidence["receipt"], current=current)
    shipped = _current(db.query(ShipmentSettlement).filter_by(invoice_id=invoice.id, state="shipped"), current, ShipmentSettlement.id).all()
    check_shipped_funding(db, invoice, evidence, shipped, current=current)
    if current:
        quantities = {}
        prior_items = _current(db.query(SettlementItem).filter(SettlementItem.settlement_id.in_([row.id for row in shipped])), True, SettlementItem.id).all()
        for item in prior_items:
            quantities[item.invoice_item_id] = quantities.get(item.invoice_item_id, 0) + item.quantity
    else:
        quantities = dict(db.query(SettlementItem.invoice_item_id, func.sum(SettlementItem.quantity)).join(
            ShipmentSettlement, ShipmentSettlement.id == SettlementItem.settlement_id).filter(
            ShipmentSettlement.invoice_id == invoice.id, ShipmentSettlement.state == "shipped"
        ).group_by(SettlementItem.invoice_item_id).all())
    requested = {x.invoice_item_id: x.quantity for x in body.items}
    if set(requested) - {x.id for x in invoice.items}:
        raise ValueError("产品明细不属于本订单")
    lines = [{"invoice_item_id": x.id, "quantity": x.quantity, "total_price": str(x.total_price),
              "shipped_quantity": int(quantities.get(x.id, 0)), "requested_quantity": requested.get(x.id, 0)}
             for x in invoice.items]
    result = quote_settlement(lines, invoice.internal_accessory or 0, invoice.surcharge_amount or 0,
        deposit.amount, deposit.bank_charge, sum((Decimal(x.quote["packaging_amount"]) for x in shipped), Decimal(0)),
        sum((Decimal(x.quote["handling_amount"]) for x in shipped), Decimal(0)), freight=body.freight_amount)
    if Decimal(result["goods_payment_due"]) > Decimal(available["remaining_amount"]):
        raise ValueError("本批商品款超过主单可回款余额，请先核对历史资金分配")
    result.update(invoice_id=invoice.id, currency=invoice.currency, customer_id=invoice.customer_id,
                  invoice_no=invoice.invoice_no, deposit_receipt_id=deposit.id,
                  delivery_address=invoice.delivery_address, remark=invoice.remark)
    result["quote_hash"] = digest({"quote": result, "lines": lines, "evidence": evidence,
                                   "deposit": [deposit.id, deposit.version, str(deposit.amount), str(deposit.bank_charge)]})
    result["capabilities"] = capabilities()
    return result


def quote(db, invoice_id, body, user):
    from app.invoice.shipment_quote_service import quote as current_quote
    return current_quote(db,invoice_id,body,user)


def target(db, invoice, settlement=None, *, current=False):
    key = f"settlement:{settlement.id}:freight" if settlement else f"invoice:{invoice.id}:goods"
    query = db.query(Receivable).filter_by(business_key=key)
    if current:
        query = query.populate_existing().with_for_update()
    row = query.first()
    if row is None:
        row = Receivable(invoice_id=invoice.id, settlement_id=settlement.id if settlement else None,
            business_key=key, kind="freight" if settlement else "goods", currency=invoice.currency,
            customer_id=invoice.customer_id, amount=settlement.quote["freight_amount"] if settlement else invoice.total_amount,
            handling_amount=0 if settlement else invoice.surcharge_amount or 0,
            remote_order_id=None if settlement else invoice.xiaoman_order_id,
            remote_order_name=f"{settlement.settlement_no}-F" if settlement else None,
            remote_status="unverified" if settlement else "bound")
        db.add(row); db.flush()
    return row


def application(db, settlement, row, component, amount, charge):
    reserved_rows = db.scalars(select(SettlementApplication).where(
        SettlementApplication.receipt_id == row.id, SettlementApplication.status != "released")
        .order_by(SettlementApplication.id).with_for_update().execution_options(populate_existing=True)).all()
    reserved = (sum((app.amount for app in reserved_rows), Decimal(0)),
                sum((app.bank_charge for app in reserved_rows), Decimal(0)))
    if Decimal(reserved[0]) + Decimal(amount) > row.amount or Decimal(reserved[1]) + Decimal(charge) > row.bank_charge:
        raise ValueError("资金已被其他结算占用")
    db.add(SettlementApplication(settlement_id=settlement.id, receipt_id=row.id, component=component,
        amount=amount, bank_charge=charge))
    db.flush()


def create(db, invoice_id, body, user):
    from app.invoice.shipment_create_service import create as authorized_create
    return authorized_create(db, invoice_id, body, user)


def _create_verified(db, invoice, body, user, evidence, proof_evidence):
    """Local application only; current authority and immutable evidence held by caller."""
    from app.receipt import batch_service
    actor, fingerprint = access.user_id(user), digest(body.model_dump(mode="json"))
    calculated = build_quote(db, invoice, body, evidence, current=True)
    if calculated["quote_hash"] != body.quote_hash:
        raise ValueError("QUOTE_STALE：订单或余额已变化，请刷新报价")
    prior = _current(db.query(ShipmentSettlement).filter_by(invoice_id=invoice.id), True, ShipmentSettlement.id).all()
    sequence = max((item.sequence for item in prior), default=0) + 1
    row = ShipmentSettlement(invoice_id=invoice.id, sequence=sequence,
        settlement_no=f"{invoice.invoice_no}-{sequence:02d}", is_final=int(calculated["is_final"]),
        quote=calculated, quote_hash=body.quote_hash, request_key=body.request_key,
        request_hash=fingerprint, created_by=actor)
    db.add(row); db.flush()
    originals = {x.id: x for x in invoice.items}
    for line in calculated["items"]:
        item = originals[line["invoice_item_id"]]
        if not line["quantity"]:
            continue
        if not item.xiaoman_unique_id:
            raise ValueError("小满产品行身份缺失，请先同步订单")
        db.add(SettlementItem(settlement_id=row.id, invoice_item_id=item.id, quantity=line["quantity"],
            line_amount=line["line_amount"], snapshot={"order_id": invoice.xiaoman_order_id,
                "order_record_id": item.xiaoman_unique_id, "product_id": item.product_id, "sku_id": item.sku_id,
                "product_name": item.product_name, "outbound_count": line["quantity"],
                "sale_price": str(item.price_per_piece or 0)}))
    target(db, invoice)
    if body.freight_amount:
        target(db, invoice, row)
    if row.is_final:
        deposit = deposit_for(db, invoice, current=True)
        application(db, row, deposit, "deposit", deposit.amount, deposit.bank_charge)
    db.add(SettlementEvent(settlement_id=row.id, action="created", actor_id=actor))
    if body.payment:
        if body.payment.bank_charge:
            raise ValueError("手续费由本批自动分摊，请勿重复填写")
        batch_service._register_shipment_payment_verified(db, invoice, row, body.payment, actor, body.request_key, proof_evidence)
    return row


def funding_balance(db, row, *, current=False):
    query = db.query(SettlementApplication, Receipt).join(Receipt,
        Receipt.id == SettlementApplication.receipt_id).filter(SettlementApplication.settlement_id == row.id,
        SettlementApplication.status != "released")
    if current:
        query = query.order_by(SettlementApplication.id, Receipt.id).populate_existing().with_for_update()
    applications = query.all()
    goods = freight = charge = effective = Decimal(0)
    for app, receipt in applications:
        if receipt.status != "active":
            raise ValueError("本批关联回款已失效，请核对")
        if app.component != "deposit":
            if app.component == "goods":
                goods += app.amount; charge += app.bank_charge
            else:
                freight += app.amount
        if receipt.sync_status == "synced" and receipt.collect_status == 1 and not receipt.last_error:
            effective += app.amount
    result = {"settlement_id": row.id, "goods_remaining": str(Decimal(row.quote["goods_payment_due"]) - goods),
        "freight_remaining": str(Decimal(row.quote["freight_amount"]) - freight),
        "charge_remaining": str(Decimal(row.quote["goods_payment_charge"]) - charge),
        "effective_amount": str(effective), "registered_amount": str(goods + freight),
        "remaining_amount": str(Decimal(row.quote["new_payment_due"]) - goods - freight),
        "currency": row.quote["currency"], "total_amount": row.quote["new_payment_due"]}
    result["version"] = digest({"balance": result, "state": row.state, "version": row.version,
        "receipts": [(r.id, r.version, r.sync_status, r.collect_status, r.status) for _, r in applications]})
    return result


def get(db, identity, user, *, lock=False):
    row = db.get(ShipmentSettlement, identity)
    if not row:
        raise HTTPException(404, "发货结算不存在")
    invoice_id = row.invoice_id
    if lock:
        db.commit()  # End the initial identity lookup snapshot before locking.
    get_order(db, invoice_id, user, lock=lock, writable=lock)
    if lock:
        db.refresh(row, with_for_update=True)
    return row


def describe(db, row, *, current=False):
    outbound = _current(db.query(ShipmentOutbound).filter_by(settlement_id=row.id), current, ShipmentOutbound.id).first()
    freight = _current(db.query(Receivable).filter_by(settlement_id=row.id, kind="freight"), current, Receivable.id).first()
    invalid_funding=False
    if outbound and outbound.status=="shipped_unfunded":
        query=db.query(SettlementApplication,Receipt).join(Receipt,Receipt.id==SettlementApplication.receipt_id).filter(
            SettlementApplication.settlement_id==row.id,SettlementApplication.status!="released")
        if current:query=query.order_by(SettlementApplication.id,Receipt.id).populate_existing().with_for_update()
        invalid_funding=any(receipt.status!="active" for _,receipt in query.all())
    summary=None if invalid_funding else funding_balance(db,row,current=current)
    result={"id": row.id, "invoice_id": row.invoice_id, "settlement_no": row.settlement_no,
        "state": row.state, "version": row.version, "quote": row.quote, "balance": summary,
        "outbound": {"id": outbound.id, "status": outbound.status, "number": outbound.outbound_no,
                     "remote_id": outbound.remote_id, "last_error": outbound.last_error} if outbound else None,
        "freight_target": {"id": freight.id, "status": freight.remote_status,
                           "remote_order_id": freight.remote_order_id,
                           "last_error": freight.last_error} if freight else None,
        "capabilities": capabilities()}
    if outbound:
        from app.invoice import shipment_confirmation_recovery
        result["outbound"]["confirmation"] = shipment_confirmation_recovery.summary(db,outbound,current=current)
    if invalid_funding:
        result["balance_error"]="本批关联回款已失效，余额暂不可计算，请核对原单"
    return result


def _change_state_verified(db, row, user, action, version, reason, graph):
    """Pure local state algorithm; current authority/bindings are caller-owned."""
    if row.version != version:
        raise ValueError("结算已变化，请刷新")
    if row.state in {"shipped", "cancelled", "outbound_uncertain", "review_required"}:
        raise ValueError("当前结算状态不能执行此操作")
    if graph.outbound:
        raise ValueError("已有出库任务，请先核实远端效果")
    freight = graph.freight
    if freight and freight.remote_status in {"sending", "verifying", "uncertain"}:
        raise ValueError("运费目标正在发送或结果待核对，请先核实远端效果")
    if any(app.status != "released" and graph.receipts[app.receipt_id].sync_status in {"syncing", "uncertain"}
            for app in graph.applications):
        raise ValueError("本批回款正在发送或结果待核对，请先核实远端效果")
    if action == "cancel":
        paid = any(app.component != "deposit" and app.status != "released" for app in graph.applications)
        if paid or (freight and (freight.remote_order_id or freight.remote_status in {
                "sending", "verifying", "uncertain", "bound"})):
            raise ValueError("已有真实付款或运费目标，仅支持原批暂停/恢复")
        for app in graph.applications:
            app.status = "released"
        row.state = "cancelled"
    elif action == "pause":
        row.state = "paused"
    elif action == "resume" and row.state == "paused":
        row.state = "awaiting_verification" if Decimal(graph.balance["remaining_amount"]) == 0 else "awaiting_payment"
    else:
        raise ValueError("无效的结算状态变更")
    row.version += 1
    db.add(SettlementEvent(settlement_id=row.id, action=action, reason=reason, actor_id=access.user_id(user)))
