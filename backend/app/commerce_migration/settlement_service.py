"""Audit real zero balances and closed fulfillment before legacy retirement."""
from decimal import Decimal
from sqlalchemy import select, or_
from app.commerce_transition import service as gates, transfer_service as transfers
from app.commerce_transition.models import InvoiceAuthority, BankIdentity
from app.commerce_migration.models import MigrationBatch, MigrationRecord
from app.commerce_migration.service import digest
from app.core.time import beijing_now, beijing_today
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.settlement_models import Receivable, ReceiptBatch, ShipmentSettlement, ShipmentOutbound
from app.inventory.models import StockReservation
from app.production.local_models import ProductionSupply
from app.receipt.models import Receipt
from app.semifinished.models import InvoiceAllocation

ZERO = Decimal('0')


def _rows(db, statement):
    return db.scalars(statement.with_for_update().execution_options(populate_existing=True)).all()


def _closure_preview(db, identities):
    from app.commerce_transition.models import ResponsibilityGroup, ResponsibilityMember
    from app.stock.models import ProductionOrderItem
    ids, groups = set(identities), set()
    while True:
        before = set(ids)
        groups |= set(db.scalars(select(ResponsibilityMember.group_id).where(ResponsibilityMember.invoice_id.in_(ids))))
        ids |= set(db.scalars(select(ResponsibilityMember.invoice_id).where(ResponsibilityMember.group_id.in_(groups))))
        batches = set(db.scalars(select(Receipt.batch_id).where(Receipt.invoice_id.in_(ids), Receipt.batch_id.is_not(None))))
        ids |= set(db.scalars(select(Receipt.invoice_id).where(Receipt.batch_id.in_(batches))))
        production = set(db.scalars(select(ProductionOrderItem.order_id).join(ProductionSupply,
            ProductionSupply.production_item_id == ProductionOrderItem.id).join(InvoiceItem,
            InvoiceItem.id == ProductionSupply.invoice_item_id).where(InvoiceItem.invoice_id.in_(ids))))
        ids |= set(db.scalars(select(InvoiceItem.invoice_id).join(ProductionSupply,
            ProductionSupply.invoice_item_id == InvoiceItem.id).join(ProductionOrderItem,
            ProductionOrderItem.id == ProductionSupply.production_item_id).where(ProductionOrderItem.order_id.in_(production))))
        if before == ids:
            break
    if any(not row.complete for row in db.scalars(select(ResponsibilityGroup).where(ResponsibilityGroup.id.in_(groups)))):
        raise ValueError('共享责任清单尚未完整核验')
    return sorted(ids)


def _check(db, body, *, lock=True):
    gates.lock_policy(db) if lock else gates.policy(db)
    ids = sorted(r.invoice_id for r in body.invoices)
    if ids:
        closure = transfers.responsibility_closure(db, ids)[0] if lock else _closure_preview(db, ids)
        if closure != ids:
            raise ValueError(f'结清必须覆盖完整共享责任闭包：{closure}')
        from app.commerce_migration.handover_service import pending_original_requests
        if pending_original_requests(db, ids):
            raise ValueError('原在途或unknown尚未核清，不能结清')
    invoices, authorities = {}, {}
    for command in sorted(body.invoices, key=lambda r: r.invoice_id):
        authority = gates._lock_authority(db, command.invoice_id) if lock else db.get(InvoiceAuthority, command.invoice_id)
        invoice = db.scalar(select(Invoice).where(Invoice.id == command.invoice_id)
            .with_for_update().execution_options(populate_existing=True))
        if (authority is None or authority.route != 'legacy' or authority.epoch != command.expected_authority_epoch
                or invoice is None or invoice.transaction_mode != 'legacy'):
            raise ValueError('原订单路线或epoch已变化')
        if (invoice.internal_balance is None or invoice.internal_balance != ZERO
                or invoice.commerce_status not in {'closed', 'cancelled'}):
            raise ValueError('原订单余额非零或缺少真实已结束履约事实，不能结清')
        targets = _rows(db, select(Receivable).where(Receivable.invoice_id == invoice.id))
        if any(t.amount + t.adjustment_amount - t.paid_amount != ZERO or t.attempt_token or t.lease_until for t in targets):
            raise ValueError('原应收余额或未决责任未清零')
        lines = _rows(db, select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id))
        if (any(r.stock_reserved_quantity or r.production_pending_quantity for r in lines)
                or invoice.commerce_status == 'closed' and any(r.stock_shipped_quantity != r.quantity for r in lines)):
            raise ValueError('原订单预占、在产或全部发货责任未收尾')
        line_ids = [r.id for r in lines]
        if any(r.reserved for r in _rows(db, select(StockReservation).where(StockReservation.invoice_item_id.in_(line_ids)))):
            raise ValueError('原仓库预占未释放')
        if any(r.quantity != r.received_quantity + r.released_quantity for r in _rows(db,
                select(ProductionSupply).where(ProductionSupply.invoice_item_id.in_(line_ids)))):
            raise ValueError('原生产供货尚未交付或释放')
        if any(r.status == 'pending' or r.pending_delta_grams or r.operation_key or r.pending_at for r in _rows(db,
                select(InvoiceAllocation).where(InvoiceAllocation.invoice_id == invoice.id))):
            raise ValueError('原物料仍有未决扣量')
        shipments = _rows(db, select(ShipmentSettlement).where(ShipmentSettlement.invoice_id == invoice.id))
        if any(r.state not in {'shipped', 'cancelled'} for r in shipments):
            raise ValueError('原发货批次尚未收尾')
        outbounds = _rows(db, select(ShipmentOutbound).where(ShipmentOutbound.invoice_id == invoice.id))
        if any(r.attempt_token or r.lease_until or r.status not in {'local_shipped', 'synced', 'done', 'cancelled'} for r in outbounds):
            raise ValueError('原出库仍有未决责任')
        from app.aftersales.models import AfterSalesCase
        case_links = [AfterSalesCase.local_invoice_item_id.in_(line_ids)]
        if invoice.xiaoman_order_id:
            case_links.append(AfterSalesCase.order_id == invoice.xiaoman_order_id)
        cases = _rows(db, select(AfterSalesCase).where(or_(*case_links), AfterSalesCase.deleted_at.is_(None)))
        if any(r.current_status not in {'completed', 'closed', 'cancelled', 'rejected'} for r in cases):
            raise ValueError('原售后尚未关闭')
        invoices[invoice.id], authorities[invoice.id] = invoice, authority
    bank_rows = []
    for identity in sorted(body.bank_identity_ids):
        row = db.scalar(select(BankIdentity).where(BankIdentity.id == identity).with_for_update()
                        .execution_options(populate_existing=True))
        if row is None or row.route != 'legacy' or not row.payment_ref:
            raise ValueError('仅可结清已绑定真实原账的旧银行身份')
        prefix, _, source_id = row.payment_ref.partition(':')
        if not source_id.isdecimal() or prefix not in {'legacy-batch', 'legacy-receipt'}:
            raise ValueError('旧银行款缺少完整原账关联')
        if prefix == 'legacy-batch':
            batch = db.scalar(select(ReceiptBatch).where(ReceiptBatch.id == int(source_id)).with_for_update()
                              .execution_options(populate_existing=True))
            receipts = _rows(db, select(Receipt).where(Receipt.batch_id == int(source_id)))
            used = sum((r.amount - r.reversed_amount for r in receipts if r.status == 'active'), ZERO)
            if (batch is None or batch.gross_amount != row.amount or batch.currency != row.currency
                    or batch.allocated_amount != used or used + batch.refunded_amount != batch.gross_amount):
                raise ValueError('原银行款仍有未分配预收、退款或金额差异，不能结清')
            from app.finance.models import FinanceEvent
            refunds = _rows(db, select(FinanceEvent).where(FinanceEvent.batch_id == batch.id,
                FinanceEvent.action.in_(['refund', 'opening_refund'])))
            if sum((-r.amount for r in refunds), ZERO) != batch.refunded_amount:
                raise ValueError('原退款缺少完整不可变实际凭证')
        else:
            receipts = _rows(db, select(Receipt).where(Receipt.id == int(source_id)))
            if len(receipts) != 1 or receipts[0].amount != row.amount or receipts[0].currency != row.currency:
                raise ValueError('原银行款金额、原币或原回款事实不一致')
            original = receipts[0]
            if (original.status != 'active' or original.collect_status != 1
                    or original.sync_status not in {'synced', 'not_applicable'}
                    or original.reversed_amount or original.reversed_bank_charge):
                raise ValueError('原独立回款存在冲回、无效收款或缺少完整退款凭证，不能结清')
        from app.commerce_migration.handover_service import pending_original_requests
        if pending_original_requests(db, sorted({receipt.invoice_id for receipt in receipts})):
            raise ValueError('原银行款关联取消、删除或unknown责任尚未收尾')
        for receipt in receipts:
            authority = authorities.get(receipt.invoice_id) or db.get(InvoiceAuthority, receipt.invoice_id)
            if ((receipt.status == 'active' and receipt.amount > receipt.reversed_amount
                    and (receipt.collect_status != 1 or receipt.sync_status not in {'synced', 'not_applicable'}))
                    or receipt.sync_status in {'syncing', 'uncertain'} or receipt.attempt_token or receipt.lease_until
                    or authority is None or (receipt.invoice_id not in invoices and not authority.settled_evidence)):
                raise ValueError('原银行款全部订单、退款与未决责任必须共同结清')
        bank_rows.append(row)
    return authorities, bank_rows


def preview(db, body):
    try:
        _check(db, body, lock=False)
        return {'can_apply': True, 'conflicts': [], 'request_key': body.request_key}
    except ValueError as exc:
        return {'can_apply': False, 'conflicts': [{'code': 'legacy_not_closed', 'message': str(exc)}], 'request_key': body.request_key}


def apply(db, body, user):
    with db.begin_nested():
        gates.lock_policy(db)
        key = 'settlement:' + digest(body.request_key)[:48]
        content = body.model_dump(mode='json')
        prior = db.get(MigrationBatch, key)
        if prior:
            if prior.manifest_hash != digest(content):
                raise ValueError('结清请求已用于不同对象或依据')
            return prior.result
        authorities, banks = _check(db, body)
        actor = int(user['sub'])
        evidence = {'request_key': body.request_key, 'recorded_by': actor, 'review_reference': body.review_reference,
                    'evidence_sha256': body.evidence_sha256, 'checked_at': beijing_now().isoformat(), 'manifest_hash': digest(content)}
        for authority in authorities.values():
            authority.settled_evidence, authority.state = evidence, 'frozen'
            gates._event(db, authority, 'settle', evidence)
        for row in banks:
            row.settled_evidence = evidence
        result = {'request_key': body.request_key, 'invoice_ids': sorted(authorities), 'bank_identity_ids': [r.id for r in banks]}
        batch = MigrationBatch(batch_key=key, source='legacy-closure', tenant='formal', manifest_hash=digest(content),
            evidence_sha256=body.evidence_sha256, review_reference=body.review_reference, cutover_date=beijing_today(),
            created_by=actor, result=result)
        db.add(batch); db.flush()
        db.add(MigrationRecord(batch_key=key, source='legacy-closure', tenant='formal', object_type='settlement',
            external_id=body.request_key, role='archive', content_hash=digest(content), snapshot={**content, 'readback': result}))
        db.flush()
        return result
