"""Current-authorized, local-only settlement state commands; caller commits once."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import logging

from fastapi import HTTPException
from sqlalchemy import or_, select

from app.invoice import edit_authority, settlement_service as shipments
from app.invoice import presale_runtime as pools
from app.invoice.models import InvoiceItem
from app.invoice.settlement_models import (Receivable, ReceiptBatch, SettlementApplication,
    SettlementEvent, SettlementItem, ShipmentOutbound, ShipmentSettlement)
from app.portal.authority import lock_authority
from app.portal.errors import PortalError, TransactionBusy
from app.receipt import access, authority, service
from app.receipt.models import Receipt, ReceiptLog


@dataclass(frozen=True)
class StateGraph:
    applications: tuple
    receipts: dict
    freight: object
    outbound: object
    balance: object = None


def _rows(db, model, predicate):
    return db.scalars(select(model).where(predicate).order_by(*model.__table__.primary_key.columns)
        .with_for_update().execution_options(populate_existing=True)).all()


def _capture(db, invoice, identity, action):
    # Same authority/Invoice protocol as the migrated financial writers. These
    # are current reads even after the locator's REPEATABLE READ snapshot waits.
    receipts = _rows(db, Receipt, Receipt.invoice_id == invoice.id)
    settlements = _rows(db, ShipmentSettlement, or_(ShipmentSettlement.invoice_id == invoice.id,
        ShipmentSettlement.id == identity))
    by_settlement = {row.id: row for row in settlements}
    row = by_settlement.get(identity)
    if row is None or row.invoice_id != invoice.id:
        raise ValueError('发货结算关联已变化，请核对原单')
    items = _rows(db, InvoiceItem, InvoiceItem.invoice_id == invoice.id)
    linked_items = _rows(db, SettlementItem, SettlementItem.settlement_id == row.id)
    if not linked_items or any(item.invoice_item_id not in {item.id for item in items} for item in linked_items):
        raise ValueError('发货产品关联异常，请核对原单')
    applications = _rows(db, SettlementApplication, or_(
        SettlementApplication.settlement_id.in_(by_settlement),
        SettlementApplication.receipt_id.in_([receipt.id for receipt in receipts])))
    related = _rows(db, Receipt, Receipt.id.in_({app.receipt_id for app in applications}))
    by_receipt = {receipt.id: receipt for receipt in receipts + related}
    for app in applications:
        receipt, settlement = by_receipt.get(app.receipt_id), by_settlement.get(app.settlement_id)
        expected_purpose = {'deposit': 'presale_deposit', 'goods': 'presale_goods', 'freight': 'freight'}.get(app.component)
        if (receipt is None or settlement is None or settlement.invoice_id != invoice.id
                or receipt.invoice_id != invoice.id or receipt.customer_id != invoice.customer_id
                or receipt.currency != invoice.currency or not isinstance(settlement.quote, dict)):
            raise ValueError('发货资金关联异常，请核对原单')
        if (settlement.quote.get('funding_version') in {None, 1} and app.component == 'deposit'
                and settlement.state == 'cancelled' and app.status == 'released'):
            if not pools.released_legacy_deposit_matches(app, settlement, receipt, invoice):
                raise ValueError('历史已释放预付款与原结算快照不一致，请核对原单')
        elif (receipt.purpose != expected_purpose and not (
                settlement.quote.get('funding_version') == 2 and receipt.purpose in pools.POOL_PURPOSES
                and app.component in {'goods', 'freight'})):
            raise ValueError('发货资金关联异常，请核对原单')
    selected = tuple(app for app in applications if app.settlement_id == row.id)
    selected_receipts = {app.receipt_id: by_receipt[app.receipt_id] for app in selected}
    if not isinstance(row.quote, dict) or row.quote.get('currency') != invoice.currency:
        raise ValueError('结算资金快照异常，请核对原单')
    try:
        amounts = {key: Decimal(str(row.quote[key])) for key in ('goods_payment_due', 'freight_amount',
            'goods_payment_charge', 'new_payment_due', 'deposit_applied', 'deposit_charge_applied')}
        if not all(amount.is_finite() for amount in amounts.values()):
            raise InvalidOperation()
    except (InvalidOperation, KeyError, TypeError, ValueError):
        raise ValueError('结算资金快照异常，请核对原单') from None
    deposit = [app for app in selected if app.component == 'deposit']
    if row.quote.get('funding_version') == 2:
        pools.pool_lots(db, invoice, current=True)
        pools.validate_quote_applications(row, selected, by_receipt)
    elif row.is_final:
        if (len(deposit) != 1 or deposit[0].receipt_id != row.quote.get('deposit_receipt_id')
                or deposit[0].amount != amounts['deposit_applied']
                or deposit[0].bank_charge != amounts['deposit_charge_applied']):
            raise ValueError('发货预付款关联异常，请核对原单')
    elif deposit:
        raise ValueError('发货预付款关联异常，请核对原单')
    expected = {f'invoice:{invoice.id}:goods': ('goods', None),
                f'settlement:{row.id}:freight': ('freight', row.id)}
    targets = _rows(db, Receivable, or_(Receivable.settlement_id == row.id,
        Receivable.business_key.in_(expected),
        Receivable.id.in_({receipt.receivable_id for receipt in selected_receipts.values() if receipt.receivable_id})))
    by_target = {target.id: target for target in targets}
    freight = None
    for target in targets:
        kind, settlement_id = expected.get(target.business_key, (None, None))
        if (target.invoice_id != invoice.id or target.kind != kind or target.settlement_id != settlement_id
                or target.customer_id != invoice.customer_id or target.currency != invoice.currency
                or kind == 'goods' and target.remote_order_id != invoice.xiaoman_order_id):
            raise ValueError('发货应收目标关联异常，请核对原单')
        if kind == 'freight':
            if freight is not None:
                raise ValueError('发货运费目标关联异常，请核对原单')
            freight = target
    if amounts['freight_amount'] > 0 and freight is None:
        raise ValueError('发货运费目标关联异常，请核对原单')
    batches = {batch.id: batch for batch in _rows(db, ReceiptBatch,
        ReceiptBatch.id.in_({receipt.batch_id for receipt in selected_receipts.values() if receipt.batch_id}))}
    for app in selected:
        receipt = selected_receipts[app.receipt_id]
        target = by_target.get(receipt.receivable_id)
        if app.component == 'deposit' or receipt.purpose in pools.POOL_PURPOSES:
            if receipt.receivable_id is not None and (target is None or target.kind != 'goods'):
                raise ValueError('发货预付款目标关联异常，请核对原单')
            continue
        batch = batches.get(receipt.batch_id)
        expected_key = f'settlement:{row.id}:freight' if app.component == 'freight' else f'invoice:{invoice.id}:goods'
        if (target is None or target.business_key != expected_key or target.kind != app.component
                or batch is None or batch.customer_id != invoice.customer_id or batch.currency != invoice.currency
                or app.amount != receipt.amount or app.bank_charge != receipt.bank_charge
                or len([other for other in applications if other.receipt_id == receipt.id]) != 1):
            raise ValueError('发货付款组件关联异常，请核对原单')
    outbounds = _rows(db, ShipmentOutbound, ShipmentOutbound.settlement_id == row.id)
    if any(outbound.invoice_id != invoice.id for outbound in outbounds) or len(outbounds) > 1:
        raise ValueError('发货出库关联异常，请核对原单')
    logs = _rows(db, ReceiptLog, ReceiptLog.receipt_id.in_(selected_receipts))
    # Legacy free-text reconciled/synced cannot prove every late effect resolved.
    # Pause adds no late-fact guard: it does not free funds or resume senders.
    active_funds = {app.receipt_id for app in selected if app.status != 'released'}
    if action in {'cancel', 'resume'} and any(log.action == 'late_result' and log.receipt_id in active_funds for log in logs):
        raise ValueError('本批存在迟到回款结果，请先核对原效果；暂不能取消或恢复')
    _rows(db, SettlementEvent, SettlementEvent.settlement_id == row.id)
    balance = shipments.funding_balance(db, row, current=True) if action == 'resume' else None
    return row, StateGraph(selected, selected_receipts, freight, outbounds[0] if outbounds else None, balance)


def change(db, identity, user, action, version, reason):
    # Dirty caller rejection must not flush or roll back somebody else's work.
    authority.fresh_boundary(db)
    try:
        lock_authority(db, force=True)
        current = authority.current_user(db, user, 'shipment:write')
        invoice_id = db.scalar(select(ShipmentSettlement.invoice_id).where(ShipmentSettlement.id == identity))
        if invoice_id is None:
            raise HTTPException(404, '订单或发货结算不存在')
        invoice = edit_authority.lock_document(db, invoice_id, force=True)
        if invoice is None:
            raise HTTPException(404, '订单或发货结算不存在')
        db.refresh(invoice, with_for_update=True)
        access.ensure_invoice(db, invoice, current)
        if invoice.order_type != 'presale':
            raise ValueError('仅预售单支持分批发货结算')
        service.ensure_order_ready(db, invoice, current=True)
        if invoice.shipping_fee:
            raise ValueError('预售主单运费必须为零')
        row, graph = _capture(db, invoice, identity, action)
        shipments._change_state_verified(db, row, current, action, version, reason, graph)
        # Production SessionLocal disables autoflush. Persist this transaction's
        # state/App/event before populate_existing current reads can replace
        # pending ORM values; this is not a commit or a lock-release boundary.
        db.flush()
        return shipments.describe(db, row, current=True)
    except TransactionBusy:
        raise
    except PortalError as error:
        raise HTTPException(error.status, '发货结算授权暂不可用',
            headers={'Cache-Control': 'private, no-store', 'Pragma': 'no-cache'}) from None


def result_unavailable(error):
    diagnostics = []
    try:
        logging.getLogger(__name__).warning('Shipment state unavailable (%s)', type(error).__name__)
    except Exception as failure:
        diagnostics.append(failure)
    try:
        print('[shipment] state result unavailable', flush=True)
    except Exception as failure:
        diagnostics.append(failure)
    response = HTTPException(503, '发货结算结果暂无法确认，请先刷新原结算核对版本，不要重复提交',
        headers={'Cache-Control': 'private, no-store', 'Pragma': 'no-cache'})
    if diagnostics:
        raise response from ExceptionGroup('Shipment state diagnostics failed', diagnostics)
    raise response from None
