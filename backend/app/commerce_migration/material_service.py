"""An old material issue is evidence, never a second physical deduction."""
from decimal import Decimal
from sqlalchemy import select
from app.auth.models import ArkUser
from app.commerce_migration.models import MigrationBatch, MigrationRecord
from app.commerce_migration.service import _current, _record, _assert_record, digest
from app.commerce_migration.finance_service import _shared
from app.finance import service as finance
from app.invoice.models import Invoice
from app.semifinished.models import InvoiceAllocation


def _check(db, body, row, lock):
    proof = _current(db, select(MigrationRecord).where(MigrationRecord.id == row.order_binding_record_id), lock)
    if (proof is None or proof.role != 'opening' or proof.object_type != 'order_binding'
            or (proof.source, proof.tenant) != (body.source, body.tenant)
            or row.existing_allocation_id not in proof.snapshot['material_allocation_ids']):
        raise ValueError('原已扣量须关联同来源整单完整半成品责任清单')
    invoice = _current(db, select(Invoice).where(Invoice.id == proof.local_invoice_id), lock)
    batch = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == proof.batch_key), lock)
    if invoice is None or invoice.commerce_status != 'opening' or batch.cutover_date != body.cutover_date:
        raise ValueError('原已扣量仅可承接同切换日尚未启用订单')
    allocation = _current(db, select(InvoiceAllocation).where(InvoiceAllocation.id == row.existing_allocation_id), lock)
    if (allocation is None or allocation.invoice_id != invoice.id or allocation.material_id != row.material_id
            or allocation.status != 'allocated' or allocation.allocated_qty_grams != row.allocated_qty_grams
            or allocation.pending_delta_grams or allocation.pending_at or allocation.operation_key):
        raise ValueError('原已扣量或pending结果尚未核验，禁止重复扣料或抹除未决责任')
    source = _current(db, select(MigrationRecord).where(MigrationRecord.id == row.source_material_record_id), lock)
    expected = dict(source_order_id=proof.external_id, existing_allocation_id=allocation.id,
        material_id=allocation.material_id)
    if (source is None or source.role != 'archive' or source.object_type != 'material'
            or (source.source, source.tenant) != (body.source, body.tenant)
            or any(source.snapshot.get(key) != value for key, value in expected.items())):
        raise ValueError('原已扣量须有同来源不可变物料凭证')
    try:
        source_quantity = Decimal(str(source.snapshot['allocated_qty_grams']))
    except (KeyError, ArithmeticError) as exc:
        raise ValueError('原已扣量凭证缺少完整克数') from exc
    if source_quantity != row.allocated_qty_grams:
        raise ValueError('原已扣量与核验凭证克数不一致')
    closing = _current(db, select(MigrationRecord).where(MigrationRecord.role == 'opening', MigrationRecord.object_type == 'material_balance',
        MigrationRecord.snapshot['material_id'].as_integer() == row.material_id), lock)
    closing_batch = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == closing.batch_key), lock) if closing else None
    if closing_batch is None or closing_batch.cutover_date != body.cutover_date:
        raise ValueError('原已扣物料须先核验同日物理期末实存，不能再次领料')
    return allocation


def preview(db, body, *, lock=False):
    conflicts = []
    prior = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == body.batch_key), lock)
    if prior and prior.manifest_hash != digest(body.model_dump(mode='json')):
        conflicts.append(dict(section='batch', record_index=None, code='content_changed', message='批次身份已用于不同内容'))
    for index, row in enumerate(body.allocations):
        try:
            record = _record(db, body, 'material_allocation', str(row.existing_allocation_id), lock)
            if record:
                _assert_record(record, body, 'opening', 'material_allocation', str(row.existing_allocation_id), row.model_dump(mode='json'))
            else:
                _check(db, body, row, lock)
        except ValueError as exc:
            conflicts.append(dict(section='allocations', record_index=index, code='material_conflict', message=str(exc)))
    return dict(can_apply=not conflicts, manifest_hash=digest(body.model_dump(mode='json')), conflicts=conflicts)


def apply_manifest(db, body, user):
    from app.commerce_migration.handover_service import stage_invoices
    proofs = [db.get(MigrationRecord, row.order_binding_record_id) for row in body.allocations]
    stage_invoices(db, [p.local_invoice_id for p in proofs if p and p.local_invoice_id], body)
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
        proofs = [_current(db, select(MigrationRecord).where(MigrationRecord.id == row.order_binding_record_id), True) for row in body.allocations]
        for identity in sorted({proof.local_invoice_id for proof in proofs if proof and proof.local_invoice_id}):
            finance.lock(db, Invoice, identity)
        for row in body.allocations:
            record = _record(db, body, 'material_allocation', str(row.existing_allocation_id), True)
            if record:
                _assert_record(record, body, 'opening', 'material_allocation', str(row.existing_allocation_id), row.model_dump(mode='json'))
            else:
                _check(db, body, row, True)
        batch = MigrationBatch(batch_key=body.batch_key, source=body.source, tenant=body.tenant, manifest_hash=manifest_hash,
            evidence_sha256=body.evidence_sha256, review_reference=body.review_reference, cutover_date=body.cutover_date,
            result={}, created_by=actor_id)
        db.add(batch); db.flush()
        result = dict(batch_key=body.batch_key, manifest_hash=manifest_hash, allocations=[])
        for row in body.allocations:
            record = _record(db, body, 'material_allocation', str(row.existing_allocation_id), True)
            if record is None:
                record = MigrationRecord(batch_key=body.batch_key, source=body.source, tenant=body.tenant,
                    object_type='material_allocation', external_id=str(row.existing_allocation_id), role='opening',
                    content_hash=digest(row.model_dump(mode='json')), snapshot=row.model_dump(mode='json'))
                db.add(record); db.flush()
            result['allocations'].append(dict(record_id=record.id, existing_allocation_id=row.existing_allocation_id))
        batch.result = result
        db.flush()
        return result
