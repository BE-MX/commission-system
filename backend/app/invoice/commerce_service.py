"""Local lifecycle on the existing invoice aggregate; no OKKI transaction reads.

Every command is savepoint atomic and caller committed. Order locks precede all
warehouse locks. Bulk commands lock the complete sorted warehouse set first.
"""

import hashlib
import json
import logging
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import set_committed_value

from app.catalog.models import CatalogProduct, CatalogSku
from app.customer.access_service import require_customer_access, CustomerAccessDenied
from app.customer.models import CustomerAccount
from app.inventory.models import StockReservation
from app.inventory.reservation_service import reserve_line, release_line
from app.inventory.service import _lock_warehouses, _validate_skus
from app.invoice import delegation_service
from app.invoice.models import Invoice, InvoiceItem, InvoiceCommerceEvent
from app.invoice.settlement_models import Receivable, ShipmentSettlement
from app.receipt.models import Receipt
from app.commerce_shadow.hooks import observe_command

logger = logging.getLogger(__name__)
MONEY_LIMIT = Decimal("999999999999.99")


def _money(value):
    result = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if not result.is_finite() or abs(result) > MONEY_LIMIT:
        raise ValueError("金额超过可存储范围")
    return result


def _actor(user):
    try:
        return int(user["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(403, "无法确认用户身份") from exc


def _claim(db, action, body, user, invoice_id=None):
    from app.invoice.transition_gate import allow_route, assert_epoch, require_invoice
    current = allow_route(db, 'local')
    if invoice_id is not None:
        epoch = getattr(body, 'expected_authority_epoch', None)
        assert_epoch(current, epoch)
        require_invoice(db, invoice_id, 'local', epoch)
    payload = {"action": action, "invoice_id": invoice_id, "actor_id": _actor(user),
               "body": body.model_dump(mode="json")}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    row = InvoiceCommerceEvent(request_key=body.request_key, request_hash=digest, action=action,
                               payload=payload, created_by=_actor(user), invoice_id=invoice_id)
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        logger.warning("Local invoice command identity conflict; checking prior command")
        print("Local invoice command identity conflict; checking prior command", flush=True)
        row = db.scalar(select(InvoiceCommerceEvent).where(InvoiceCommerceEvent.request_key == body.request_key)
                        .with_for_update().execution_options(populate_existing=True))
        if row is None:
            raise
        if row.request_hash != digest:
            raise ValueError("幂等键已用于不同的订单操作") from None
        return row, False
    return row, True


def _get(db, invoice_id, user):
    from app.invoice.transition_gate import require_invoice
    require_invoice(db, invoice_id, 'local')
    snapshot_version = db.scalar(select(Invoice.commerce_version).where(Invoice.id == invoice_id))
    invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id)
                        .with_for_update().execution_options(populate_existing=True))
    if invoice is None:
        raise HTTPException(404, "订单不存在")
    if not ("super_admin" in user.get("roles", []) or "invoice:read_all" in user.get("permissions", [])
            or delegation_service.can_access_invoice(db, _actor(user), invoice)):
        raise HTTPException(404, "订单不存在")
    if invoice.transaction_mode != "local":
        raise ValueError("该历史订单尚未承接到本地交易账")
    if "super_admin" not in user.get("roles", []) and "invoice:read_all" not in user.get("permissions", []):
        try:
            require_customer_access(db, customer_id=invoice.local_customer_id, user=user,
                action_permissions=user.get("permissions", []), manage_permissions=["customer:admin"])
        except CustomerAccessDenied:
            raise HTTPException(404, "订单不存在") from None
    # All local structural edits advance commerce_version. A stale RR snapshot
    # cannot safely discover the new line IDs, so restart rather than range-lock
    # the child index and block unrelated orders being created in adjacent gaps.
    if snapshot_version != invoice.commerce_version:
        raise ValueError("订单已变化，请刷新后重试")
    item_ids = db.scalars(select(InvoiceItem.id).where(InvoiceItem.invoice_id == invoice.id)
                          .order_by(InvoiceItem.id)).all()
    items = [db.scalar(select(InvoiceItem).where(InvoiceItem.id == item_id).with_for_update()
                       .execution_options(populate_existing=True)) for item_id in item_ids]
    if any(item is None for item in items):
        raise ValueError("订单明细已变化，请刷新后重试")
    set_committed_value(invoice, "items", items)
    return invoice


def _version(invoice, body):
    if invoice.commerce_version != body.expected_version:
        raise ValueError("订单已变化，请刷新后重试")


def _apply_draft(db, invoice, body, user):
    from app.invoice import item_group_service
    if body.expected_groups_version is not None and body.item_groups is not None:
        item_group_service.load_groups(db, invoice)
        if item_group_service.version(invoice) != body.expected_groups_version:
            raise ValueError("明细分组已被他人修改，请刷新后再编辑")
    access = require_customer_access(db, customer_id=body.local_customer_id, user=user,
                                     action_permissions=["invoice:write"], manage_permissions=[])
    customer = db.scalar(select(CustomerAccount).where(CustomerAccount.id == access.customer_id)
                         .with_for_update().execution_options(populate_existing=True))
    if customer is None or customer.record_status != "active" or customer.identity_status == "disputed":
        raise ValueError("客户已停用、合并或存在待核验的身份冲突")
    actor = _actor(user)
    salesperson = delegation_service.ensure_can_delegate(db, actor, body.sales_user_id)
    if invoice.id is not None and invoice.sales_user_id != salesperson.id:
        raise ValueError("订单归属业务员不可修改")
    invoice.local_customer_id = customer.id
    invoice.customer_id = f"ark:{customer.id}"
    invoice.customer_name = customer.display_name
    from app.trade.service import apply_commercial
    apply_commercial(invoice, body, customer)
    invoice.inspection_requirement = body.inspection_requirement or invoice.inspection_requirement or (
        "detail" if body.is_new_deal else "single")
    invoice.sales_user_id = salesperson.id
    invoice.sales_user_name = salesperson.real_name or salesperson.username
    invoice.sales_phone, invoice.sales_email = salesperson.phone, salesperson.email
    from app.invoice.service import _apply_merchandiser
    _apply_merchandiser(db, invoice, body.merchandiser_id)
    for field in ("order_type", "invoice_date", "currency", "contact_name", "contact_phone", "contact_email",
                  "delivery_address", "express_channel", "shipping_fee", "surcharge_name", "surcharge_amount",
                  "packaging_quantity", "internal_accessory", "payment_term", "remark", "local_deposit_amount", "local_deposit_charge"):
        setattr(invoice, field, getattr(body, field))
    if body.invoice_no:
        invoice.invoice_no = body.invoice_no.strip()
        if not invoice.invoice_no:
            raise ValueError("订单编号不能为空")
    _validate_skus(db, [item.local_sku_id for item in body.items])
    prior = {item.id: item for item in invoice.items}
    carried = set()
    next_items = []
    for index, item_body in enumerate(body.items, 1):
        if item_body.id is not None:
            if item_body.id not in prior or item_body.id in carried:
                raise ValueError("订单明细ID不属于此单或重复")
            carried.add(item_body.id)
            item = prior[item_body.id]
        else:
            item = InvoiceItem()
        sku = db.get(CatalogSku, item_body.local_sku_id)
        product = db.get(CatalogProduct, sku.product_id)
        item.local_sku_id = sku.id
        item.commercial_kind = item_body.commercial_kind
        item.sort_order, item.product_kind, item.item_type = index, product.kind, "stock"
        item.product_name, item.product_display = product.name, product.display_name
        item.model, item.color, item.length, item.curl = product.model, sku.color, sku.size, sku.curl
        item.net_weight_grams = f"{format(sku.weight_grams.normalize(), 'f')}g" if sku.weight_grams is not None else None
        item.quantity, item.price_per_piece = item_body.quantity, item_body.price_per_piece
        item.discount_amount = _money(item_body.discount_amount)
        item.total_price = _money(item.quantity * item.price_per_piece + item.discount_amount)
        if item.total_price < 0:
            raise ValueError("折扣不能超过产品行金额")
        item.price_source = "manual"
        next_items.append(item)
    invoice.items = next_items
    invoice.product_amount = _money(sum(item.total_price for item in invoice.items))
    invoice.internal_discount = _money(sum(item.discount_amount for item in invoice.items))
    invoice.total_amount = _money(invoice.product_amount + body.shipping_fee + body.surcharge_amount + body.internal_accessory)
    invoice.internal_received = Decimal("0")
    invoice.internal_balance = invoice.total_amount
    invoice.updated_by = actor
    # Grouping is presentation-only; use validated catalog kinds, not caller labels.
    from types import SimpleNamespace
    db.add(invoice)
    db.flush()
    grouping_items = [SimpleNamespace(id=payload.id, group_key=payload.group_key,
        product_kind=item.product_kind) for payload, item in zip(body.items, invoice.items)]
    grouped = item_group_service.prepare_replace(db, invoice,
        SimpleNamespace(item_groups=body.item_groups, items=grouping_items))
    for item, payload in zip(invoice.items, grouping_items):
        item.group = grouped(payload)


@observe_command("contract.create")
def create_draft(db, body, user):
    from app.invoice.transition_gate import lock_platform, allow_route
    allow_route(db, 'local')
    with db.begin_nested():
        event, fresh = _claim(db, "create", body, user)
        if not fresh:
            return _get(db, event.invoice_id, user)
        if body.expected_version != 0:
            raise ValueError("新订单版本必须为零")
        invoice = Invoice(transaction_mode="local", commerce_status="draft", commerce_version=1,
                          sync_status="not_applicable", status="draft", created_by=_actor(user))
        # Use the durable command ID for collision-free automatic numbering.
        invoice.invoice_no = f"ARK-{body.invoice_date:%Y%m%d}-{event.id:06d}"
        _apply_draft(db, invoice, body, user)
        db.add(invoice)
        db.flush()
        event.invoice_id = invoice.id
        from app.commerce_transition.service import ensure_authority
        ensure_authority(db, invoice, route='local', source_evidence={
            'new_draft': True, 'request_key': body.request_key, 'created_by': _actor(user)})
        db.flush()
        return invoice


@observe_command("contract.update_draft", target_arg="invoice_id", invoice_arg="invoice_id")
def update_draft(db, invoice_id, body, user):
    with db.begin_nested():
        invoice = _get(db, invoice_id, user)
        event, fresh = _claim(db, "edit_draft", body, user, invoice_id)
        if not fresh:
            return invoice
        _version(invoice, body)
        if invoice.commerce_status != "draft":
            raise ValueError("已确认订单需通过订单变更处理，不能覆盖草稿")
        _apply_draft(db, invoice, body, user)
        invoice.commerce_version += 1
        db.flush()
        return invoice


@observe_command("contract.confirm", target_arg="invoice_id", invoice_arg="invoice_id")
def confirm(db, invoice_id, body, user):
    with db.begin_nested():
        invoice = _get(db, invoice_id, user)
        event, fresh = _claim(db, "confirm", body, user, invoice_id)
        if not fresh:
            return invoice
        _version(invoice, body)
        if invoice.commerce_status != "draft" or not invoice.items:
            raise ValueError("仅有产品明细的草稿订单可以确认")
        from app.commerce_transition.service import confirm_authority
        from app.commerce_transition.models import InvoiceAuthority
        authority = db.get(InvoiceAuthority, invoice.id)
        confirm_authority(db, invoice, 'local', authority.epoch, {'contract_event_id': event.id})
        if invoice.order_type == "presale" and not 0 < invoice.local_deposit_amount - invoice.local_deposit_charge <= invoice.product_amount:
            raise ValueError("确认预售单前须约定有效首款本金及费用")
        customer = db.scalar(select(CustomerAccount).where(CustomerAccount.id == invoice.local_customer_id)
                             .with_for_update().execution_options(populate_existing=True))
        if customer is None or customer.record_status != "active" or customer.identity_status == "disputed":
            raise ValueError("客户身份或状态已变化，请核对客户后再确认订单")
        from app.trade.service import freeze_order_fx
        freeze_order_fx(db, invoice)
        from app.trade.department_service import freeze_departments
        freeze_departments(db, invoice)
        if invoice.order_type == "stock" and body.warehouse_id is None:
            raise ValueError("现货订单确认时必须选择供货仓库")
        if body.warehouse_id is not None:
            _lock_warehouses(db, [body.warehouse_id])
        _validate_skus(db, [item.local_sku_id for item in invoice.items])
        invoice.commerce_status, invoice.status = "confirmed", "confirmed"
        db.flush()
        if invoice.order_type == "stock":
            for item in sorted(invoice.items, key=lambda item: item.id):
                reserve_line(db, item.id, body.warehouse_id, item.quantity, f"confirm:{event.id}:{item.id}", _actor(user))
        goods_amount = _money(invoice.total_amount - invoice.shipping_fee)
        components = [("goods", goods_amount, invoice.surcharge_amount)]
        if invoice.shipping_fee:
            components.append(("freight", invoice.shipping_fee, Decimal("0")))
        for kind, amount, handling in components:
            db.add(Receivable(invoice_id=invoice.id, business_key=f"invoice:{invoice.id}:{kind}",
                              kind=kind, amount=amount, handling_amount=handling, currency=invoice.currency,
                              customer_id=invoice.customer_id, remote_status="not_applicable"))
        invoice.commerce_version += 1
        db.flush()
        return invoice


@observe_command("contract.cancel", target_arg="invoice_id", invoice_arg="invoice_id")
def cancel(db, invoice_id, body, user):
    with db.begin_nested():
        invoice = _get(db, invoice_id, user)
        event, fresh = _claim(db, "cancel", body, user, invoice_id)
        if not fresh:
            return invoice
        _version(invoice, body)
        if invoice.commerce_status not in {"draft", "confirmed"}:
            raise ValueError("订单当前状态不能取消")
        if any(item.production_pending_quantity for item in invoice.items):
            raise ValueError("订单有未交付生产供货，请先释放生产计划")
        reservation_query = select(StockReservation).where(
            StockReservation.invoice_item_id.in_([item.id for item in invoice.items]))
        # Discover without range locks, then lock warehouses before responsibility
        # rows, matching reserve/issue. A pre-existing RR snapshot can miss a
        # warehouse; reject and retry the transaction rather than acquire a late
        # warehouse lock while holding a reservation index gap.
        warehouse_ids = set(db.scalars(reservation_query.with_only_columns(StockReservation.warehouse_id)).all())
        _lock_warehouses(db, warehouse_ids, allow_inactive=True)
        reservations = db.scalars(reservation_query.with_for_update()
                                  .execution_options(populate_existing=True)).all()
        if any(row.warehouse_id not in warehouse_ids for row in reservations):
            raise ValueError("订单仓库责任已变化，请刷新后重试取消")
        if any(row.shipped for row in reservations):
            raise ValueError("订单已有正式出库，请通过退货和贷项处理")
        if db.scalar(select(Receipt.id).where(Receipt.invoice_id == invoice.id, Receipt.status == "active").limit(1).with_for_update()):
            raise ValueError("订单存在回款，请先处理资金退款或核销释放")
        if db.scalar(select(ShipmentSettlement.id).where(ShipmentSettlement.invoice_id == invoice.id,
                     ShipmentSettlement.state != "cancelled").limit(1).with_for_update()):
            raise ValueError("订单存在发货结算，请先取消发货结算")
        for row in sorted(reservations, key=lambda row: (row.warehouse_id, row.invoice_item_id)):
            if row.reserved:
                release_line(db, row.invoice_item_id, row.warehouse_id, row.reserved,
                             f"cancel:{event.id}:{row.id}", body.reason, _actor(user))
        # Keep the receivable face amounts as historical facts; cancelled orders
        # must be excluded by active AR queries and cannot accept new allocations.
        invoice.commerce_status, invoice.status = "cancelled", "cancelled"
        invoice.commerce_version += 1
        invoice.updated_by = _actor(user)
        db.flush()
        return invoice


@observe_command("contract.amend", target_arg="invoice_id", invoice_arg="invoice_id")
def amend(db, invoice_id, body, user):
    from app.invoice.amendment_service import amend as apply_amendment
    return apply_amendment(db, invoice_id, body, user)
