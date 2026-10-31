"""Reviewed opening adapters for the existing frozen responsibility protocol.

No shadow output or client-supplied success flag grants an opening. The source
manifests and the existing domain validators remain the complete evidence.
"""
from sqlalchemy import select

from app.commerce_transition import service as gates, transfer_service as transfers
from app.commerce_transition.models import InvoiceAuthority, TransferPreparation, ResourceScope
from app.commerce_migration.models import MigrationBatch, MigrationRecord
from app.commerce_migration.service import digest
from app.invoice.models import Invoice


def pending_original_requests(db, invoice_ids):
    """A remove acknowledgment does not finish its original local workflow."""
    if transfers._pending_original_requests(db, invoice_ids):
        return True
    originals = db.scalars(select(Invoice).where(Invoice.id.in_(invoice_ids)).with_for_update()
                           .execution_options(populate_existing=True)).all()
    if any(row.status == 'cancel_pending' or (row.cancellation and
            row.cancellation.get('status') not in {'remote_deleted', 'retained', 'aborted'}) for row in originals):
        return True
    from app.receipt.models import Receipt, ReceiptLog
    return db.scalar(select(Receipt.id).join(ReceiptLog, ReceiptLog.receipt_id == Receipt.id).where(
        Receipt.invoice_id.in_(invoice_ids), Receipt.status == 'active', ReceiptLog.action == 'delete_started')
        .with_for_update().limit(1)) is not None


def opening_policy(db, body=None):
    from app.core.config import get_settings
    current = gates.lock_policy(db)
    if get_settings().COMMERCE_SHADOW_EXECUTION_ONLY:
        raise ValueError('验证执行结果不能作为正式期初')
    source = str(getattr(body, 'source', '')).strip().lower()
    if source in {'shadow', 'replay', 'comparison'} or source.startswith(
            ('shadow-', 'shadow_', 'shadow:', 'ark-shadow', 'replay-', 'replay_', 'comparison-', 'comparison_')):
        raise ValueError('对比或重放结果不能作为正式期初')
    gates.require_phase(db, 'local')
    return current


def preparation_for(db, invoice_ids, *, required=True, lock=True):
    ids = set(invoice_ids)
    rows = db.scalars(select(TransferPreparation).where(TransferPreparation.state != 'completed')
        .order_by(TransferPreparation.id).with_for_update().execution_options(populate_existing=True)).all()
    matches = [row for row in rows if ids and ids.issubset(set(row.manifest['invoice_ids']))]
    if len(matches) != 1:
        if required:
            raise ValueError('承接必须关联同一完整冻结责任闭包')
        return None
    row = matches[0]
    for identity in sorted(ids):
        authority = gates._lock_authority(db, identity) if lock else db.get(InvoiceAuthority, identity)
        if (authority is None or authority.route != 'legacy' or authority.state != 'frozen'
                or authority.epoch != row.manifest['epochs'][str(identity)]):
            raise ValueError('原办理权、冻结或epoch已变化')
    return row


def begin_orders(db, body):
    current = opening_policy(db, body)
    if current.phase != 'transition':
        return None
    existing = db.scalar(select(MigrationBatch).where(MigrationBatch.batch_key == body.batch_key).with_for_update())
    if existing:
        if existing.manifest_hash != digest(body.model_dump(mode='json')):
            raise ValueError('批次身份已用于不同清单')
        return existing.result.get('handover_preparation_id')
    ids = {row.existing_invoice_id for row in body.orders}
    if None in ids:
        raise ValueError('过渡期仅可承接明确复用的原发票ID，不能另造剩余订单')
    for identity in sorted(ids):
        invoice = db.scalar(select(Invoice).where(Invoice.id == identity).with_for_update().execution_options(populate_existing=True))
        if invoice is None or invoice.transaction_mode != 'legacy':
            raise ValueError('原发票必须仍由旧路线正式办理')
        gates.ensure_authority(db, invoice, route='legacy', confirmed=True,
            source_evidence={'explicit_transaction_mode': 'legacy', 'review_reference': body.review_reference,
                             'evidence_sha256': body.evidence_sha256})
    key = 'opening:' + digest([body.source, body.tenant, body.batch_key])[:48]
    row = transfers.prepare_transfer(db, invoice_ids=sorted(ids), target_route='local', request_key=key,
        checkpoint=f'{body.cutover_date}:{body.evidence_sha256}',
        evidence={'manifest_hash': digest(body.model_dump(mode='json')), 'review_reference': body.review_reference,
                  'evidence_sha256': body.evidence_sha256, 'source': body.source, 'tenant': body.tenant})
    if pending_original_requests(db, row.manifest['invoice_ids']):
        row.state = 'waiting'
    return row.id


def stage_invoices(db, ids, body=None):
    current = opening_policy(db, body)
    if current.phase == 'transition' and ids:
        originals = []
        for identity in sorted(set(ids)):
            invoice = db.scalar(select(Invoice).where(Invoice.id == identity).with_for_update()
                                .execution_options(populate_existing=True))
            if invoice is None:
                raise ValueError('原订单不存在')
            if invoice.transaction_mode == 'local':
                gates.require_route(db, invoice, 'local')
            else:
                originals.append(identity)
        if not originals:
            return None
        row = preparation_for(db, originals)
        if pending_original_requests(db, row.manifest['invoice_ids']):
            raise ValueError('原在途或unknown尚未核清，禁止写入期初')
        return row
    return None


def staged_invoice(db, invoice):
    if invoice is None:
        return False
    if invoice.transaction_mode == 'local':
        return True
    if invoice.transaction_mode == 'legacy' and invoice.commerce_status == 'opening':
        return preparation_for(db, [invoice.id], required=False, lock=False) is not None
    return False


def register_opening_resources(db, body):
    opening_policy(db, body)
    evidence = {'checkpoint': f'{body.cutover_date}:{body.evidence_sha256}',
        'old_responsibilities_cleared': {'review_reference': body.review_reference, 'manifest_hash': digest(body.model_dump(mode='json'))},
        'writers_enforced': {'policy_version': gates.policy(db).version}, 'evidence_sha256': body.evidence_sha256}
    entries = [('sku', str(r.local_sku_id), str(r.warehouse_id)) for r in getattr(body, 'stocks', [])]
    entries += [('material', str(r.material_id), '*') for r in getattr(body, 'materials', [])]
    for kind, identity, bucket in sorted(set(entries)):
        old = db.scalar(select(ResourceScope).where(ResourceScope.resource_kind == kind,
            ResourceScope.resource_key == identity, ResourceScope.warehouse_key == bucket).with_for_update())
        if old is None:
            gates.register_resource_scope(db, route='local', resource_kind=kind, resource_key=identity,
                                          warehouse_key=bucket, evidence=evidence)
        elif old.route != 'local' or old.state != 'active':
            raise ValueError('原资源不归本地或已冻结，必须先完成资源责任核验')


def activation_preparation(db, body, *, lock=True):
    proofs = db.scalars(select(MigrationRecord).where(MigrationRecord.id.in_(
        [r.order_binding_record_id for r in body.orders])).with_for_update()).all()
    ids = sorted(p.local_invoice_id for p in proofs if p.local_invoice_id)
    if not ids:
        return None
    row = preparation_for(db, ids, required=gates.policy(db).phase == 'transition', lock=lock)
    if row and ids != row.manifest['invoice_ids']:
        raise ValueError('放行必须一次覆盖完整共享资金、生产及订单闭包')
    return row


def reserve_opening_line(db, proof, line, warehouse_id, quantity, actor_id, preparation):
    """Private frozen-opening writer; ordinary reservations never use this path."""
    from app.inventory.service import _bucket, _claim_document, _move
    from app.inventory.reservation_service import _reservation
    authority = gates._lock_authority(db, proof.local_invoice_id)
    if (proof.local_invoice_id not in preparation.manifest['invoice_ids'] or authority.state != 'frozen'
            or authority.route != 'legacy' or authority.epoch != preparation.manifest['epochs'][str(proof.local_invoice_id)]):
        raise ValueError('期初预占缺少同锁冻结原责任')
    key = f'opening-reserve:{proof.id}:{line.id}:{warehouse_id}'
    document, fresh = _claim_document(db, key, {'opening_record_id': proof.id, 'preparation_id': preparation.id,
        'item_id': line.id, 'warehouse_id': warehouse_id, 'quantity': quantity}, kind='reserve',
        reason='Reviewed opening reservation', created_by=actor_id, source_type='commerce_opening', source_id=str(proof.id))
    if fresh:
        bucket = _bucket(db, warehouse_id, line.local_sku_id, 'sellable', create=False)
        reservation = _reservation(db, line, warehouse_id, create=True)
        _move(db, document, 1, bucket, 0, quantity)
        reservation.reserved += quantity
        line.stock_reserved_quantity += quantity
    return document


def bank_opening_identity(db, payment, body):
    from app.finance.models import BankAccount
    from app.finance.transition_identity import domain_for
    from app.commerce_transition.models import BankIdentity
    account = db.scalar(select(BankAccount).where(BankAccount.id == payment.bank_account_id).with_for_update())
    if account is None:
        raise ValueError('原银行账户不存在')
    domain = domain_for(db, account)
    row = db.scalar(select(BankIdentity).where(BankIdentity.domain_id == domain.id,
        BankIdentity.transaction_id == payment.bank_reference).with_for_update().execution_options(populate_existing=True))
    references = {f'legacy-batch:{payment.existing_batch_id}'} if payment.existing_batch_id else {
        f'legacy-receipt:{a.existing_receipt_id}' for a in payment.allocations if a.existing_receipt_id}
    old_orders = any(db.get(Invoice, allocation.invoice_id).transaction_mode == 'legacy'
                     for allocation in payment.allocations)
    if references or (gates.policy(db).phase == 'transition' and old_orders):
        if (row is None or row.route != 'legacy' or row.payment_ref not in references
                or row.amount != payment.gross_amount or row.currency != payment.currency):
            raise ValueError('旧款须先按原银行总额核验唯一身份；共享付款必须复用完整原批次')
        return row
    return gates.claim_bank_identity(db, domain_id=domain.id, transaction_id=payment.bank_reference,
        route='local', currency=payment.currency, amount=payment.gross_amount,
        payer_evidence={'bank_identity_verified': True, 'opening_reference': payment.external_id, 'bank_reference': payment.bank_reference,
                        'gross_amount': str(payment.gross_amount), 'currency': payment.currency,
                        'source_manifest_hash': digest(body.model_dump(mode='json')),
                        'evidence_sha256': body.evidence_sha256, 'review_reference': body.review_reference}).identity


def finish_bank_openings(db, invoice_ids, preparation_id=None):
    from app.commerce_transition.models import BankIdentity
    from app.invoice.settlement_models import ReceiptBatch
    ids = set(invoice_ids)
    records = db.scalars(select(MigrationRecord).where(MigrationRecord.role == 'opening',
        MigrationRecord.object_type == 'payment_opening').with_for_update()).all()
    for proof in records:
        members = {a['invoice_id'] for a in proof.snapshot['allocations']}
        if not members.intersection(ids):
            continue
        if not members.issubset(ids):
            raise ValueError('共享付款全部核销订单必须同一闭包启用，不能另造可用本金')
        batch = db.get(MigrationBatch, proof.batch_key)
        mapping = next((r for r in batch.result['payments'] if r['record_id'] == proof.id), None)
        identity = db.scalar(select(BankIdentity).where(BankIdentity.id == proof.snapshot.get('_bank_identity_id'))
            .with_for_update().execution_options(populate_existing=True))
        if mapping is None or identity is None:
            raise ValueError('原银行唯一身份与期初结果关联缺失')
        payment = db.scalar(select(ReceiptBatch).where(ReceiptBatch.id == mapping['batch_id']).with_for_update())
        if identity.amount != payment.gross_amount or identity.currency != payment.currency:
            raise ValueError('原银行本金、原币与期初不守恒')
        prior = identity.payment_ref
        identity.route, identity.payment_ref = 'local', f'local:{payment.id}'
        identity.payer_evidence = {**identity.payer_evidence, 'handover': {'preparation_id': preparation_id,
            'opening_record_id': proof.id, 'previous_payment_ref': prior, 'principal_recreated': False}}
        payment.transaction_mode = 'local'


def verification_receipt(db, prepared, productions):
    """Build references only after activation's real seven-part check succeeds."""
    invoice_ids = {invoice.id for _, invoice, _ in prepared}
    records = db.scalars(select(MigrationRecord).where(MigrationRecord.role == 'opening').with_for_update()).all()
    def refs(kind):
        return [{'record_id': p.id, 'source_hash': p.content_hash, 'batch_key': p.batch_key}
                for p in records if p.object_type == kind and (p.local_invoice_id in invoice_ids
                or any(a.get('invoice_id') in invoice_ids for a in p.snapshot.get('allocations', []))
                or p.snapshot.get('order_binding_record_id') in {proof.id for proof, _, _ in prepared})]
    contracts = [{'record_id': p.id, 'source_hash': p.content_hash, 'invoice_id': invoice.id,
                  'business_version': invoice.commerce_version} for p, invoice, _ in prepared]
    return {'contract': contracts, 'funds': {'contracts': contracts, 'payments': refs('payment_opening')},
        'fulfillment': {'contracts': contracts, 'shipments': refs('shipment_opening')},
        'inventory': {'lines': sorted(line.id for _, _, lines in prepared for line in lines.values())},
        'production': {'orders': [p.id for p in productions], 'declared': [p.snapshot['production_ids'] for p, _, _ in prepared]},
        'media': {'shipments': refs('shipment_opening'), 'declared': [p.snapshot['historical_shipment_ids'] for p, _, _ in prepared]},
        'commission': {'payments': refs('payment_opening'), 'contracts': contracts}}
