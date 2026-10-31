"""Local batch settlement and physical dispatch on the existing invoice ledger.

Every mutation is savepoint atomic and caller committed. Finance book -> order
serializes cash with dispatch; all warehouse locks precede stock consumption.
"""
from datetime import date
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select
from app.core.time import beijing_now
from app.customer.transaction_identity import invoice_key
from app.finance import service as finance
from app.inventory.reservation_service import consume_line, reserve_line
from app.inventory.models import StockReservation
from app.inventory.service import _lock_warehouses
from app.invoice import commerce_service as commerce, local_funding as funding
from app.invoice.models import Invoice
from app.invoice.local_fulfillment_schemas import LocalShipmentAudit
from app.invoice.settlement_models import ShipmentSettlement, SettlementItem, ShipmentOutbound, SettlementEvent, Receivable
from app.invoice.settlement_pricing import quote_settlement, _cents, _round_ratio, _format
from app.invoice.settlement_service import digest
from app.shipping_inspection.models import ShippingInspection
from app.commerce_shadow.hooks import observe_command


def record_id(outbound):
    return f"local-{outbound.id}"


def _order(db, invoice_id, user):
    finance.book(db)
    invoice = commerce._get(db, invoice_id, user)
    if invoice.commerce_status not in {"confirmed", "partially_shipped", "shipped"}:
        raise ValueError("仅已确认的本地订单可以安排发货")
    return invoice


def _settlements(db, invoice):
    return db.scalars(select(ShipmentSettlement).where(ShipmentSettlement.invoice_id == invoice.id)
        .order_by(ShipmentSettlement.sequence).with_for_update().execution_options(populate_existing=True)).all()


def _quote(db, invoice, body, rows, targets):
    settlements = _settlements(db, invoice)
    if any(row.state not in {"shipped", "cancelled"} for row in settlements):
        raise ValueError("已有未完成发货批次，请先完成或取消")
    shipped = [row for row in settlements if row.state == "shipped"]
    requested = {line.invoice_item_id: line.quantity for line in body.items}
    if set(requested) - {item.id for item in invoice.items}:
        raise ValueError("发货明细不属于该订单")
    presale = invoice.order_type == "presale"
    if presale and funding.deposit_totals(rows) != (invoice.local_deposit_amount, invoice.local_deposit_charge):
        raise ValueError("合同首款尚未全部确认并核销，请先补齐首款")
    lines = [dict(invoice_item_id=item.id, quantity=item.quantity, total_price=str(item.total_price),
                  shipped_quantity=item.stock_shipped_quantity, requested_quantity=requested.get(item.id, 0)) for item in invoice.items]
    prior_packaging = sum((Decimal(row.quote["packaging_amount"]) for row in shipped), Decimal(0))
    prior_handling = sum((Decimal(row.quote["handling_amount"]) for row in shipped), Decimal(0))
    opening_history = any(row.quote.get('opening_record_id') is not None for row in shipped)
    allow_free_replacement = False
    if not presale and invoice.product_amount == 0:
        from app.aftersales.models import AfterSalesExecution
        allow_free_replacement = db.scalar(select(AfterSalesExecution.id).where(
            AfterSalesExecution.related_invoice_id == invoice.id,
            AfterSalesExecution.action.in_(["replacement", "resend"])).limit(1).with_for_update()) is not None
        if not allow_free_replacement:
            raise ValueError("零货值发货必须关联最终批准的售后补发方案")
    if opening_history:
        from app.invoice.opening_pricing import quote_remaining
        apps = funding.applications(db, invoice)
        used_deposit = sum((app.effective_amount for app in apps if app.component == 'deposit' and app.status == 'applied'), Decimal(0))
        used_deposit_fee = sum((app.effective_bank_charge for app in apps if app.component == 'deposit' and app.status == 'applied'), Decimal(0))
        result = quote_remaining(invoice, requested, shipped, freight=body.freight_amount,
            deposit_remaining=invoice.local_deposit_amount - used_deposit if presale else 0,
            deposit_charge_remaining=invoice.local_deposit_charge - used_deposit_fee if presale else 0)
    else:
        result = quote_settlement(lines, invoice.internal_accessory or 0, invoice.surcharge_amount or 0,
            invoice.local_deposit_amount if presale else 0, invoice.local_deposit_charge if presale else 0,
            prior_packaging, prior_handling, freight=body.freight_amount if presale else 0, allow_zero_deposit=not presale, allow_zero_goods=allow_free_replacement)
    if not presale and not opening_history:
        if body.freight_amount:
            raise ValueError("普通订单运费从合同自动分摊，不能重复登记")
        goods = _cents(invoice.product_amount, "goods")
        prior_goods = sum(_round_ratio(_cents(item.total_price, "line") * item.stock_shipped_quantity, item.quantity) for item in invoice.items)
        freight = _cents(invoice.shipping_fee, "freight")
        if goods == 0 and freight:
            raise ValueError("免费补发不向客户计收运费，请使用正常收费订单登记客户承担部分")
        batch_freight = 0 if goods == 0 else _round_ratio(freight * (prior_goods + _cents(result["goods_amount"], "batch")), goods) - _round_ratio(freight * prior_goods, goods)
        result["freight_amount"] = _format(batch_freight)
        result["new_payment_due"] = str(finance.money(Decimal(result["goods_payment_due"]) + Decimal(result["freight_amount"])))
    result.update(invoice_id=invoice.id, currency=invoice.currency, customer_id=invoice_key(db, invoice, lock=True),
                  invoice_no=invoice.invoice_no, warehouse_id=body.warehouse_id, commerce_version=invoice.commerce_version,
                  delivery_address=invoice.delivery_address, remark=invoice.remark, business_date=body.business_date.isoformat())
    result["quote_hash"] = digest(result)
    return result


def quote(db, invoice_id, body, user):
    invoice = _order(db, invoice_id, user)
    rows, targets = funding.sources(db, invoice)
    return _quote(db, invoice, body, rows, targets)


@observe_command('shipment.create', target_arg='invoice_id', invoice_arg='invoice_id')
def create(db, invoice_id, body, user):
    with db.begin_nested():
        invoice = _order(db, invoice_id, user)
        event, fresh = commerce._claim(db, "shipment_create", body, user, invoice.id)
        if not fresh:
            return finance.lock(db, ShipmentSettlement, event.payload["settlement_id"])
        commerce._version(invoice, body)
        funding.ensure_event_date(db, invoice.id, body.business_date)
        finance.open_date(finance.book(db), body.business_date)
        if body.business_date < invoice.invoice_date:
            raise ValueError("发货结算日期不能早于订单日期")
        rows, targets = funding.sources(db, invoice)
        calculated = _quote(db, invoice, body, rows, targets)
        if body.quote_hash != calculated["quote_hash"]:
            raise ValueError("QUOTE_STALE：发货报价已变化，请刷新")
        _lock_warehouses(db, [body.warehouse_id])
        sequence = max((row.sequence for row in _settlements(db, invoice)), default=0) + 1
        row = ShipmentSettlement(invoice_id=invoice.id, sequence=sequence, settlement_no=f"{invoice.invoice_no}-{sequence:02d}",
            state="awaiting_payment", is_final=int(calculated["is_final"]), quote=calculated, quote_hash=body.quote_hash,
            request_key=body.request_key, request_hash=event.request_hash, created_by=commerce._actor(user))
        db.add(row)
        db.flush()
        originals = {item.id: item for item in invoice.items}
        snapshots = []
        for line in calculated["items"]:
            item = originals[line["invoice_item_id"]]
            snapshot = dict(invoice_item_id=item.id, local_sku_id=item.local_sku_id, product_name=item.product_name,
                model=item.model, color=item.color, size=item.length, qty=line["quantity"], unit="Piece", product_kind=item.product_kind,
                price=str(item.price_per_piece), line_amount=line["line_amount"])
            db.add(SettlementItem(settlement_id=row.id, invoice_item_id=item.id, quantity=line["quantity"],
                                   line_amount=line["line_amount"], snapshot=snapshot))
            snapshots.append(snapshot)
        if invoice.order_type == "presale" and Decimal(calculated["freight_amount"]):
            freight_target = Receivable(invoice_id=invoice.id, settlement_id=row.id, business_key=f"settlement:{row.id}:freight",
                kind="freight", amount=calculated["freight_amount"], handling_amount=0, currency=invoice.currency,
                customer_id=invoice_key(db, invoice, lock=True), remote_status="not_applicable")
            db.add(freight_target)
            db.flush()
            finance_event, _ = finance.claim(db, "create_freight", freight_target.id,
                body.model_copy(update={"request_key": f"freight-create:{event.id}"}), user, body.business_date)
            finance_event.receivable_id, finance_event.amount = freight_target.id, Decimal(calculated["freight_amount"])
            invoice.internal_balance = finance.money(invoice.internal_balance + Decimal(calculated["freight_amount"]))
        payload = dict(transaction_mode="local", warehouse_id=body.warehouse_id, invoice_id=invoice.id,
                       customer_name=invoice.customer_name, customer_id=invoice_key(db, invoice, lock=True),
                       owner_id=invoice.sales_user_id, owner_name=invoice.sales_user_name,
                       outbound_version=1, items=snapshots, delivery_address=invoice.delivery_address)
        outbound = ShipmentOutbound(settlement_id=row.id, invoice_id=invoice.id, outbound_no=row.settlement_no,
                                    status="local_pending", payload=payload, payload_hash=digest(payload))
        db.add(outbound)
        db.flush()
        event.payload = {**event.payload, "settlement_id": row.id, "outbound_id": outbound.id}
        db.add(SettlementEvent(settlement_id=row.id, action="created", reason="本地发货结算", actor_id=commerce._actor(user)))
        invoice.commerce_version += 1
        db.flush()
        return row


def _context(db, identity, user):
    seed = db.get(ShipmentSettlement, identity)
    if seed is None:
        raise HTTPException(404, "发货结算不存在")
    invoice = _order(db, seed.invoice_id, user)
    rows, targets = funding.sources(db, invoice)
    settlement = finance.lock(db, ShipmentSettlement, identity)
    outbound = db.scalar(select(ShipmentOutbound).where(ShipmentOutbound.settlement_id == identity)
                         .with_for_update().execution_options(populate_existing=True))
    if outbound is None or (outbound.payload or {}).get("transaction_mode") != "local":
        raise ValueError("不是本地发货批次")
    apps = funding.applications(db, invoice)
    return invoice, settlement, outbound, rows, targets, apps


@observe_command(lambda values: 'shipment.' + {'ship': 'dispatch'}.get(values['action'], values['action']), target_arg='identity')
def act(db, identity, body, user, action):
    with db.begin_nested():
        invoice, row, outbound, receipts, targets, apps = _context(db, identity, user)
        event, fresh = commerce._claim(db, f"shipment_{action}",
            LocalShipmentAudit(**body.model_dump(), settlement_id=identity, operation=action), user, invoice.id)
        if not fresh:
            return row
        if row.version != body.expected_version:
            raise ValueError("发货结算已变化，请刷新")
        finance.open_date(finance.book(db), body.business_date)
        if body.business_date < date.fromisoformat(row.quote["business_date"]):
            raise ValueError("操作日期不能早于发货结算生效日")
        funding.ensure_event_date(db, invoice.id, body.business_date, row.id)
        if action == "ready":
            if row.state != "awaiting_payment":
                raise ValueError("仅待付款结算可以放行资金")
            funding.fund(db, invoice, row, receipts, targets, apps, body.business_date)
            row.state, outbound.status = "ready", "local_ready"
        elif action == "release_funding":
            if row.state not in {"awaiting_payment", "ready"}:
                raise ValueError("已出库资金不能直接释放，请通过退货处理")
            for app in apps:
                if app.settlement_id == row.id and app.status == "reserved":
                    app.status = "released"
            row.state, outbound.status = "awaiting_payment", "local_pending"
        elif action == "cancel":
            if row.state not in {"awaiting_payment", "ready"}:
                raise ValueError("已出库结算必须通过退货处理")
            freight = next((target for target in targets.values() if target.settlement_id == row.id and target.kind == "freight"), None)
            if freight and freight.paid_amount:
                raise ValueError("本批运费已核销，请先释放资金占用并冲回核销")
            for app in apps:
                if app.settlement_id == row.id and app.status == "reserved":
                    app.status = "released"
            if freight:
                delta = finance.money(freight.amount + freight.adjustment_amount)
                if delta:
                    from app.finance.schemas import AdjustmentCreate
                    finance.adjust_receivable(db, freight.id, AdjustmentCreate(request_key=f"freight-cancel:{event.id}",
                        expected_version=freight.version, invoice_id=invoice.id, amount=-delta,
                        business_date=body.business_date, reason=body.reason), user)
            row.state, outbound.status = "cancelled", "local_cancelled"
        elif action == "ship":
            if row.state != "ready" or outbound.status != "local_ready":
                raise ValueError("请先完成本批资金放行")
            funding.validate(db, invoice, row, receipts, targets, apps, complete=True)
            inspection = db.scalar(select(ShippingInspection).where(ShippingInspection.outbound_record_id == record_id(outbound))
                                   .with_for_update().execution_options(populate_existing=True))
            if (inspection is None or inspection.status != "submitted" or body.inspection_version != inspection.edit_version
                    or inspection.local_outbound_id != outbound.id or inspection.local_outbound_version != outbound.payload["outbound_version"]):
                raise ValueError("请完成当前出库明细的发货检验并刷新版本")
            _lock_warehouses(db, [outbound.payload["warehouse_id"]])
            documents = []
            reservations = []
            for item in sorted(outbound.payload["items"], key=lambda item: item["invoice_item_id"]):
                if invoice.order_type in {"presale", "production"}:
                    responsibility = db.scalar(select(StockReservation).where(
                        StockReservation.invoice_item_id == item["invoice_item_id"],
                        StockReservation.warehouse_id == outbound.payload["warehouse_id"])
                        .with_for_update().execution_options(populate_existing=True))
                    missing = max(0, item["qty"] - (responsibility.reserved if responsibility else 0))
                    if missing:
                        reserved = reserve_line(db, item["invoice_item_id"], outbound.payload["warehouse_id"], missing,
                            f"dispatch-reserve:{event.id}:{item['invoice_item_id']}", commerce._actor(user))
                        reservations.append(reserved.id)
                document = consume_line(db, item["invoice_item_id"], outbound.payload["warehouse_id"], item["qty"],
                    f"shipment:{event.id}:{item['invoice_item_id']}", record_id(outbound), commerce._actor(user))
                documents.append(document.id)
            for app in apps:
                if app.settlement_id == row.id and app.status == "reserved":
                    app.status = "applied"
            row.state, outbound.status = "shipped", "local_shipped"
            outbound.verified_at = beijing_now()
            event.payload = {**event.payload, "stock_document_ids": documents, "stock_reservation_document_ids": reservations, "inspection_id": inspection.id,
                             "inspection_version": inspection.edit_version}
            invoice.commerce_status = "shipped" if all(item.stock_shipped_quantity == item.quantity for item in invoice.items) else "partially_shipped"
        else:
            raise ValueError("未知发货动作")
        if action in {"ready", "ship"}:
            used = {app.receipt_id for app in apps if app.settlement_id == row.id and app.status != "released"}
            if any(receipt.id in used and receipt.collection_date > body.business_date for receipt in receipts):
                raise ValueError("操作日期不能早于本批占用资金核销日期")
        row.version += 1
        outbound.version += 1
        invoice.commerce_version += 1
        event.payload = {**event.payload, "settlement_id": row.id, "outbound_id": outbound.id,
            "funding": [{"id": app.id, "receipt_id": app.receipt_id, "amount": str(app.amount), "fee": str(app.bank_charge),
                         "status": app.status} for app in apps if app.settlement_id == row.id]}
        db.add(SettlementEvent(settlement_id=row.id, action=action, reason=body.reason, actor_id=commerce._actor(user)))
        db.flush()
        return row


def describe(db, row, user=None):
    outbound = db.scalar(select(ShipmentOutbound).where(ShipmentOutbound.settlement_id == row.id))
    target = db.scalar(select(Receivable).where(Receivable.settlement_id == row.id, Receivable.kind == "freight"))
    inspection = db.scalar(select(ShippingInspection).where(ShippingInspection.local_outbound_id == outbound.id))
    current_inspection = bool(inspection and inspection.status == "submitted"
                              and inspection.outbound_record_id == record_id(outbound)
                              and inspection.local_outbound_version == outbound.payload["outbound_version"])
    invoice = db.get(Invoice, row.invoice_id)
    from app.invoice.transition_editor import describe as describe_transition
    ownership = describe_transition(db, invoice, user)
    permissions = set(user.get('permissions', [])) if user else set()
    administrator = bool(user and 'super_admin' in user.get('roles', []))
    writable = bool(administrator or 'shipment:write' in permissions)
    stock_write = bool(administrator or 'inventory:write' in permissions)
    active = ownership['authority_operable'] and ownership['transaction_route'] == 'local'
    pending = row.state in {'awaiting_payment', 'ready'}
    capabilities = {'ready': active and writable and row.state == 'awaiting_payment',
        'ship': active and writable and stock_write and row.state == 'ready' and current_inspection,
        'cancel': active and writable and pending, 'release_funding': active and writable and pending,
        'inspect': active and row.state not in {'shipped', 'cancelled'},
        'print': active and row.state != 'cancelled'}
    return dict(id=row.id, invoice_id=row.invoice_id, invoice_no=invoice.invoice_no,
        customer_name=invoice.customer_name, record_source='local_shipment',
        authority_epoch=ownership['authority_epoch'], capabilities=capabilities,
        settlement_no=row.settlement_no, state=row.state,
        version=row.version, quote=row.quote, freight_receivable_id=target.id if target else None,
        outbound_id=outbound.id, outbound_record_id=record_id(outbound), outbound_status=outbound.status,
        inspection_status=inspection.status if inspection else "none", inspection_current=current_inspection,
        inspection_version=inspection.edit_version if inspection else None)
