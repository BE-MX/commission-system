"""Reviewed cash and spent allocations continue in the existing finance book.

All rows in one manifest are savepoint atomic. The finance singleton serializes
financial imports with ordinary finance, fulfillment, and commission writers.
No historical stock movement or positive commission payment is replayed.
"""
from types import SimpleNamespace
from sqlalchemy import select
from app.auth.models import ArkUser
from app.commerce_migration.models import MigrationBatch, MigrationRecord
from app.commerce_migration.service import _current, _record, _assert_record, digest
from app.commission.opening_service import bind_paid_history, paid_snapshot
from app.customer.models import CustomerAccount, CustomerExternalIdentity, CustomerObjectOwnership
from app.finance import service as finance
from app.finance.models import BankAccount, FinanceEvent
from app.invoice.models import Invoice
from app.invoice.settlement_models import Receivable, ReceiptBatch
from app.receipt.models import Receipt


def _query(db, statement, lock):
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return db.scalars(statement).all()


def _shared(db, statement, lock):
    if lock:
        statement = statement.with_for_update(read=True).execution_options(populate_existing=True)
    return db.scalar(statement)


def _customer_proof(db, manifest, payment, lock):
    overlay = _current(db, select(CustomerObjectOwnership).where(CustomerObjectOwnership.object_type == 'external_identity',
        CustomerObjectOwnership.object_id == payment.customer_external_identity_id), lock)
    identity = _current(db, select(CustomerExternalIdentity).where(CustomerExternalIdentity.id == payment.customer_external_identity_id), lock)
    if (identity is None or identity.contact_id is not None or identity.customer_id is None
            or (identity.source_system, identity.source_account_key, identity.identifier_type, identity.normalized_value)
                != (manifest.source, manifest.tenant, 'company_id', payment.source_customer_id)
            or identity.verification_status != 'verified' or identity.status != 'active'
            or identity.identity_strength != 'strong' or identity.cardinality != 'one_to_one'
            or payment.local_customer_id != (overlay.current_customer_id if overlay else identity.customer_id)):
        raise ValueError('付款缺少同来源已核验的客户身份关联，不能重归属未核销预收')


def _order_proof(db, manifest, payment, allocation, lock):
    proof = _current(db, select(MigrationRecord).where(MigrationRecord.id == allocation.order_binding_record_id), lock)
    expected = dict(local_customer_id=payment.local_customer_id,
        source_customer_id=allocation.source_customer_id)
    if (proof is None or proof.role != 'opening' or proof.object_type != 'order_binding'
            or proof.local_invoice_id != allocation.invoice_id
            or (proof.source, proof.tenant) != (manifest.source, manifest.tenant)
            or any(proof.snapshot.get(key) != value for key, value in expected.items())):
        raise ValueError('核销缺少同来源已核验的整单承接关联')
    invoice = _current(db, select(Invoice).where(Invoice.id == allocation.invoice_id), lock)
    from app.commerce_migration.handover_service import staged_invoice
    if (not staged_invoice(db, invoice)
            or invoice.commerce_status not in {'opening', 'confirmed', 'partially_shipped', 'shipped', 'closed'}
            or invoice.local_customer_id != payment.local_customer_id or invoice.currency != payment.currency
            or invoice.xiaoman_order_id != proof.snapshot.get('source_order_id')
            or invoice.invoice_date > allocation.collection_date):
        raise ValueError('历史订单身份、日期、客户、币种或状态与整单承接不一致')
    target = _current(db, select(Receivable).where(Receivable.id == allocation.receivable_id), lock)
    if (target is None or target.invoice_id != invoice.id or target.currency != payment.currency
            or target.customer_id != f'ark:{payment.local_customer_id}' or target.kind not in {'goods', 'freight'}
            or (target.kind == 'freight') != (allocation.purpose == 'freight')
            or (allocation.purpose in {'presale_deposit', 'presale_balance'}) != (invoice.order_type == 'presale' and target.kind == 'goods')):
        raise ValueError('历史核销应收或预售组成与整单责任不一致')
    prior_events = _query(db, select(FinanceEvent).where(FinanceEvent.receivable_id == target.id), lock)
    if any(event.action != 'opening_adjustment' or event.payload.get('migration_record_id') != proof.id for event in prior_events) or target.paid_amount:
        raise ValueError('应收已有在线资金事实，须在整单切换批次内核验，不能再次承接')
    if invoice.internal_received:
        raise ValueError('整单已有收款汇总，须先核验承接基线，不能重复累计历史回款')
    if allocation.amount - allocation.reversed_amount > target.amount + target.adjustment_amount:
        raise ValueError('历史有效核销超过整单剩余应收')
    if allocation.bank_charge - allocation.reversed_bank_charge > target.handling_amount:
        raise ValueError('历史有效核销费用超过原应收费用')
    return invoice, target


def _legacy_receipt(db, payment, allocation, invoice, lock):
    rows = _query(db, select(Receipt).where(Receipt.xiaoman_receipt_id == allocation.original_receipt_id), lock)
    existing = _current(db, select(Receipt).where(Receipt.id == allocation.existing_receipt_id), lock) if allocation.existing_receipt_id else None
    if existing is None and (allocation.existing_receipt_id or rows):
        raise ValueError('原回款已存在，须明确复用原回款ID')
    if existing is not None:
        if any(row.id != existing.id for row in rows):
            raise ValueError('原回款身份指向多个回款，须先核验重复事实')
        expected = dict(invoice_id=invoice.id, batch_id=payment.existing_batch_id,
            xiaoman_receipt_id=allocation.original_receipt_id, amount=allocation.amount,
            bank_charge=allocation.bank_charge, currency=payment.currency, collection_date=allocation.collection_date,
            customer_id=allocation.source_customer_id, xiaoman_order_id=invoice.xiaoman_order_id)
        if (any(getattr(existing, key) != value for key, value in expected.items())
                or {'presale_goods': 'presale_balance'}.get(existing.purpose, existing.purpose) != allocation.purpose
                or (existing.receivable_id is not None and existing.receivable_id != allocation.receivable_id)
                or existing.source == 'local' or existing.status != 'active' or existing.collect_status != 1
                or existing.sync_status not in {'synced', 'not_applicable'} or existing.attempt_token or existing.lease_until
                or existing.reversed_amount or existing.reversed_bank_charge
                or _query(db, select(FinanceEvent.id).where(FinanceEvent.receipt_id == existing.id), lock)):
            raise ValueError('原回款事实不匹配或存在未完成远端动作，禁止改写承接')
    return existing


def _check_payment(db, manifest, payment, lock):
    customer = _current(db, select(CustomerAccount).where(CustomerAccount.id == payment.local_customer_id), lock)
    bank = _current(db, select(BankAccount).where(BankAccount.id == payment.bank_account_id), lock)
    confirmer = _shared(db, select(ArkUser).where(ArkUser.id == payment.confirmed_by), lock)
    if customer is None or customer.identity_status == 'disputed':
        raise ValueError('历史付款缺少明确稳定客户映射')
    _customer_proof(db, manifest, payment, lock)
    if bank is None or bank.currency != payment.currency or confirmer is None:
        raise ValueError('历史付款缺少银行账户、币种或确认人映射')
    existing = _current(db, select(ReceiptBatch).where(ReceiptBatch.id == payment.existing_batch_id), lock) if payment.existing_batch_id else None
    same_no = _query(db, select(ReceiptBatch.id).where(ReceiptBatch.batch_no == payment.batch_no), lock)
    if any(identity != payment.existing_batch_id for identity in same_no):
        raise ValueError('付款编号已用于其他付款')
    if payment.existing_batch_id:
        expected = dict(batch_no=payment.batch_no, customer_id=payment.source_customer_id, currency=payment.currency, gross_amount=payment.gross_amount,
            collection_date=payment.collection_date, payment_type=payment.payment_type)
        if (existing is None or existing.transaction_mode == 'local'
                or any(getattr(existing, key) != value for key, value in expected.items())
                or existing.status != 'active' or _query(db, select(FinanceEvent.id).where(FinanceEvent.batch_id == existing.id), lock)):
            raise ValueError('原付款主记录已承接或事实不一致')
        # Nullable local metadata may be absent on a legacy row. A populated
        # identity or frozen rate is evidence, and cannot be silently replaced.
        for key in ('local_customer_id', 'bank_account_id', 'bank_reference', 'rate_to_cny', 'rate_to_usd',
                    'confirmed_date', 'confirmed_by', 'confirmed_at'):
            actual = getattr(existing, key)
            if actual is not None and actual != getattr(payment, key):
                raise ValueError('原付款已记录的银行、客户、汇率或确认事实与清单不一致')
        if (existing.actual_bank_fee != payment.actual_bank_fee
                or (existing.net_amount is not None and existing.net_amount != payment.gross_amount - payment.actual_bank_fee)):
            raise ValueError('原付款实际银行扣费或净到账金额与清单不一致')
        children = _query(db, select(Receipt.id).where(Receipt.batch_id == existing.id), lock)
        if set(children) != {row.existing_receipt_id for row in payment.allocations}:
            raise ValueError('必须核验原付款全部核销，不能遗漏跨订单责任')
    for reference in [payment.bank_reference, *(row.bank_reference for row in payment.refunds)]:
        batches = _query(db, select(ReceiptBatch.id).where(ReceiptBatch.bank_account_id == payment.bank_account_id,
            ReceiptBatch.bank_reference == reference), lock)
        events = _query(db, select(FinanceEvent.id).where(FinanceEvent.bank_account_id == payment.bank_account_id,
            FinanceEvent.bank_reference == reference), lock)
        if any(identity != payment.existing_batch_id or reference != payment.bank_reference for identity in batches) or events:
            raise ValueError('历史银行流水已记账，禁止换来源再次承接')
    for allocation in payment.allocations:
        invoice, _ = _order_proof(db, manifest, payment, allocation, lock)
        _legacy_receipt(db, payment, allocation, invoice, lock)
        if allocation.purpose != 'freight':
            receipt = SimpleNamespace(id=None, invoice_id=invoice.id, xiaoman_receipt_id=allocation.original_receipt_id,
                amount=allocation.amount, bank_charge=allocation.bank_charge, reversed_amount=allocation.reversed_amount,
                reversed_bank_charge=allocation.reversed_bank_charge)
            event = SimpleNamespace(action='opening_allocation', receipt_id=None, batch_id=None,
                business_date=manifest.cutover_date, amount=allocation.amount - allocation.reversed_amount,
                commission_amount_usd=allocation.remaining_commission_usd)
            paid_snapshot(db, event, receipt, source_customer_id=allocation.source_customer_id,
                payment_id=allocation.original_receipt_id, prior_reversals=allocation.prior_reversals,
                lock=lock, payment_batch=payment)


def _allocation_conflicts(db, body, lock):
    conflicts = []
    fresh_allocations = [allocation for payment in body.payments
        if _record(db, body, 'payment_opening', payment.external_id, lock) is None for allocation in payment.allocations]
    for identity in sorted({a.receivable_id for a in fresh_allocations}):
        target = _current(db, select(Receivable).where(Receivable.id == identity), lock)
        if target is None:
            continue
        rows = [a for a in fresh_allocations if a.receivable_id == identity]
        amount = sum((a.amount - a.reversed_amount for a in rows), finance.ZERO)
        fee = sum((a.bank_charge - a.reversed_bank_charge for a in rows), finance.ZERO)
        if (amount > target.amount + target.adjustment_amount or fee > target.handling_amount
                or amount - fee > target.amount + target.adjustment_amount - target.handling_amount):
            conflicts.append(dict(section='receivables', record_index=None, code='ar_opening_excess', message='跨付款核销本金或费用合计超过原应收责任'))
        invoice = _current(db, select(Invoice).where(Invoice.id == target.invoice_id), lock)
        if invoice is None or invoice.order_type != 'presale' or target.kind != 'goods':
            continue
        for purpose, amount_limit, fee_limit in (
            ('presale_deposit', invoice.local_deposit_amount, invoice.local_deposit_charge),
            ('presale_balance', target.amount + target.adjustment_amount - invoice.local_deposit_amount,
             target.handling_amount - invoice.local_deposit_charge),
        ):
            pool = [a for a in rows if a.purpose == purpose]
            paid = sum((a.amount - a.reversed_amount for a in pool), finance.ZERO)
            charge = sum((a.bank_charge - a.reversed_bank_charge for a in pool), finance.ZERO)
            if paid > amount_limit or charge > fee_limit or paid - charge > amount_limit - fee_limit:
                conflicts.append(dict(section='receivables', record_index=None, code='presale_opening_excess',
                    message='跨付款有效首款或尾款本金、费用超过冻结合同组成'))
    return conflicts


def preview(db, body, *, lock=False):
    conflicts = []
    previous = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == body.batch_key), lock)
    if previous and previous.manifest_hash != digest(body.model_dump(mode='json')):
        conflicts.append(dict(section='batch', record_index=None, code='batch_content_changed', message='批次身份已用于不同内容'))
    for index, payment in enumerate(body.payments):
        try:
            snapshot = payment.model_dump(mode='json')
            record = _record(db, body, 'payment_opening', payment.external_id, lock)
            if record:
                _assert_record(record, body, 'opening', 'payment_opening', payment.external_id, snapshot)
            else:
                _check_payment(db, body, payment, lock)
        except ValueError as exc:
            conflicts.append(dict(section='payments', record_index=index, code='opening_conflict', message=str(exc)))
    conflicts.extend(_allocation_conflicts(db, body, lock))
    return dict(manifest_hash=digest(body.model_dump(mode='json')), can_apply=not conflicts,
        payment_count=len(body.payments), conflicts=conflicts)


def _event(db, record, action, suffix, body, actor_id, **values):
    event = FinanceEvent(request_key=f'commerce-opening:{record.id}:{suffix}', request_hash=digest([record.content_hash, action, suffix]),
        action=action, business_date=body.cutover_date, created_by=actor_id,
        payload={'migration_record_id': record.id, **values.pop('payload', {})}, **values)
    db.add(event); db.flush()
    return event


def _post_payment(db, body, payment, record, actor_id):
    from app.commerce_migration.handover_service import bank_opening_identity
    from app.commerce_transition.service import policy
    bank_identity = bank_opening_identity(db, payment, body)
    row = finance.lock(db, ReceiptBatch, payment.existing_batch_id) if payment.existing_batch_id else ReceiptBatch(
        batch_no=payment.batch_no, customer_id=f'ark:{payment.local_customer_id}', currency=payment.currency,
        gross_amount=payment.gross_amount, collection_date=payment.collection_date, payment_type=payment.payment_type,
        request_key=f'commerce-opening-payment:{record.id}', request_hash=record.content_hash, created_by=actor_id)
    if row.id is None:
        db.add(row)
    else:
        row.version += 1
    for key in ('local_customer_id', 'bank_account_id', 'bank_reference', 'actual_bank_fee', 'rate_to_cny', 'rate_to_usd',
                'confirmed_date', 'confirmed_by', 'confirmed_at', 'remark'):
        setattr(row, key, getattr(payment, key))
    row.customer_id, row.transaction_mode, row.finance_status = f'ark:{payment.local_customer_id}', 'local', 'confirmed'
    row.net_amount = finance.money(payment.gross_amount - payment.actual_bank_fee)
    row.allocated_amount = finance.money(sum((r.amount - r.reversed_amount for r in payment.allocations), finance.ZERO))
    row.bank_charge_total = finance.money(sum((r.bank_charge - r.reversed_bank_charge for r in payment.allocations), finance.ZERO))
    row.refunded_amount = finance.money(sum((r.amount for r in payment.refunds), finance.ZERO))
    db.flush()
    record.snapshot = {**record.snapshot, '_bank_identity_id': bank_identity.id}
    if policy(db).phase == 'transition' and any(
            db.get(Invoice, allocation.invoice_id).transaction_mode == 'legacy' for allocation in payment.allocations):
        row.transaction_mode = 'opening'
    else:
        bank_identity.route = 'local'
        bank_identity.payment_ref = f'local:{row.id}'
    _event(db, record, 'opening_payment', 'payment', body, actor_id, batch_id=row.id,
        amount=payment.gross_amount, payload={'historical_collection_date': payment.collection_date.isoformat()})
    for index, refund in enumerate(payment.refunds):
        _event(db, record, 'opening_refund', f'refund:{index}', body, actor_id, batch_id=row.id, amount=-refund.amount,
            bank_account_id=row.bank_account_id, bank_reference=refund.bank_reference,
            payload={'historical_refund': refund.model_dump(mode='json')})
    allocations = []
    for index, allocation in enumerate(payment.allocations):
        invoice = finance.lock(db, Invoice, allocation.invoice_id)
        target = finance.lock(db, Receivable, allocation.receivable_id)
        receipt = finance.lock(db, Receipt, allocation.existing_receipt_id) if allocation.existing_receipt_id else Receipt(
            receipt_no=f'OPEN-ALLOC-{record.id}-{index}', invoice_id=invoice.id, batch_id=row.id,
            request_key=f'commerce-opening-receipt:{record.id}:{index}', request_hash=digest(allocation.model_dump(mode='json')),
            amount=allocation.amount, bank_charge=allocation.bank_charge, currency=row.currency,
            collection_date=allocation.collection_date, payment_type=row.payment_type, created_by=actor_id,
            xiaoman_order_id=invoice.xiaoman_order_id, xiaoman_receipt_id=allocation.original_receipt_id)
        if receipt.id is None:
            db.add(receipt)
        else:
            receipt.version += 1
        receipt.batch_id, receipt.receivable_id, receipt.purpose = row.id, target.id, allocation.purpose
        receipt.source, receipt.customer_id, receipt.sync_status = 'local', row.customer_id, 'not_applicable'
        receipt.reversed_amount, receipt.reversed_bank_charge = allocation.reversed_amount, allocation.reversed_bank_charge
        receipt.status = 'active' if receipt.effective_amount else 'reversed'
        receipt.collect_status = 1 if receipt.effective_amount else 0
        db.flush()
        event = _event(db, record, 'opening_allocation', f'allocation:{index}', body, actor_id, batch_id=row.id,
            receipt_id=receipt.id, receivable_id=target.id, amount=receipt.effective_amount,
            commission_amount_usd=allocation.remaining_commission_usd,
            payload={'opening': allocation.model_dump(mode='json')})
        if target.kind == 'goods':
            bind_paid_history(db, event, receipt, source_customer_id=allocation.source_customer_id,
                payment_id=allocation.original_receipt_id, prior_reversals=allocation.prior_reversals,
                actor_id=actor_id)
        target.paid_amount = finance.money(target.paid_amount + receipt.effective_amount)
        target.version += 1
        if target.paid_amount > target.amount + target.adjustment_amount:
            raise ValueError('跨付款累计历史核销超过整单应收')
        invoice.internal_received = finance.money(invoice.internal_received + receipt.effective_amount)
        invoice.internal_balance = finance.money(invoice.internal_balance - receipt.effective_amount)
        allocations.append(dict(receipt_id=receipt.id, event_id=event.id, external_id=allocation.external_id))
    db.flush()
    return dict(record_id=record.id, batch_id=row.id, external_id=payment.external_id, allocations=allocations)


def apply_manifest(db, body, user):
    from app.commerce_migration.handover_service import stage_invoices
    stage_invoices(db, sorted({a.invoice_id for p in body.payments for a in p.allocations}), body)
    with db.begin_nested():
        ledger = finance.book(db)
        actor_id = int(user['sub'])
        actor = _shared(db, select(ArkUser).where(ArkUser.id == actor_id), True)
        if actor is None or not actor.is_active or actor.deleted_at:
            raise ValueError('导入账号不可用')
        manifest_hash = digest(body.model_dump(mode='json'))
        prior = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == body.batch_key), True)
        if prior:
            if prior.manifest_hash != manifest_hash:
                raise ValueError('批次身份已用于不同内容')
            return prior.result
        finance.open_date(ledger, body.cutover_date)
        # Lock complete parent sets before any child proof or allocation.
        for identity in sorted({a.invoice_id for p in body.payments for a in p.allocations}):
            finance.lock(db, Invoice, identity)
        for identity in sorted({p.existing_batch_id for p in body.payments if p.existing_batch_id}):
            finance.lock(db, ReceiptBatch, identity)
        for identity in sorted({a.receivable_id for p in body.payments for a in p.allocations}):
            finance.lock(db, Receivable, identity)
        report = preview(db, body, lock=True)
        if not report['can_apply']:
            raise ValueError(f'资金期初清单存在{len(report["conflicts"])}项冲突，请先核对预览')
        # Authoritative checks happen before any posting, across all fresh rows.
        # A cached or substituted preview is never permission to mutate cash.
        for payment in body.payments:
            if _record(db, body, 'payment_opening', payment.external_id, True) is None:
                _check_payment(db, body, payment, True)
        if _allocation_conflicts(db, body, True):
            raise ValueError('跨付款核销与冻结合同责任存在冲突')
        batch = MigrationBatch(batch_key=body.batch_key, source=body.source, tenant=body.tenant,
            manifest_hash=manifest_hash, evidence_sha256=body.evidence_sha256, review_reference=body.review_reference,
            cutover_date=body.cutover_date, result={}, created_by=actor_id)
        db.add(batch); db.flush()
        result = dict(batch_key=body.batch_key, manifest_hash=manifest_hash, payments=[])
        for payment in body.payments:
            snapshot = payment.model_dump(mode='json')
            record = _record(db, body, 'payment_opening', payment.external_id, True)
            if record:
                _assert_record(record, body, 'opening', 'payment_opening', payment.external_id, snapshot)
                original = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == record.batch_key), True)
                mapping = next((r for r in original.result.get('payments', []) if r['record_id'] == record.id), None) if original else None
                if mapping is None:
                    raise ValueError('既有期初结果缺少完整关联，请核验后恢复')
            else:
                # Current locked checks are not replaced by a prior preview.
                record = MigrationRecord(batch_key=body.batch_key, source=body.source, tenant=body.tenant,
                    object_type='payment_opening', external_id=payment.external_id, role='opening',
                    content_hash=digest(snapshot), snapshot=snapshot)
                db.add(record); db.flush()
                mapping = _post_payment(db, body, payment, record, actor_id)
            result['payments'].append(mapping)
        batch.result = result
        db.flush()
        return result
