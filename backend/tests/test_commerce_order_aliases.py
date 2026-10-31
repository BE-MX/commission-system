"""Generic historical custom lines retain identity without double counting."""
from copy import deepcopy
from decimal import Decimal
import pytest
from pydantic import ValidationError
from sqlalchemy import select, func
from app.commerce_migration import order_service as service
from app.commerce_migration.order_schemas import OrderOpeningManifest
from app.customer.models import CustomerOrderItem
from app.customer.pcw_order_service import _items_by_order
from app.invoice.models import InvoiceItem
from app.trade.projection_service import project_invoice
from app.stock.local_query_service import _sales
from tests.test_commerce_order_opening import inputs, seed_original_order
from tests.test_invoice_commerce import buyer
from tests.test_inventory_local import stock


def alias_inputs(db, buyer, *, tag='OLD', tenant='tenant-A'):
    raw = inputs(db, buyer, tag=tag, tenant=tenant, catalog_code=tag)
    row = raw['orders'][0]
    item = row['items'][0]
    second = deepcopy(item)
    item.update(source_item_id=f'{tag}-REAL-A', legacy_unique_id=f'{tag}-CUSTOM-GROUP', item_type='custom',
        quantity=4, total_price='400', shipped_quantity=2)
    second.update(source_item_id=f'{tag}-REAL-B', legacy_unique_id=f'{tag}-CUSTOM-GROUP', item_type='custom',
        quantity=6, total_price='600', shipped_quantity=4, color='Brown')
    row['items'] = [item, second]
    invoice, order = seed_original_order(db, raw, buyer[1])
    originals = db.scalars(select(CustomerOrderItem).where(CustomerOrderItem.order_id == order.id).order_by(CustomerOrderItem.id)).all()
    alias = originals[0]
    db.delete(originals[1])
    alias.external_item_id = f'{tag}-CUSTOM-GROUP'
    alias.quantity, alias.unit_price, alias.line_amount = Decimal('1'), Decimal('1000'), Decimal('1000')
    alias.product_name, alias.color = 'Historical generic custom', None
    db.flush()
    original = service.alias_snapshot(alias)
    for item in row['items']:
        item.pop('existing_customer_order_item_id')
    row['customer_item_aliases'] = [dict(existing_customer_order_item_id=alias.id,
        external_item_id=alias.external_item_id, source_record_id=alias.source_record_id,
        item_fingerprint=alias.item_fingerprint, original_snapshot_sha256=service.digest(original),
        source_item_ids=[f'{tag}-REAL-A', f'{tag}-REAL-B'])]
    return raw, invoice, order, alias, original


def verify_alias_projection(db, raw, invoice, order, alias, original, user):
    body = OrderOpeningManifest.model_validate(raw)
    assert service.preview(db, body)['can_apply']
    mapping = service.apply_manifest(db, body, user)['orders'][0]
    db.commit()
    assert alias.projection_role == 'historical_alias' and service.alias_snapshot(alias) == original
    active = _items_by_order(db, [order.id])[order.id]
    assert len(active) == 2 and sum(item.quantity for item in active) == 10
    assert sum(item.line_amount for item in active) == 1000
    assert {item.historical_alias_id for item in active} == {alias.id}
    assert {item.local_invoice_item_id for item in active} == {line.id for line in invoice.items}
    assert {line.xiaoman_unique_id for line in invoice.items} == {alias.external_item_id}
    # Isolate ongoing projection here; full responsibility activation is tested separately.
    invoice.commerce_status = 'partially_shipped'
    for line in invoice.items:
        line.stock_shipped_quantity = 2 if line.quantity == 4 else 4
    invoice.internal_received, invoice.internal_balance = 600, 400
    projected = project_invoice(db, invoice.id)
    db.commit()
    assert projected.id == order.id and projected.amount_usd == 1000
    assert service.alias_snapshot(alias) == original
    assert db.scalar(select(func.count()).select_from(CustomerOrderItem).where(CustomerOrderItem.order_id == order.id)) == 3
    replay = body.model_copy(update={'batch_key': f'{body.batch_key}-alias-replay'})
    assert service.apply_manifest(db, replay, user)['orders'][0] == mapping
    return mapping


def test_alias_group_preserves_original_and_true_lines_without_double_counting(db, stock, buyer, monkeypatch):
    from datetime import date
    raw, invoice, order, alias, original = alias_inputs(db, buyer)
    verify_alias_projection(db, raw, invoice, order, alias, original, buyer[1])
    monkeypatch.setattr('app.stock.local_query_service.beijing_today', lambda: date(2026, 10, 3))
    sales = _sales(30, db)
    assert db.execute(select(sales.c.quantity)).scalar_one() == 10
    assert [item.quantity for item in db.scalars(select(InvoiceItem).order_by(InvoiceItem.id))] == [4, 6]
    # Any later accidental rewrite is detected before altering the complete projection.
    alias.product_name = 'Unexpected rewrite'
    invoice.commerce_version += 1
    db.flush()
    with pytest.raises(ValueError, match='聚合别名原值'):
        project_invoice(db, invoice.id)


def test_long_original_display_uses_explicit_bounded_family_without_truncating_source(db, stock, buyer):
    raw, invoice, order, alias, original = alias_inputs(db, buyer)
    for source, line in zip(raw['orders'][0]['items'], invoice.items, strict=True):
        source['product_display'], source['product_family'] = 'P'*200, 'Reviewed family'
        line.product_display = source['product_display']
    db.flush()
    verify_alias_projection(db, raw, invoice, order, alias, original, buyer[1])
    assert {line.product_display for line in invoice.items} == {'P'*200}
    active = _items_by_order(db, [order.id])[order.id]
    assert {item.product_family for item in active} == {'Reviewed family'}
    from app.trade.snapshot_service import build_snapshot
    assert {item['product_family'] for item in build_snapshot(db, invoice.id)['items']} == {'Reviewed family'}
    changed = deepcopy(raw)
    changed['orders'][0]['items'][0]['product_family'] = 'F'*257
    with pytest.raises(ValidationError):
        OrderOpeningManifest.model_validate(changed)


@pytest.mark.parametrize('change', ['hash', 'source', 'amount', 'duplicate_member', 'missing_member', 'wrong_uid'])
def test_alias_proof_conflicts_cannot_mutate_originals(db, stock, buyer, change):
    raw, invoice, order, alias, original = alias_inputs(db, buyer)
    proof = raw['orders'][0]['customer_item_aliases'][0]
    if change == 'hash':
        proof['original_snapshot_sha256'] = 'd'*64
    elif change == 'source':
        proof['source_record_id'] += 100
    elif change == 'amount':
        alias.line_amount = Decimal('999')
        db.flush()
        proof['original_snapshot_sha256'] = service.digest(service.alias_snapshot(alias))
    elif change == 'duplicate_member':
        proof['source_item_ids'].append('OLD-REAL-A')
    elif change == 'missing_member':
        proof['source_item_ids'].remove('OLD-REAL-B')
    else:
        raw['orders'][0]['items'][1]['legacy_unique_id'] = 'OTHER-GROUP'
    before = service.alias_snapshot(alias)
    try:
        body = OrderOpeningManifest.model_validate(raw)
    except ValidationError:
        pass
    else:
        assert not service.preview(db, body)['can_apply']
        with pytest.raises(ValueError):
            service.apply_manifest(db, body, buyer[1])
    db.commit()
    assert service.alias_snapshot(alias) == before and alias.projection_role == 'active'
    assert invoice.transaction_mode != 'local' and order.local_invoice_id is None
