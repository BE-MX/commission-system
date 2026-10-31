"""Explicit pre-dispatch order amendments preserve posted AR and stock facts."""
from decimal import Decimal
from contextlib import contextmanager
import logging
from sqlalchemy import select
from app.finance import service as finance
from app.finance.schemas import AdjustmentCreate
from app.invoice import commerce_service as commerce
from app.invoice.settlement_models import Receivable, ShipmentSettlement, SettlementItem
from app.inventory.models import StockReservation
from app.inventory.service import _lock_warehouses
from app.inventory.reservation_service import release_line, reserve_line
from app.production.local_models import ProductionSupply
from app.receipt.models import Receipt
from app.aftersales.local_replacement import ensure_regular_amendment
from app.customer.models import CustomerOrderItem


logger = logging.getLogger(__name__)


@contextmanager
def _amendment_transaction(db):
    try:
        with db.begin_nested():
            yield
    except Exception:
        # A read-loaded instance after a released nested savepoint can survive
        # rollback with the intermediate value if the earlier dirty instance
        # was garbage-collected. Reload from the restored parent transaction.
        db.expire_all()
        logger.warning("Order amendment rolled back")
        print("Order amendment rolled back; cached state expired", flush=True)
        raise


def amend(db, invoice_id, body, user):
    with _amendment_transaction(db):
        ledger = finance.book(db)
        invoice = commerce._get(db, invoice_id, user)
        event, fresh = commerce._claim(db, "amend", body, user, invoice.id)
        if not fresh:
            return invoice
        ensure_regular_amendment(db, invoice.id)
        commerce._version(invoice, body)
        finance.open_date(ledger, body.business_date)
        if invoice.commerce_status != "confirmed":
            raise ValueError("订单已经开始履约，已履约事实须用补差、退货或新单承接")
        if body.business_date < invoice.invoice_date:
            raise ValueError("变更日期不能早于原订单")
        immutable = ("local_customer_id", "currency", "order_type", "sales_user_id", "invoice_date")
        if any(getattr(invoice, field) != getattr(body, field) for field in immutable):
            raise ValueError("已确认订单的客户、币种、类型、归属和原始日期不可覆盖")
        if body.invoice_no and body.invoice_no != invoice.invoice_no:
            raise ValueError("已确认订单编号不可更改")
        settlements = db.scalars(select(ShipmentSettlement).where(ShipmentSettlement.invoice_id == invoice.id)
            .with_for_update().execution_options(populate_existing=True)).all()
        if any(row.state != "cancelled" for row in settlements):
            raise ValueError("请先取消未履约发货批次；已履约批次不能覆盖")
        original_items = {item.id: item for item in invoice.items}
        edited = {item.id: item for item in body.items if item.id is not None}
        supplied = set(db.scalars(select(ProductionSupply.invoice_item_id).where(
            ProductionSupply.invoice_item_id.in_(original_items)).with_for_update()).all())
        snapshot = select(StockReservation).where(StockReservation.invoice_item_id.in_(original_items))
        warehouse_ids = set(db.scalars(snapshot.with_only_columns(StockReservation.warehouse_id)).all())
        if body.warehouse_id is not None:
            warehouse_ids.add(body.warehouse_id)
        _lock_warehouses(db, warehouse_ids, allow_inactive=True)
        reservations = db.scalars(snapshot.with_for_update().execution_options(populate_existing=True)).all()
        if any(row.warehouse_id not in warehouse_ids for row in reservations):
            raise ValueError("库存责任发生变化，请刷新后重试")
        settled = set(db.scalars(select(SettlementItem.invoice_item_id).where(
            SettlementItem.invoice_item_id.in_(original_items)).with_for_update()).all())
        historical = set(db.scalars(select(CustomerOrderItem.local_invoice_item_id).where(
            CustomerOrderItem.local_invoice_item_id.in_(original_items)).with_for_update()).all())
        referenced = supplied | settled | historical | {row.invoice_item_id for row in reservations}
        if referenced - set(edited):
            raise ValueError("有库存或生产凭证的明细须保留原ID，不能删除历史引用")
        for identity, item in original_items.items():
            if item.stock_shipped_quantity:
                raise ValueError("已出库明细不能覆盖")
            new = edited.get(identity)
            if identity in referenced and new and new.local_sku_id != item.local_sku_id:
                raise ValueError("有库存或生产凭证的明细不能更换SKU")
            if new and new.quantity < item.production_pending_quantity:
                raise ValueError("数量不能低于未交付生产供货，请先调整生产计划")
        targets = {row.kind: row for row in db.scalars(select(Receivable).where(
            Receivable.invoice_id == invoice.id, Receivable.settlement_id.is_(None))
            .order_by(Receivable.id).with_for_update().execution_options(populate_existing=True)).all()}
        active_receipts = db.scalars(select(Receipt).where(Receipt.invoice_id == invoice.id, Receipt.status == "active")
            .with_for_update().execution_options(populate_existing=True)).all()
        if any(row.purpose == "presale_deposit" for row in active_receipts) and (
                body.local_deposit_amount != invoice.local_deposit_amount or body.local_deposit_charge != invoice.local_deposit_charge):
            raise ValueError("已核销首款的合同组成不能覆盖，请先冲回首款")
        before = dict(total=str(invoice.total_amount), goods=str(invoice.total_amount-invoice.shipping_fee),
            freight=str(invoice.shipping_fee), handling=str(invoice.surcharge_amount), items=[dict(id=item.id,
                sku_id=item.local_sku_id, quantity=item.quantity, total=str(item.total_price)) for item in invoice.items])
        received, outstanding = invoice.internal_received, invoice.internal_balance
        prior_reservations = [(row.invoice_item_id, row.warehouse_id, row.reserved) for row in reservations]
        frozen_customer = invoice.customer_name
        for row in reservations:
            if row.reserved:
                release_line(db, row.invoice_item_id, row.warehouse_id, row.reserved, f"amend-release:{event.id}:{row.id}", body.reason, commerce._actor(user))
        commerce._apply_draft(db, invoice, body, user)
        invoice.internal_received, invoice.internal_balance = received, outstanding
        invoice.customer_name = frozen_customer
        if invoice.order_type == "presale" and not 0 < invoice.local_deposit_amount - invoice.local_deposit_charge <= invoice.product_amount:
            raise ValueError("变更后的预售首款本金必须由商品金额覆盖")
        db.flush()
        components = {"goods": finance.money(invoice.total_amount-invoice.shipping_fee), "freight": finance.money(invoice.shipping_fee)}
        for kind, amount in components.items():
            delta = finance.money(amount - Decimal(before[kind]))
            if not delta:
                continue
            target = targets.get(kind)
            if target is None:
                if delta < 0:
                    raise ValueError("缺少原应收，不能调整")
                target = Receivable(invoice_id=invoice.id, business_key=f"invoice:{invoice.id}:{kind}", kind=kind,
                    amount=amount, handling_amount=0, currency=invoice.currency, customer_id=invoice.customer_id, remote_status="not_applicable")
                db.add(target)
                db.flush()
                created, _ = finance.claim(db, "create_invoice_freight", target.id,
                    body.model_copy(update={"request_key": f"amend-new-ar:{event.id}:{kind}"}), user, body.business_date)
                created.receivable_id, created.amount = target.id, amount
                invoice.internal_balance = finance.money(invoice.internal_balance + amount)
                targets[kind] = target
            else:
                finance.adjust_receivable(db, target.id, AdjustmentCreate(request_key=f"amend-ar:{event.id}:{kind}",
                    expected_version=target.version, invoice_id=invoice.id, amount=delta,
                    business_date=body.business_date, reason=body.reason), user, contract_change_event=event)
        goods = targets["goods"]
        paid_fee = sum((row.effective_bank_charge for row in active_receipts if row.receivable_id == goods.id), Decimal(0))
        unpaid = finance.money(goods.amount + goods.adjustment_amount - goods.paid_amount)
        if invoice.surcharge_amount < paid_fee or invoice.surcharge_amount - paid_fee > unpaid:
            raise ValueError("变更后的费用不能覆盖已核销组成，请先核对资金")
        goods.handling_amount = invoice.surcharge_amount
        goods.version += 1
        if invoice.order_type == "stock":
            if body.warehouse_id is None:
                raise ValueError("现货变更需指定重新预占的仓库")
            for item in sorted(invoice.items, key=lambda item: item.id):
                needed = item.quantity - item.production_pending_quantity
                if needed:
                    reserve_line(db, item.id, body.warehouse_id, needed, f"amend-reserve:{event.id}:{item.id}", commerce._actor(user))
        else:
            remaining = {item.id: item.quantity-item.production_pending_quantity for item in invoice.items}
            for item_id, warehouse_id, quantity in sorted(prior_reservations):
                kept = min(quantity, remaining[item_id])
                if kept:
                    reserve_line(db, item_id, warehouse_id, kept, f"amend-keep:{event.id}:{item_id}:{warehouse_id}", commerce._actor(user))
                    remaining[item_id] -= kept
        invoice.commerce_version += 1
        event.payload = {**event.payload, "before": before, "after": dict(total=str(invoice.total_amount),
            goods=str(components["goods"]), freight=str(components["freight"]), handling=str(invoice.surcharge_amount))}
        db.flush()
        return invoice
