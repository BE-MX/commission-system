"""Resolve a reviewed legacy reservation once before opening physical balances."""
from decimal import Decimal
from sqlalchemy import select
from app.auth.models import ArkUser
from app.commerce_migration.models import MigrationBatch, MigrationRecord
from app.commerce_migration.service import _current, _record, _assert_record, digest
from app.commerce_migration.finance_service import _shared, _query
from app.finance import service as finance
from app.invoice.models import Invoice, InvoiceSyncLog
from app.semifinished.models import InvoiceAllocation, InventoryBalance, InventoryLedger, SemifinishedMaterial
from app.semifinished.inventory_service import claim_ledger


def _identity(row):
    return f'{row.invoice_id}:{row.operation_key}'


def evidence(row):
    return row.model_dump(mode='json', exclude={'source_material_record_id'})


def _check(db, body, row, lock):
    invoice = _current(db, select(Invoice).where(Invoice.id == row.invoice_id), lock)
    if (invoice is None or invoice.transaction_mode != 'legacy' or invoice.xiaoman_order_id != row.source_order_id
            or invoice.linked_sync_id or invoice.sync_attempt or invoice.sync_status == 'sync_uncertain'
            or invoice.status == 'cancel_pending'
            or invoice.cancellation and invoice.cancellation.get('status') not in {'remote_deleted', 'retained', 'aborted'}):
        raise ValueError('仅可核验已停止外部操作的原发票；在线本地单或远端未决动作不能处置')
    proof = _current(db, select(MigrationRecord).where(MigrationRecord.id == row.source_material_record_id), lock)
    batch = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == proof.batch_key), lock) if proof else None
    if (proof is None or proof.role != 'archive' or proof.object_type != 'material'
            or (proof.source, proof.tenant) != (body.source, body.tenant) or batch is None or batch.cutover_date != body.cutover_date
            or proof.snapshot != evidence(row)):
        raise ValueError('原操作结果须由同来源、同切换日的不可变完整核验凭证证明')
    pending = _query(db, select(InvoiceAllocation).where(InvoiceAllocation.invoice_id == invoice.id,
        InvoiceAllocation.status == 'pending').order_by(InvoiceAllocation.material_id), lock)
    if {a.id for a in pending} != {a.existing_allocation_id for a in row.allocations}:
        raise ValueError('必须核验原发票全部未决物料，不能遗漏或拼接其他批次')
    by_id = {a.id: a for a in pending}
    balances = {}
    for line in sorted(row.allocations, key=lambda item: item.material_id):
        original = by_id[line.existing_allocation_id]
        if ((original.material_id, original.operation_key, original.pending_at,
                original.allocated_qty_grams, original.pending_delta_grams) !=
                (line.material_id, row.operation_key, line.pending_at, line.allocated_qty_grams, line.pending_delta_grams)):
            raise ValueError('原pending操作身份、时间或数量已变化，须重新核验')
        closing = _current(db, select(MigrationRecord).where(MigrationRecord.role == 'opening',
            MigrationRecord.object_type == 'material_balance',
            MigrationRecord.snapshot['material_id'].as_integer() == line.material_id), lock)
        if closing:
            raise ValueError('物理期末已承接，禁止再处置原未决运动；须先在期初前完成核验')
        if _shared(db, select(SemifinishedMaterial).where(SemifinishedMaterial.id == line.material_id), lock) is None:
            raise ValueError('原半成品主档不存在')
        balance = _current(db, select(InventoryBalance).where(InventoryBalance.material_id == line.material_id), lock)
        if (balance is None or (balance.version, balance.on_hand_grams, balance.reserved_grams) !=
                (line.expected_balance_version, line.on_hand_grams, line.reserved_grams)):
            raise ValueError('原物料余额或版本已变化，须重新核验')
        delta = line.pending_delta_grams
        prior_keys = [f'invoice:{invoice.id}:{action}:{row.operation_key}:{line.material_id}' for action in ('finalize', 'release')]
        if _query(db, select(InventoryLedger.id).where(InventoryLedger.idempotency_key.in_(prior_keys)), lock):
            raise ValueError('原操作已有结束流水但pending未关闭，须核验差异而非重复过账')
        if delta > 0:
            reserve = _current(db, select(InventoryLedger).where(InventoryLedger.idempotency_key ==
                f'invoice:{invoice.id}:reserve:{row.operation_key}:{line.material_id}'), lock)
            if (reserve is None or (reserve.material_id, reserve.business_type, reserve.business_id,
                    reserve.movement_type, reserve.quantity_grams) != (line.material_id, 'invoice_sync', invoice.id, 'reserve', delta)
                    or balance.reserved_grams < delta or balance.on_hand_grams < delta):
                raise ValueError('原正差额缺少真实预占流水或余额不足，不能伪造释放/出库')
        balances[line.material_id] = balance
    accepted = _query(db, select(InvoiceSyncLog.id).where(InvoiceSyncLog.invoice_id == invoice.id,
        InvoiceSyncLog.inventory_operation_key == row.operation_key, InvoiceSyncLog.success == 1), lock)
    if row.outcome == 'not_accepted' and accepted:
        raise ValueError('原操作已有受理成功日志，不能声明未受理并释放占用')
    return by_id, balances


def _available(prepared):
    totals = {}
    for row, record, state in prepared:
        if record is not None:
            continue
        for line in row.allocations:
            balance = state[1][line.material_id]
            value = totals.setdefault(line.material_id, [balance, Decimal('0'), Decimal('0')])
            if row.outcome == 'accepted':
                value[1] += line.pending_delta_grams
            value[2] += max(line.pending_delta_grams, 0)
    for balance, delta, occupied in totals.values():
        hand, reserved = balance.on_hand_grams - delta, balance.reserved_grams - occupied
        if not 0 <= reserved <= hand <= Decimal('99999999999.999'):
            raise ValueError('整份原操作的合计出库/释放超过当前物料责任或库存精度')


def preview(db, body, *, lock=False):
    conflicts = []
    prepared = []
    prior = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == body.batch_key), lock)
    if prior and prior.manifest_hash != digest(body.model_dump(mode='json')):
        conflicts.append(dict(section='batch', record_index=None, code='content_changed', message='批次身份已用于不同内容'))
    for index, row in enumerate(body.resolutions):
        try:
            record = _record(db, body, 'material_resolution', _identity(row), lock)
            if record:
                _assert_record(record, body, 'opening', 'material_resolution', _identity(row), row.model_dump(mode='json'))
            else:
                prepared.append((row, None, _check(db, body, row, lock)))
        except ValueError as exc:
            conflicts.append(dict(section='resolutions', record_index=index, code='pending_conflict', message=str(exc)))
    try:
        _available(prepared)
    except ValueError as exc:
        conflicts.append(dict(section='resolutions', record_index=None, code='quantity_conflict', message=str(exc)))
    return dict(can_apply=not conflicts, manifest_hash=digest(body.model_dump(mode='json')), conflicts=conflicts)


def _post(db, row, record, allocations, balances, actor_id):
    before, after = [], []
    for line in sorted(row.allocations, key=lambda item: item.material_id):
        original, balance = allocations[line.existing_allocation_id], balances[line.material_id]
        before.append(dict(allocation_id=original.id, allocated=str(original.allocated_qty_grams),
            pending_delta=str(original.pending_delta_grams), operation_key=original.operation_key,
            pending_at=original.pending_at.isoformat(), on_hand=str(balance.on_hand_grams),
            reserved=str(balance.reserved_grams), version=balance.version))
        delta = line.pending_delta_grams
        accepted = row.outcome == 'accepted'
        hand = balance.on_hand_grams - delta if accepted else balance.on_hand_grams
        reserved = balance.reserved_grams - max(delta, 0)
        if accepted or delta > 0:
            action = 'finalize' if accepted else 'release'
            ledger, fresh = claim_ledger(db, material_id=line.material_id,
                movement_type=('outbound' if delta > 0 else 'reversal') if accepted else 'release',
                quantity_grams=-delta, on_hand_after=hand, reserved_after=reserved,
                business_type='invoice' if accepted else 'invoice_sync', business_id=row.invoice_id,
                idempotency_key=f'invoice:{row.invoice_id}:{action}:{row.operation_key}:{line.material_id}',
                operator_id=actor_id, remark=f'Reviewed pending result: migration record {record.id}')
            if not fresh:
                raise ValueError('原操作已生成运动，不能重复更新余额')
            balance.on_hand_grams, balance.reserved_grams = hand, reserved
            balance.version += 1
        if accepted:
            original.allocated_qty_grams += delta
        original.status, original.pending_delta_grams = 'allocated', 0
        original.operation_key = original.pending_at = None
        after.append(dict(allocation_id=original.id, allocated=str(original.allocated_qty_grams),
            on_hand=str(balance.on_hand_grams), reserved=str(balance.reserved_grams), version=balance.version))
    record.snapshot = {**record.snapshot, '_before': before, '_after': after}


def apply_manifest(db, body, user):
    from app.commerce_migration.handover_service import opening_policy
    opening_policy(db, body)
    with db.begin_nested():
        book = finance.book(db)
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
        finance.open_date(book, body.cutover_date)
        for identity in sorted(row.invoice_id for row in body.resolutions):
            finance.lock(db, Invoice, identity)
        records = [_record(db, body, 'material_resolution', _identity(row), True) for row in body.resolutions]
        material_ids = sorted({line.material_id for row, record in zip(body.resolutions, records, strict=True)
            if record is None for line in row.allocations})
        # Old recovery does not take the finance book. Every current material
        # balance must therefore be acquired in global order across invoices.
        for identity in material_ids:
            _shared(db, select(SemifinishedMaterial).where(SemifinishedMaterial.id == identity), True)
        for identity in material_ids:
            _current(db, select(InventoryBalance).where(InventoryBalance.material_id == identity), True)
        prepared = []
        for row, record in zip(body.resolutions, records, strict=True):
            if record:
                _assert_record(record, body, 'opening', 'material_resolution', _identity(row), row.model_dump(mode='json'))
                prepared.append((row, record, None))
            else:
                prepared.append((row, None, _check(db, body, row, True)))
        _available(prepared)
        batch = MigrationBatch(batch_key=body.batch_key, source=body.source, tenant=body.tenant,
            manifest_hash=manifest_hash, evidence_sha256=body.evidence_sha256, review_reference=body.review_reference,
            cutover_date=body.cutover_date, result={}, created_by=actor_id)
        db.add(batch); db.flush()
        result = dict(batch_key=body.batch_key, manifest_hash=manifest_hash, resolutions=[])
        for row, record, state in prepared:
            if record is None:
                record = MigrationRecord(batch_key=body.batch_key, source=body.source, tenant=body.tenant,
                    object_type='material_resolution', external_id=_identity(row), role='opening',
                    content_hash=digest(row.model_dump(mode='json')), snapshot=row.model_dump(mode='json'))
                db.add(record); db.flush()
                _post(db, row, record, *state, actor_id)
            result['resolutions'].append(dict(record_id=record.id, invoice_id=row.invoice_id,
                operation_key=row.operation_key, outcome=row.outcome, allocations=record.snapshot['_after']))
        batch.result = result
        db.flush()
        return result
