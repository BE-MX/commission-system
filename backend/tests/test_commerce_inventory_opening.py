"""Opening references cannot reset live balances or replay historical issues."""
from decimal import Decimal
import pytest
from sqlalchemy import func, select
from app.commerce_migration.inventory_schemas import InventoryOpeningManifest
from app.commerce_migration import inventory_service as service
from app.commerce_migration.models import MigrationBatch, MigrationRecord
from app.finance.models import FinanceEvent
from app.inventory.models import StockBalance, StockLedger
from app.inventory.schemas import DocumentCreate
from app.inventory.service import post_document
from app.semifinished.models import SemifinishedMaterial, InventoryBalance, InventoryLedger
from tests.test_commerce_migration import actor
from tests.test_inventory_local import stock


def opening(stock, **updates):
    sku, (wh, _) = stock
    raw = dict(batch_key='opening-1', source='verified-export', tenant='tenant-A', cutover_date='2026-10-03',
        evidence_sha256='b' * 64, review_reference='Synthetic opening reconciliation',
        stocks=[dict(external_id='warehouse-SKU-1', mode='initialize', warehouse_id=wh.id,
            local_sku_id=sku.id, quality='sellable', on_hand=10)], materials=[])
    raw.update(updates)
    return InventoryOpeningManifest.model_validate(raw)


def material(db):
    row = SemifinishedMaterial(material_code='OPEN-M1', size='18', color_code='Black', color_key='black')
    db.add(row); db.flush()
    db.add(InventoryBalance(material_id=row.id)); db.flush()
    return row


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_opening_and_replay_after_new_stock_activity_never_reset_balance(db, stock):
    user = actor(db)
    body = opening(stock)
    assert service.preview(db, body)['can_apply']
    assert count(db, StockBalance) == count(db, MigrationRecord) == 0
    result = service.apply_manifest(db, body, user); db.commit()
    assert db.scalar(select(StockBalance.on_hand)) == 10
    sku, (wh, _) = stock
    post_document(db, DocumentCreate(idempotency_key='later-receipt', kind='receipt', reason='Later real receipt',
        source_type='purchase', source_id='P1', lines=[dict(warehouse_id=wh.id, sku_id=sku.id, quantity=2)]), actor_id=int(user['sub']))
    db.commit()
    assert service.apply_manifest(db, body, user) == result
    result2 = service.apply_manifest(db, body.model_copy(update={'batch_key': 'replay-new-batch'}), user); db.commit()
    assert result2['stocks'] == result['stocks']
    assert db.scalar(select(StockBalance.on_hand)) == 12
    assert count(db, StockLedger) == 2 and count(db, MigrationRecord) == 1 and count(db, FinanceEvent) == 0


@pytest.mark.parametrize('initial_quantity', [0, 10])
def test_target_cannot_be_opened_again_under_another_source_even_when_zero(db, stock, initial_quantity):
    user = actor(db)
    raw = opening(stock).model_dump(mode='json'); raw['stocks'][0]['on_hand'] = initial_quantity
    service.apply_manifest(db, InventoryOpeningManifest.model_validate(raw), user); db.commit()
    raw.update(batch_key='other-source', source='other-export')
    raw['stocks'][0].update(external_id='new-identity', on_hand=20)
    body = InventoryOpeningManifest.model_validate(raw)
    assert not service.preview(db, body)['can_apply']
    with pytest.raises(ValueError, match='冲突'): service.apply_manifest(db, body, user)
    assert db.scalar(select(StockBalance.on_hand)) == initial_quantity
    assert count(db, MigrationBatch) == count(db, StockLedger) == 1


def test_changed_source_content_and_partial_material_failure_rollback_all(db, stock):
    user = actor(db)
    raw = opening(stock).model_dump(mode='json')
    raw['materials'] = [dict(external_id='missing-M', mode='initialize', material_id=99999, on_hand_grams='1.000')]
    body = InventoryOpeningManifest.model_validate(raw)
    with pytest.raises(ValueError, match='冲突'): service.apply_manifest(db, body, user)
    assert count(db, StockLedger) == count(db, StockBalance) == count(db, MigrationRecord) == count(db, MigrationBatch) == 0
    service.apply_manifest(db, opening(stock), user); db.commit()
    raw = opening(stock).model_dump(mode='json'); raw['batch_key'] = 'changed'; raw['stocks'][0]['on_hand'] = 11
    assert not service.preview(db, InventoryOpeningManifest.model_validate(raw))['can_apply']
    with pytest.raises(ValueError): service.apply_manifest(db, InventoryOpeningManifest.model_validate(raw), user)
    assert db.scalar(select(StockBalance.on_hand)) == 10


def test_existing_material_issued_amount_is_acknowledged_without_second_deduction(db, stock):
    user = actor(db); master = material(db)
    balance = db.scalar(select(InventoryBalance))
    balance.on_hand_grams = Decimal('899.875')
    balance.version = 2
    for key, amount, after in [('historical-opening', '1000.000', '1000.000'), ('historical-issue', '-100.125', '899.875')]:
        db.add(InventoryLedger(material_id=master.id, movement_type='inbound' if amount[0] != '-' else 'outbound',
            quantity_grams=Decimal(amount), on_hand_after=Decimal(after), reserved_after=0,
            business_type='verified_history', idempotency_key=key, created_by=int(user['sub'])))
    db.commit()
    body = opening(stock, stocks=[], materials=[dict(external_id='historic-M1', mode='acknowledge_existing',
        material_id=master.id, on_hand_grams='899.875')])
    result = service.apply_manifest(db, body, user); db.commit()
    assert service.apply_manifest(db, body, user) == result
    assert db.scalar(select(InventoryBalance.on_hand_grams)) == Decimal('899.875')
    assert count(db, InventoryLedger) == 2 and count(db, MigrationRecord) == 1
    raw = body.model_dump(mode='json'); raw.update(batch_key='bad-reinitialize', source='another'); raw['materials'][0]['mode'] = 'initialize'
    with pytest.raises(ValueError): service.apply_manifest(db, InventoryOpeningManifest.model_validate(raw), user)
    assert db.scalar(select(InventoryBalance.on_hand_grams)) == Decimal('899.875')


def test_material_initialization_preserves_three_decimal_units_and_rejects_mismatch(db, stock):
    user = actor(db); master = material(db)
    body = opening(stock, stocks=[], materials=[dict(external_id='M1', mode='initialize', material_id=master.id, on_hand_grams='100.125')])
    service.apply_manifest(db, body, user); db.commit()
    assert db.scalar(select(InventoryBalance.on_hand_grams)) == Decimal('100.125')
    assert db.scalar(select(InventoryLedger.quantity_grams)) == Decimal('100.125')
    raw = body.model_dump(mode='json'); raw.update(batch_key='wrong', source='other'); raw['materials'][0].update(mode='acknowledge_existing', on_hand_grams='101.125')
    with pytest.raises(ValueError): service.apply_manifest(db, InventoryOpeningManifest.model_validate(raw), user)


@pytest.mark.parametrize('change', ['duplicate_bucket', 'reserved_initialize', 'non_piece', 'fractional_piece', 'four_decimal_grams'])
def test_invalid_opening_units_and_unsupported_responsibilities_are_rejected(stock, change):
    raw = opening(stock).model_dump(mode='json')
    if change == 'duplicate_bucket': raw['stocks'].append({**raw['stocks'][0], 'external_id': 'other-source'})
    elif change == 'reserved_initialize': raw['stocks'][0]['reserved'] = 1
    elif change == 'non_piece': raw['stocks'][0]['quality'] = 'unknown'
    elif change == 'fractional_piece': raw['stocks'][0]['on_hand'] = 1.5
    elif change == 'four_decimal_grams': raw['materials'] = [dict(external_id='M1', mode='initialize', material_id=1, on_hand_grams='1.0001')]
    with pytest.raises(ValueError): InventoryOpeningManifest.model_validate(raw)


def test_existing_stock_acknowledges_correct_ledger_without_new_movement(db, stock):
    user = actor(db)
    sku, (wh, _) = stock
    post_document(db, DocumentCreate(idempotency_key='historical-stock', kind='opening', reason='Verified historical balance',
        lines=[dict(warehouse_id=wh.id, sku_id=sku.id, quantity=8)]), actor_id=int(user['sub']))
    db.commit()
    raw = opening(stock).model_dump(mode='json'); raw['stocks'][0].update(mode='acknowledge_existing', on_hand=8)
    result = service.apply_manifest(db, InventoryOpeningManifest.model_validate(raw), user); db.commit()
    assert result['stocks'][0]['mode'] == 'acknowledge_existing'
    assert db.scalar(select(StockBalance.on_hand)) == 8 and count(db, StockLedger) == 1


def test_http_inventory_opening_permission_preview_and_changed_batch_conflict(db, stock):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.commerce_migration.router import router
    user = actor(db); user.update(roles=[], permissions=['inventory:admin', 'semifinished:write'])
    app = FastAPI(); app.include_router(router, prefix='/api/commerce-migration')
    from tests.authority_helpers import seed_authority
    seed_authority(db, int(user['sub']), *user.get('permissions', []), roles=user.get('roles', []))
    def request_session():
        # TestClient requests own a fresh transaction, like production get_db.
        db.rollback()
        try:
            yield db
        finally:
            db.rollback()
    app.dependency_overrides[get_db] = request_session
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        raw = opening(stock).model_dump(mode='json')
        assert client.post('/api/commerce-migration/inventory/batches', json=raw).status_code == 403
        user['permissions'].append('commerce_migration:admin')
        seed_authority(db, int(user['sub']), 'commerce_migration:admin')
        response = client.post('/api/commerce-migration/inventory/preview', json=raw)
        assert response.status_code == 200 and response.json()['data']['can_apply']
        assert count(db, StockLedger) == 0
        response = client.post('/api/commerce-migration/inventory/batches', json=raw)
        assert response.status_code == 200, response.text
        result = response.json()['data']
        assert client.post('/api/commerce-migration/inventory/batches', json=raw).json()['data'] == result
        assert client.post('/api/commerce-migration/inventory/batches', json={**raw, 'review_reference': 'Changed'}).status_code == 409
        assert count(db, StockLedger) == count(db, MigrationRecord) == 1


def test_late_posting_failure_rolls_back_first_stock_movement_even_if_caller_commits(db, stock, monkeypatch):
    from app.inventory import service as stock_service
    user = actor(db)
    sku, (_, other) = stock
    raw = opening(stock).model_dump(mode='json')
    raw['stocks'].append({**raw['stocks'][0], 'external_id': 'second-bucket', 'warehouse_id': other.id})
    original = stock_service._move
    calls = []
    def fail_after_second_move(*args, **kwargs):
        original(*args, **kwargs)
        calls.append(args[1].id)
        if len(calls) == 2:
            raise ValueError('Synthetic failure after two posted movements')
    monkeypatch.setattr(stock_service, '_move', fail_after_second_move)
    with pytest.raises(ValueError, match='Synthetic failure'):
        service.apply_manifest(db, InventoryOpeningManifest.model_validate(raw), user)
    db.commit()  # A caught exception must not leave a first movement to commit.
    assert len(calls) == 2
    assert count(db, StockBalance) == count(db, StockLedger) == count(db, MigrationRecord) == count(db, MigrationBatch) == 0


def test_invalid_semifinished_claims_leave_no_rows_when_caller_commits(db, stock):
    from app.semifinished import order_service, inventory_service
    from app.semifinished.models import SemifinishedOrderItem
    user = actor(db); master = material(db)
    order = order_service.create_order(db, items=[dict(material_id=master.id, quantity_grams=Decimal('10'))], user_id=int(user['sub']))
    item_id = order.items[0].id
    with pytest.raises(ValueError, match='剩余数量'):
        order_service.receive_item(db, item_id=item_id, quantity_grams=Decimal('11'),
            idempotency_key='invalid-over-receipt', operator_id=int(user['sub']), remark=None)
    db.commit()
    with pytest.raises(ValueError, match='实存'):
        inventory_service.adjust_inventory(db, material_id=master.id, quantity_grams=Decimal('-1'),
            idempotency_key='invalid-negative', operator_id=int(user['sub']), remark='Synthetic invalid adjustment')
    db.commit()
    assert count(db, InventoryLedger) == 0
    balance = db.scalar(select(InventoryBalance))
    assert balance.on_hand_grams == balance.reserved_grams == balance.version == 0
    assert db.get(SemifinishedOrderItem, item_id).received_qty_grams == 0
