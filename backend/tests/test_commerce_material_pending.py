"""Known old outcomes close exact reservations; unknowns cannot consume stock."""
from datetime import date, datetime
from decimal import Decimal
import pytest
from sqlalchemy import select, func
from pydantic import ValidationError
from app.commerce_migration import material_pending_service as service, service as archive
from app.commerce_migration.material_pending_schemas import MaterialResolutionManifest
from app.commerce_migration.schemas import ImportManifest
from app.commerce_migration.models import MigrationRecord
from app.invoice.models import Invoice, InvoiceSyncLog
from app.semifinished.models import InvoiceAllocation, SemifinishedMaterial, InventoryBalance, InventoryLedger
from app.semifinished.inventory_service import write_ledger
from tests.test_invoice_commerce import buyer
from tests.test_inventory_local import stock

DAY = date(2026, 10, 3)
PENDING = datetime(2026, 10, 3, 0, 5)


def inputs(db, buyer, *, delta='100.125', outcome='accepted', material=None, tag='A', reserved=None):
    user = buyer[1]
    invoice = Invoice(invoice_no=f'PENDING-{tag}', order_type='production', customer_id='OLD-CUSTOMER',
        customer_name='Original buyer', xiaoman_order_id=f'PENDING-ORDER-{tag}', currency='USD', invoice_date=DAY,
        total_amount=1000, product_amount=1000, status='synced', sync_status='synced', created_by=int(user['sub']))
    if material is None:
        material = SemifinishedMaterial(material_code=f'PENDING-MAT-{tag}', size='18',
            color_code=f'Black-{tag}', color_key=f'black-{tag}')
        db.add(material); db.flush()
        balance = InventoryBalance(material_id=material.id, on_hand_grams=Decimal('1000'),
            reserved_grams=Decimal(reserved or max(Decimal(delta), 0)), version=1)
        db.add(balance); db.flush()
    else:
        balance = db.scalar(select(InventoryBalance).where(InventoryBalance.material_id == material.id))
    db.add(invoice); db.flush()
    allocation = InvoiceAllocation(invoice_id=invoice.id, material_id=material.id, allocated_qty_grams=Decimal('200'),
        pending_delta_grams=Decimal(delta), operation_key=f'pending-op-{tag}', pending_at=PENDING, status='pending')
    db.add(allocation); db.flush()
    if Decimal(delta) > 0:
        write_ledger(db, balance=balance, movement_type='reserve', quantity_grams=Decimal(delta), business_type='invoice_sync',
            business_id=invoice.id, idempotency_key=f'invoice:{invoice.id}:reserve:pending-op-{tag}:{material.id}',
            operator_id=int(user['sub']), remark='Original committed reservation')
    row = dict(invoice_id=invoice.id, source_order_id=invoice.xiaoman_order_id, operation_key=allocation.operation_key,
        outcome=outcome, evidence_reference='Synthetic definitive operation result reviewed',
        source_material_record_id=1, allocations=[dict(existing_allocation_id=allocation.id, material_id=material.id,
            allocated_qty_grams='200', pending_delta_grams=delta, pending_at=PENDING, expected_balance_version=balance.version,
            on_hand_grams=str(balance.on_hand_grams), reserved_grams=str(balance.reserved_grams))])
    body = MaterialResolutionManifest(batch_key=f'pending-result-{tag}', source='okki', tenant='pending-tenant',
        cutover_date=DAY, evidence_sha256='a'*64, review_reference='Synthetic accepted/rejected evidence', resolutions=[row])
    proof = archive.apply_manifest(db, ImportManifest(batch_key=f'pending-source-{tag}', source=body.source,
        tenant=body.tenant, cutover_date=DAY, evidence_sha256='b'*64, review_reference=body.review_reference,
        catalog=[], archives=[dict(object_type='material', external_id=f'pending-proof-{tag}', snapshot=service.evidence(body.resolutions[0]))]), user)
    body = body.model_copy(update={'resolutions': [body.resolutions[0].model_copy(update={'source_material_record_id': proof['archives'][0]['record_id']})]})
    db.commit()
    return body, invoice, allocation, balance, material


@pytest.mark.parametrize('delta,outcome,hand,allocated,count', [
    ('100.125', 'accepted', '899.875', '300.125', 2),
    ('100.125', 'not_accepted', '1000.000', '200.000', 2),
    ('-100.125', 'accepted', '1100.125', '99.875', 1),
    ('-100.125', 'not_accepted', '1000.000', '200.000', 0),
])
def test_known_outcome_resolves_exact_delta_once_and_replay_preserves_new_activity(db, buyer, delta, outcome, hand, allocated, count):
    body, invoice, allocation, balance, _ = inputs(db, buyer, delta=delta, outcome=outcome)
    before = db.scalar(select(func.count()).select_from(InventoryLedger))
    assert service.preview(db, body)['can_apply']
    assert allocation.status == 'pending' and db.scalar(select(func.count()).select_from(InventoryLedger)) == before
    result = service.apply_manifest(db, body, buyer[1]); db.commit()
    assert (balance.on_hand_grams, balance.reserved_grams) == (Decimal(hand), 0)
    assert allocation.allocated_qty_grams == Decimal(allocated) and allocation.status == 'allocated'
    assert not allocation.pending_delta_grams and allocation.pending_at is allocation.operation_key is None
    assert db.scalar(select(func.count()).select_from(InventoryLedger)) == count
    assert invoice.sync_status == 'synced' and invoice.transaction_mode == 'legacy'
    record = db.get(MigrationRecord, result['resolutions'][0]['record_id'])
    assert record.snapshot['_before'][0]['operation_key'] == body.resolutions[0].operation_key
    assert record.snapshot['_after'][0]['allocated'] == str(Decimal(allocated))
    # Honest later movement; replay neither rechecks old versions nor resets it.
    balance.on_hand_grams += Decimal('5.125'); balance.version += 1
    write_ledger(db, balance=balance, movement_type='inbound', quantity_grams=Decimal('5.125'),
        business_type='manual', idempotency_key='new-safe-receive', operator_id=int(buyer[1]['sub']))
    db.commit()
    assert service.apply_manifest(db, body, buyer[1]) == result
    repeated = service.apply_manifest(db, body.model_copy(update={'batch_key': 'second-proof-batch'}), buyer[1]); db.commit()
    assert repeated['resolutions'] == result['resolutions']
    assert balance.on_hand_grams == Decimal(hand) + Decimal('5.125')


def test_unknown_or_changed_source_cannot_release_a_real_pending_reservation(db, buyer):
    body, _, allocation, balance, _ = inputs(db, buyer, outcome='not_accepted')
    raw = body.model_dump(mode='json'); raw['resolutions'][0]['outcome'] = 'unknown'
    with pytest.raises(ValidationError):
        MaterialResolutionManifest.model_validate(raw)
    wrong = body.model_copy(update={'resolutions': [body.resolutions[0].model_copy(update={'outcome': 'accepted'})]})
    assert not service.preview(db, wrong)['can_apply']
    with pytest.raises(ValueError, match='凭证'):
        service.apply_manifest(db, wrong, buyer[1])
    db.commit()
    assert allocation.status == 'pending' and balance.reserved_grams == Decimal('100.125') and balance.on_hand_grams == 1000


def test_not_accepted_conflicts_with_actual_success_log_and_missing_original_reservation(db, buyer):
    body, invoice, allocation, balance, _ = inputs(db, buyer, outcome='not_accepted')
    db.add(InvoiceSyncLog(invoice_id=invoice.id, action='create', success=1, inventory_operation_key=allocation.operation_key,
        created_at=datetime(2026, 10, 3, 0, 6))); db.flush()
    assert not service.preview(db, body)['can_apply']
    with pytest.raises(ValueError, match='成功日志'):
        service.apply_manifest(db, body, buyer[1])
    db.commit()
    assert allocation.status == 'pending' and balance.reserved_grams == Decimal('100.125')
    db.query(InvoiceSyncLog).delete(); db.query(InventoryLedger).delete(); db.flush()
    assert not service.preview(db, body)['can_apply']
    with pytest.raises(ValueError, match='预占流水'):
        service.apply_manifest(db, body, buyer[1])


def test_aggregate_two_operations_cannot_release_more_than_actual_reserved(db, buyer):
    first, _, a, balance, material = inputs(db, buyer, reserved='150')
    second, _, b, _, _ = inputs(db, buyer, material=material, tag='B')
    body = first.model_copy(update={'resolutions': first.resolutions + second.resolutions})
    assert not service.preview(db, body)['can_apply']
    with pytest.raises(ValueError, match='合计'):
        service.apply_manifest(db, body, buyer[1])
    db.commit()
    assert a.status == b.status == 'pending' and balance.reserved_grams == 150 and balance.on_hand_grams == 1000


def test_late_failure_savepoint_restores_pending_and_balance_even_if_caller_commits(db, buyer, monkeypatch):
    body, _, allocation, balance, _ = inputs(db, buyer)
    original = service._post
    def fail(*args):
        original(*args)
        raise ValueError('Synthetic late pending failure')
    monkeypatch.setattr(service, '_post', fail)
    before = db.scalar(select(func.count()).select_from(InventoryLedger))
    with pytest.raises(ValueError, match='late pending'):
        service.apply_manifest(db, body, buyer[1])
    db.commit()
    assert allocation.status == 'pending' and allocation.pending_delta_grams == Decimal('100.125')
    assert balance.on_hand_grams == 1000 and balance.reserved_grams == Decimal('100.125')
    assert db.scalar(select(func.count()).select_from(InventoryLedger)) == before


@pytest.mark.parametrize('field,value', [('expected_balance_version', 99), ('allocated_qty_grams', Decimal('201')), ('pending_delta_grams', Decimal('100'))])
def test_stale_review_quantities_and_versions_are_rejected_without_writes(db, buyer, field, value):
    body, _, allocation, balance, _ = inputs(db, buyer)
    line = body.resolutions[0].allocations[0].model_copy(update={field: value})
    revised = body.resolutions[0].model_copy(update={'allocations': [line]})
    wrong = body.model_copy(update={'resolutions': [revised]})
    assert not service.preview(db, wrong)['can_apply']
    with pytest.raises(ValueError):
        service.apply_manifest(db, wrong, buyer[1])
    assert allocation.status == 'pending' and balance.reserved_grams == Decimal('100.125')


@pytest.mark.parametrize('target,field,value,message', [
    ('balance', 'version', 2, '版本已变化'),
    ('balance', 'reserved_grams', Decimal('99'), '版本已变化'),
    ('allocation', 'pending_delta_grams', Decimal('101'), '数量已变化'),
    ('invoice', 'transaction_mode', 'local', '在线本地单'),
    ('invoice', 'sync_status', 'sync_uncertain', '远端未决'),
    ('invoice', 'cancellation', {'status': 'deleting', 'token': 'synthetic-live-deletion', 'lease_until': '2099-10-03T00:10:00'}, '远端未决'),
])
def test_current_state_change_after_review_cannot_be_bypassed_by_original_proof(db, buyer, target, field, value, message):
    body, invoice, allocation, balance, _ = inputs(db, buyer)
    assert service.preview(db, body)['can_apply']
    entity = {'balance': balance, 'allocation': allocation, 'invoice': invoice}[target]
    setattr(entity, field, value); db.commit()
    before = db.scalar(select(func.count()).select_from(InventoryLedger))
    assert not service.preview(db, body)['can_apply']
    with pytest.raises(ValueError, match=message):
        service.apply_manifest(db, body, buyer[1])
    db.commit()
    assert allocation.status == 'pending' and db.scalar(select(func.count()).select_from(InventoryLedger)) == before


def test_declared_pending_time_is_beijing_naive_and_must_precede_cutover_date(db, buyer, monkeypatch):
    body, _, _, _, _ = inputs(db, buyer)
    monkeypatch.setenv('TZ', 'America/Los_Angeles')
    raw = body.model_dump(mode='json')
    raw['resolutions'][0]['allocations'][0]['pending_at'] = '2026-10-03T00:05:00'
    assert MaterialResolutionManifest.model_validate(raw).resolutions[0].allocations[0].pending_at == PENDING
    raw['resolutions'][0]['allocations'][0]['pending_at'] = '2026-10-04T00:00:00'
    with pytest.raises(ValidationError, match='晚于切换日'):
        MaterialResolutionManifest.model_validate(raw)
    raw['resolutions'][0]['allocations'][0]['pending_at'] = '2026-10-02T16:05:00Z'
    with pytest.raises(ValidationError, match='北京时间'):
        MaterialResolutionManifest.model_validate(raw)


def test_one_original_operation_preserves_individual_material_timestamps_and_resolves_all_rows(db, buyer):
    body, invoice, first, first_balance, _ = inputs(db, buyer)
    material = SemifinishedMaterial(material_code='PENDING-MAT-SECOND', size='20', color_code='Brown', color_key='brown')
    db.add(material); db.flush()
    balance = InventoryBalance(material_id=material.id, on_hand_grams=500, reserved_grams=Decimal('50.025'), version=1)
    second = InvoiceAllocation(invoice_id=invoice.id, material_id=material.id, allocated_qty_grams=0,
        pending_delta_grams=Decimal('50.025'), operation_key=first.operation_key,
        pending_at=datetime(2026, 10, 3, 0, 5, 2), status='pending')
    db.add_all([balance, second]); db.flush()
    write_ledger(db, balance=balance, movement_type='reserve', quantity_grams=Decimal('50.025'), business_type='invoice_sync',
        business_id=invoice.id, idempotency_key=f'invoice:{invoice.id}:reserve:{first.operation_key}:{material.id}',
        operator_id=int(buyer[1]['sub']))
    raw = body.model_dump(mode='json')
    raw['resolutions'][0]['allocations'].append(dict(existing_allocation_id=second.id, material_id=material.id,
        allocated_qty_grams='0', pending_delta_grams='50.025', pending_at=second.pending_at.isoformat(),
        expected_balance_version=1, on_hand_grams='500.000', reserved_grams='50.025'))
    amended = MaterialResolutionManifest.model_validate(raw)
    proof = archive.apply_manifest(db, ImportManifest(batch_key='complete-pending-proof', source=body.source, tenant=body.tenant,
        cutover_date=DAY, evidence_sha256='d'*64, review_reference='Synthetic full original multi-material operation', catalog=[],
        archives=[dict(object_type='material', external_id='complete-pending-proof', snapshot=service.evidence(amended.resolutions[0]))]), buyer[1])
    amended = amended.model_copy(update={'resolutions': [amended.resolutions[0].model_copy(update={'source_material_record_id': proof['archives'][0]['record_id']})]})
    db.commit()
    assert not service.preview(db, body)['can_apply']  # Original one-row review cannot omit the second material.
    assert service.preview(db, amended)['can_apply']
    result = service.apply_manifest(db, amended, buyer[1]); db.commit()
    assert first.status == second.status == 'allocated'
    assert first_balance.on_hand_grams == Decimal('899.875') and balance.on_hand_grams == Decimal('449.975')
    record = db.get(MigrationRecord, result['resolutions'][0]['record_id'])
    assert [row['pending_at'] for row in record.snapshot['_before']] == ['2026-10-03T00:05:00', '2026-10-03T00:05:02']
