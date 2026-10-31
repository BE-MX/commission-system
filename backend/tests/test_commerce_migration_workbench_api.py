"""Administrator review infers current versions without granting ordinary writers."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.commerce_migration.router import router
from app.commerce_migration.models import MigrationRecord
from app.inventory.models import StockLedger
from tests.test_commerce_order_activation import prepared
from tests.test_finance_local import finance
from tests.test_invoice_commerce import buyer
from tests.test_inventory_local import stock
from tests.authority_helpers import seed_authority


def client_for(db, user):
    app = FastAPI()
    app.include_router(router, prefix='/api/commerce-migration')
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
    return TestClient(app)


def test_workbench_permissions_preview_pagination_and_real_activation(db, stock, finance):
    _, invoice, _, mapping, user = prepared(db, stock, finance)
    user['roles'], user['permissions'] = [], ['receipt:admin', 'invoice:write', 'production:write']
    selected = dict(request_key='api-reviewed-activation', record_ids=[mapping['record_id']])
    before = db.scalar(select(func.count()).select_from(StockLedger))
    with client_for(db, user) as client:
        for path in ['records/page', f'records/{mapping["record_id"]}']:
            assert client.get('/api/commerce-migration/' + path).status_code == 403
        for path in ['orders/preview', 'orders/batches', 'fulfillment/preview', 'fulfillment/batches',
                     'production/preview', 'production/batches', 'materials/preview', 'materials/batches',
                     'materials/pending/preview', 'materials/pending/batches',
                     'activation/prepare', 'activation/preview', 'activation']:
            assert client.post('/api/commerce-migration/' + path, json={}).status_code == 403
        user['permissions'].append('commerce_migration:admin')
        seed_authority(db, int(user['sub']), 'commerce_migration:admin')
        page = client.get('/api/commerce-migration/records/page?page=1&page_size=2').json()['data']
        assert page['total'] == db.scalar(select(func.count()).select_from(MigrationRecord))
        assert len(page['items']) == 2 and all('snapshot' not in row for row in page['items'])
        second = client.get('/api/commerce-migration/records/page?page=2&page_size=2').json()['data']
        assert not set(row['id'] for row in page['items']) & set(row['id'] for row in second['items'])
        detail = client.get(f'/api/commerce-migration/records/{mapping["record_id"]}').json()['data']
        assert detail['record']['snapshot']['total_amount'] == '1000'
        assert detail['batch']['review_reference']
        response = client.post('/api/commerce-migration/activation/prepare', json=selected)
        assert response.status_code == 200, response.text
        review = response.json()['data']
        assert review['report']['can_activate']
        assert review['command']['orders'][0]['expected_version'] == invoice.commerce_version
        assert review['descriptions'][0]['target_id'] == invoice.id
        assert invoice.commerce_status == 'opening' and invoice.items[0].stock_reserved_quantity == 0
        assert db.scalar(select(func.count()).select_from(StockLedger)) == before
        applied = client.post('/api/commerce-migration/activation', json=review['command'])
        assert applied.status_code == 200, applied.text
        first = applied.json()['data']
        assert client.post('/api/commerce-migration/activation', json=review['command']).json()['data'] == first
        assert invoice.commerce_status == 'partially_shipped' and invoice.items[0].stock_reserved_quantity == 4
        assert db.scalar(select(func.count()).select_from(StockLedger)) == before + 1
        assert client.post('/api/commerce-migration/activation/prepare', json=selected).status_code == 409


def test_workbench_refuses_nonresponsibility_records_and_duplicates_without_writing(db, stock, finance):
    _, invoice, _, _, user = prepared(db, stock, finance)
    record = db.scalar(select(MigrationRecord).where(MigrationRecord.object_type == 'stock_balance'))
    before = db.scalar(select(func.count()).select_from(StockLedger))
    with client_for(db, user) as client:
        response = client.post('/api/commerce-migration/activation/prepare',
            json=dict(request_key='wrong-responsibility', record_ids=[record.id]))
        assert response.status_code == 409 and '完整订单或生产' in response.json()['detail']
        assert client.post('/api/commerce-migration/activation/prepare',
            json=dict(request_key='duplicate-responsibility', record_ids=[record.id, record.id])).status_code == 422
        assert client.get('/api/commerce-migration/records/999999').status_code == 404
    db.commit()
    assert invoice.commerce_status == 'opening' and db.scalar(select(func.count()).select_from(StockLedger)) == before
