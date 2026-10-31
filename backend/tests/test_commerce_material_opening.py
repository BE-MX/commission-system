"""Prior invoice material issues do not deduct physical stock again."""
from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import select, func
from app.commerce_migration import material_service as service, service as archive, order_service, inventory_service
from app.commerce_migration.order_schemas import OrderOpeningManifest
from app.commerce_migration.material_schemas import MaterialOpeningManifest
from app.commerce_migration.schemas import ImportManifest
from app.commerce_migration.inventory_schemas import InventoryOpeningManifest
from app.invoice.models import Invoice
from app.semifinished.models import InvoiceAllocation, SemifinishedMaterial, InventoryBalance, InventoryLedger
from tests.test_commerce_order_opening import inputs as order_inputs
from tests.test_invoice_commerce import buyer
from tests.test_inventory_local import stock

DAY = date(2026, 10, 3)


def inputs(db, buyer):
    raw = order_inputs(db, buyer)
    row = OrderOpeningManifest.model_validate(raw).orders[0]
    invoice = Invoice(**{k: getattr(row, k) for k in order_service.HEADER_FIELDS}, customer_id='OLD-CUSTOMER',
        xiaoman_order_id='OLD-ORDER', internal_received=600, internal_balance=400, status='synced', sync_status='synced')
    db.add(invoice); db.flush()
    from app.invoice.models import InvoiceItem
    src = OrderOpeningManifest.model_validate(raw).orders[0].items[0]
    line = InvoiceItem(invoice_id=invoice.id, xiaoman_unique_id=src.source_item_id, **{k: getattr(src, k) for k in order_service.ITEM_FIELDS})
    material = SemifinishedMaterial(material_code='ORIGINAL-MAT', size='18', color_code='Black', color_key='black')
    db.add_all([line, material]); db.flush()
    db.add(InventoryBalance(material_id=material.id, on_hand_grams=0, reserved_grams=0, version=0)); db.flush()
    allocated = InvoiceAllocation(invoice_id=invoice.id, material_id=material.id, allocated_qty_grams=Decimal('100.125'))
    db.add(allocated); db.flush()
    raw['orders'][0].update(existing_invoice_id=invoice.id, material_allocation_ids=[allocated.id])
    raw['orders'][0]['items'][0]['existing_invoice_item_id'] = line.id
    mapping = order_service.apply_manifest(db, OrderOpeningManifest.model_validate(raw), buyer[1])['orders'][0]
    inventory_service.apply_manifest(db, InventoryOpeningManifest(batch_key='prior-material-closing', source='physical', tenant='warehouse',
        cutover_date=DAY, evidence_sha256='1'*64, review_reference='Synthetic physical closing after prior issues', stocks=[],
        materials=[dict(external_id='prior-material', mode='initialize', material_id=material.id, on_hand_grams='899.875', reserved_grams='0')]), buyer[1])
    source = archive.apply_manifest(db, ImportManifest(batch_key='prior-material-source', source='okki', tenant='tenant-A', cutover_date=DAY,
        evidence_sha256='2'*64, review_reference='Synthetic original issues', catalog=[], archives=[dict(object_type='material', external_id='prior-issue',
        snapshot=dict(source_order_id='OLD-ORDER', existing_allocation_id=allocated.id, material_id=material.id, allocated_qty_grams='100.125'))]), buyer[1])['archives'][0]
    body = MaterialOpeningManifest(batch_key='prior-material-ack', source='okki', tenant='tenant-A', cutover_date=DAY,
        evidence_sha256='3'*64, review_reference='Synthetic original issues reconciled', allocations=[dict(order_binding_record_id=mapping['record_id'],
        existing_allocation_id=allocated.id, source_material_record_id=source['record_id'], material_id=material.id, allocated_qty_grams='100.125')])
    return body, allocated


def test_prior_material_issue_is_acknowledged_with_no_second_deduction(db, buyer):
    body, allocated = inputs(db, buyer)
    equivalent = body.model_copy(update={'allocations': [body.allocations[0].model_copy(update={'allocated_qty_grams': Decimal('100.1250')})]})
    assert service.preview(db, equivalent)['can_apply']
    before = db.scalar(select(func.count()).select_from(InventoryLedger))
    assert service.preview(db, body)['can_apply']
    result = service.apply_manifest(db, body, buyer[1]); db.commit()
    balance = db.scalars(select(InventoryBalance)).one()
    assert balance.on_hand_grams == Decimal('899.875') and allocated.allocated_qty_grams == Decimal('100.125')
    assert db.scalar(select(func.count()).select_from(InventoryLedger)) == before
    assert service.apply_manifest(db, body, buyer[1]) == result
    assert service.apply_manifest(db, body.model_copy(update={'batch_key': 'prior-material-repeat'}), buyer[1])['allocations'] == result['allocations']
    assert balance.on_hand_grams == Decimal('899.875')


def test_unresolved_pending_material_is_not_cleared_or_deducted_by_acknowledgment(db, buyer):
    body, allocated = inputs(db, buyer)
    allocated.pending_delta_grams, allocated.operation_key, allocated.status = Decimal('10'), 'uncertain-old-operation', 'pending'
    assert not service.preview(db, body)['can_apply']
    with pytest.raises(ValueError, match='pending'):
        service.apply_manifest(db, body, buyer[1])
    db.commit()
    assert allocated.status == 'pending' and allocated.pending_delta_grams == 10 and allocated.operation_key == 'uncertain-old-operation'
    assert db.scalars(select(InventoryBalance)).one().on_hand_grams == Decimal('899.875')
