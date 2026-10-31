"""Migration records are evidence, not replays of historical stock or money."""
from copy import deepcopy
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select

from app.auth.models import ArkUser
from app.catalog.models import CatalogExternalIdentity, CatalogProduct, CatalogSku
from app.commerce_migration.models import MigrationBatch, MigrationRecord
from app.commerce_migration.schemas import ImportManifest
from app.commerce_migration.service import apply_manifest, preview
from app.finance.models import FinanceEvent
from app.inventory.models import StockLedger
from app.invoice.models import InvoiceCommerceEvent


def manifest(**updates):
    body = dict(batch_key='verified-import-1', source='okki', tenant='tenant-A',
        cutover_date='2026-10-03', evidence_sha256='a' * 64,
        review_reference='Synthetic reviewed export 1',
        catalog=[dict(external_product_id='remote-P1', external_sku_id='remote-S1',
            product=dict(code='M-P1', name='Full historical product', display_name='Hair', kind='hair', model='M1'),
            sku=dict(code='M-S1', color='Black', size='18', weight_grams='20.125'))],
        archives=[dict(object_type='order', external_id='remote-order-1',
            snapshot=dict(contract_amount='1000.00', paid_amount='600.00', ordered_quantity=10, shipped_quantity=6))])
    body.update(updates)
    return ImportManifest.model_validate(body)


def actor(db):
    user = ArkUser(username='migration-admin', password_hash='synthetic-only', real_name='Synthetic Migration Admin')
    db.add(user); db.flush()
    return {'sub': str(user.id), 'roles': ['super_admin'], 'permissions': []}


def counts(db):
    return [db.scalar(select(func.count()).select_from(model)) for model in
            (MigrationBatch, MigrationRecord, CatalogProduct, CatalogSku, StockLedger, FinanceEvent, InvoiceCommerceEvent)]


def test_preview_is_read_only_and_apply_replay_has_no_economic_effect(db):
    user = actor(db)
    body = manifest()
    before = counts(db)
    report = preview(db, body)
    assert report['can_apply'] and report['catalog_count'] == report['archive_count'] == 1
    assert report['conflicts'] == [] and counts(db) == before
    result = apply_manifest(db, body, user)
    db.commit()
    assert result['catalog'][0]['sku_id'] == db.scalar(select(CatalogSku.id))
    assert counts(db) == [1, 2, 1, 1, 0, 0, 0]
    assert apply_manifest(db, body, user) == result
    db.commit()
    assert counts(db) == [1, 2, 1, 1, 0, 0, 0]
    record = db.scalar(select(MigrationRecord).where(MigrationRecord.object_type == 'order'))
    assert record.role == 'archive' and record.snapshot['paid_amount'] == '600.00'
    assert record.snapshot['shipped_quantity'] == 6
    assert db.get(MigrationBatch, body.batch_key).cutover_date == date(2026, 10, 3)


def test_content_change_and_code_collision_are_explicit_conflicts(db):
    user = actor(db)
    original = manifest()
    apply_manifest(db, original, user); db.commit()
    changed = original.model_dump(mode='json')
    changed['archives'][0]['snapshot']['paid_amount'] = '601.00'
    assert not preview(db, ImportManifest.model_validate(changed))['can_apply']
    with pytest.raises(ValueError, match='批次'):
        apply_manifest(db, ImportManifest.model_validate(changed), user)
    changed['batch_key'] = 'new-batch'
    report = preview(db, ImportManifest.model_validate(changed))
    assert not report['can_apply'] and report['conflicts'][0]['code'] == 'source_content_changed'
    with pytest.raises(ValueError, match='冲突'):
        apply_manifest(db, ImportManifest.model_validate(changed), user)
    assert counts(db) == [1, 2, 1, 1, 0, 0, 0]


def test_mapping_scopes_tenant_and_preserves_native_ids(db):
    user = actor(db)
    original = manifest()
    first = apply_manifest(db, original, user); db.commit()
    second = apply_manifest(db, manifest(batch_key='second-batch', tenant='tenant-B'), user); db.commit()
    assert first['catalog'][0]['sku_id'] == second['catalog'][0]['sku_id']
    assert db.scalar(select(func.count()).select_from(CatalogExternalIdentity)) == 2
    assert counts(db) == [2, 4, 1, 1, 0, 0, 0]
    changed = manifest(batch_key='third-batch').model_dump(mode='json')
    changed['catalog'][0]['sku']['code'] = 'OTHER-SKU'
    assert preview(db, ImportManifest.model_validate(changed))['conflicts'][0]['code'] == 'source_content_changed'


def test_existing_master_conflicts_do_not_overwrite_or_partially_import(db):
    user = actor(db)
    db.add(CatalogProduct(code='M-P1', name='Current native name', display_name='Hair', kind='hair', model='M1'))
    db.commit()
    body = manifest()
    report = preview(db, body)
    assert not report['can_apply'] and report['conflicts'][0]['code'] == 'product_conflict'
    with pytest.raises(ValueError, match='冲突'):
        apply_manifest(db, body, user)
    assert counts(db) == [0, 0, 1, 0, 0, 0, 0]
    assert db.scalar(select(CatalogProduct.name)) == 'Current native name'


def test_same_source_second_batch_reuses_immutable_evidence_after_live_rename(db):
    user = actor(db)
    body = manifest()
    result = apply_manifest(db, body, user); db.commit()
    db.scalar(select(CatalogProduct)).name = 'Renamed after import'
    db.commit()
    duplicate = manifest(batch_key='different-batch-key')
    assert preview(db, duplicate)['can_apply']
    next_result = apply_manifest(db, duplicate, user); db.commit()
    assert next_result['catalog'][0]['sku_id'] == result['catalog'][0]['sku_id']
    assert counts(db) == [2, 2, 1, 1, 0, 0, 0]
    assert db.scalar(select(CatalogProduct.name)) == 'Renamed after import'


def test_conflict_late_in_manifest_rolls_back_earlier_master_work(db):
    user = actor(db)
    body = manifest().model_dump(mode='json')
    another = deepcopy(body['catalog'][0])
    another.update(external_product_id='remote-P2', external_sku_id='remote-S2')
    another['sku']['code'] = 'M-S2'
    another['product']['name'] = 'Conflicting product snapshot'
    body['catalog'].append(another)
    report = preview(db, ImportManifest.model_validate(body))
    assert not report['can_apply'] and report['conflicts'][0]['code'] == 'manifest_product_conflict'
    with pytest.raises(ValueError):
        apply_manifest(db, ImportManifest.model_validate(body), user)
    assert counts(db) == [0, 0, 0, 0, 0, 0, 0]


@pytest.mark.parametrize('change', ['duplicate_archive', 'duplicate_alias', 'opening_not_archive', 'missing_proof', 'too_large_snapshot'])
def test_manifest_rejects_unverified_or_ambiguous_input(change):
    body = manifest().model_dump(mode='json')
    if change == 'duplicate_archive': body['archives'].append(deepcopy(body['archives'][0]))
    elif change == 'duplicate_alias': body['catalog'].append(deepcopy(body['catalog'][0]))
    elif change == 'opening_not_archive': body['archives'][0]['object_type'] = 'opening'
    elif change == 'missing_proof': body['evidence_sha256'] = ''
    elif change == 'too_large_snapshot': body['archives'][0]['snapshot'] = {'oversized': 'a' * 262145}
    with pytest.raises(ValueError): ImportManifest.model_validate(body)


def test_existing_external_alias_cannot_be_reassigned(db):
    user = actor(db)
    product = CatalogProduct(code='OTHER-P', name='Other', display_name='Other')
    db.add(product); db.flush()
    sku = CatalogSku(code='OTHER-S', product_id=product.id, color='', size='')
    db.add(sku); db.flush()
    db.add(CatalogExternalIdentity(source='okki', tenant='tenant-A', external_product_id='remote-P1', external_sku_id='remote-S1', sku_id=sku.id))
    db.commit()
    report = preview(db, manifest())
    assert not report['can_apply'] and any(row['code'] == 'alias_conflict' for row in report['conflicts'])
    with pytest.raises(ValueError): apply_manifest(db, manifest(), user)
    assert db.scalar(select(CatalogExternalIdentity.sku_id)) == sku.id


def test_http_preview_apply_archive_reads_and_admin_permission(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.commerce_migration.router import router
    user = actor(db)
    user['roles'] = []
    user['permissions'] = ['catalog:write', 'inventory:admin', 'receipt:admin']
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
        body = manifest().model_dump(mode='json')
        assert client.post('/api/commerce-migration/preview', json=body).status_code == 403
        assert client.post('/api/commerce-migration/batches', json=body).status_code == 403
        assert client.get('/api/commerce-migration/records').status_code == 403
        user['permissions'].append('commerce_migration:admin')
        seed_authority(db, int(user['sub']), 'commerce_migration:admin')
        response = client.post('/api/commerce-migration/preview', json=body)
        assert response.status_code == 200 and response.json()['data']['can_apply']
        assert counts(db) == [0, 0, 0, 0, 0, 0, 0]
        response = client.post('/api/commerce-migration/batches', json=body)
        assert response.status_code == 200, response.text
        first = response.json()['data']
        assert client.post('/api/commerce-migration/batches', json=body).json()['data'] == first
        details = client.get('/api/commerce-migration/batches/verified-import-1').json()['data']
        assert details['review_reference'] == body['review_reference']
        records = client.get('/api/commerce-migration/records?source=okki&tenant=tenant-A&object_type=order').json()['data']
        assert len(records) == 1 and records[0]['role'] == 'archive'
        assert client.get(f'/api/commerce-migration/records?after_id={records[0]["id"]}').json()['data'] == []
        assert client.get('/api/commerce-migration/batches/missing').status_code == 404
        assert client.post('/api/commerce-migration/batches', json={**body, 'review_reference': 'Changed evidence'}).status_code == 409
        assert counts(db) == [1, 2, 1, 1, 0, 0, 0]


@pytest.mark.parametrize(('utc_hour', 'utc_minute', 'expected_date'), [(15, 59, date(2026, 10, 3)), (16, 0, date(2026, 10, 4))])
def test_import_audit_time_uses_beijing_across_midnight_on_non_beijing_server(db, monkeypatch, utc_hour, utc_minute, expected_date):
    from zoneinfo import ZoneInfo
    from app.core import time as clock
    instant = datetime(2026, 10, 3, utc_hour, utc_minute, tzinfo=timezone.utc)
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            # Simulate a US server: naive server time must never be used here.
            return instant.astimezone(tz) if tz else instant.astimezone(ZoneInfo('America/Los_Angeles')).replace(tzinfo=None)
    monkeypatch.setenv('TZ', 'America/Los_Angeles')
    monkeypatch.setattr(clock, 'datetime', FixedDatetime)
    body = manifest()
    apply_manifest(db, body, actor(db)); db.commit()
    batch = db.get(MigrationBatch, body.batch_key)
    record = db.scalar(select(MigrationRecord))
    assert batch.created_at.date() == record.created_at.date() == expected_date
    assert batch.created_at == record.created_at == instant.astimezone(clock.BEIJING_TIMEZONE).replace(tzinfo=None)
    assert batch.cutover_date == date(2026, 10, 3)  # Preserve supplied historical business date.



def test_case_sensitive_archive_and_tenant_identities_remain_distinct(db):
    user = actor(db)
    body = manifest(catalog=[], archives=[
        dict(object_type='order', external_id='Order-A', snapshot={'paid': 1}),
        dict(object_type='order', external_id='order-a', snapshot={'paid': 2})])
    assert preview(db, body)['can_apply']
    result = apply_manifest(db, body, user); db.commit()
    assert len({row['record_id'] for row in result['archives']}) == 2
    apply_manifest(db, manifest(batch_key='tenant-case', tenant='tenant-a', catalog=[],
        archives=body.model_dump(mode='json')['archives']), user); db.commit()
    assert counts(db) == [2, 4, 0, 0, 0, 0, 0]


def case_sku_manifest():
    raw = manifest().model_dump(mode='json')
    other = deepcopy(raw['catalog'][0])
    other['external_sku_id'] = 'remote-S2'
    other['sku'].update(code='m-s1', size='20')
    raw['catalog'].append(other)
    return ImportManifest.model_validate(raw)


def test_catalog_codes_use_database_case_equality_before_any_write(db):
    body = case_sku_manifest()
    user = actor(db)
    report = preview(db, body)
    assert not report['can_apply']
    assert any(row['code'] == 'manifest_sku_conflict' for row in report['conflicts'])
    with pytest.raises(ValueError): apply_manifest(db, body, user)
    assert counts(db) == [0, 0, 0, 0, 0, 0, 0]


@pytest.mark.parametrize('include_existing', [False, True])
def test_external_product_cannot_split_across_batches_or_skip_existing_record(db, include_existing):
    user = actor(db)
    first = manifest()
    apply_manifest(db, first, user); db.commit()
    raw = first.model_dump(mode='json')
    other = deepcopy(raw['catalog'][0])
    other['external_sku_id'] = 'remote-S2'
    other['product']['code'] = 'M-P2'
    other['sku']['code'] = 'M-S2'
    raw.update(batch_key='split-product', archives=[], catalog=([raw['catalog'][0], other] if include_existing else [other]))
    body = ImportManifest.model_validate(raw)
    assert any(row['code'] == 'external_product_conflict' for row in preview(db, body)['conflicts'])
    with pytest.raises(ValueError): apply_manifest(db, body, user)
    assert counts(db) == [1, 2, 1, 1, 0, 0, 0]


def test_write_phase_revalidates_reused_catalog_even_after_preview(db, monkeypatch):
    from app.commerce_migration import service
    user = actor(db)
    raw = manifest().model_dump(mode='json')
    other = deepcopy(raw['catalog'][0])
    other['external_sku_id'] = 'remote-S2'
    other['sku']['size'] = '20'
    raw['catalog'].append(other)
    monkeypatch.setattr(service, 'preview', lambda *a, **k: {'can_apply': True})
    with pytest.raises(ValueError, match='SKU'):
        apply_manifest(db, ImportManifest.model_validate(raw), user)
    assert counts(db) == [0, 0, 0, 0, 0, 0, 0]


def test_archive_preserves_whitespace_distinct_json_keys_and_values(db):
    snapshot = {' amount': ' 100.00 ', 'amount ': '200.00',
        'nested': {' key': [' value ', {'key ': ' fact '}]}}
    body = manifest(catalog=[], archives=[dict(object_type='order', external_id=' Order-A ', snapshot=snapshot)])
    assert body.archives[0].external_id == 'Order-A'
    assert body.archives[0].snapshot == snapshot
    apply_manifest(db, body, actor(db)); db.commit()
    assert db.scalar(select(MigrationRecord.snapshot)) == snapshot
