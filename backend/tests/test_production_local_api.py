"""Native workbench reads follow the same sales scope as supply commands."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.invoice.commerce_service import create_draft, confirm
from app.production.local_router import router
from app.catalog.router import router as catalog_router
from app.production import local_service as service
from app.production.local_schemas import ReceiptCreate
from tests.test_invoice_commerce import buyer, draft, action
from tests.test_inventory_local import stock
from tests.test_production_local import create, quantity


def test_workbench_reads_scope_receipts_and_permissions(db, stock, buyer):
    from tests.authority_helpers import seed_authority
    from app.customer.models import CustomerAssignment
    from app.core.time import beijing_now
    customer, admin = buyer
    sku, (warehouse, _) = stock
    order, item = create(db, stock, buyer)
    invoices = []
    for index, owner in enumerate([int(admin['sub']), int(admin['sub']) + 999]):
        invoice = create_draft(db, draft(customer, admin, sku, request_key=f'workbench-sale-{index}',
            order_type='production', items=[dict(local_sku_id=sku.id, quantity=3, price_per_piece=10)]), admin)
        confirm(db, invoice.id, action(f'workbench-confirm-{index}', 1), admin)
        invoice.sales_user_id = owner
        invoices.append(invoice)
    service.complete(db, item.id, quantity('workbench-complete', 1, 2), admin)
    service.receive(db, item.id, ReceiptCreate(request_key='workbench-receive', expected_version=2,
        quantity=1, warehouse_id=warehouse.id, reason='QC accepted'), admin)
    db.add(CustomerAssignment(customer_id=customer.id, user_id=int(admin['sub']), assignment_role='primary',
        assignment_status='active', assignment_source='admin_assign', effective_from=beijing_now()))
    seed_authority(db, int(admin['sub']), 'production:read', 'production:write')
    current = {'sub': admin['sub'], 'roles': [], 'permissions': ['production:read', 'production:write']}
    app = FastAPI()
    app.include_router(router, prefix='/api/production/local')
    app.include_router(catalog_router, prefix='/api/catalog')
    app.dependency_overrides[get_current_user] = lambda: current
    def fresh_db():
        db.rollback()
        try:
            yield db
        finally:
            db.rollback()
    app.dependency_overrides[get_db] = fresh_db
    client = TestClient(app)
    assert client.get('/api/catalog/products').status_code == 200
    root = '/api/production/local'
    listing = client.get(root + '/orders', params={'keyword': 'P-01', 'page_size': 1}).json()['data']
    assert listing['total'] == 1 and listing['items'][0]['id'] == order.id
    assert client.get(root + '/orders', params={'status': 1}).json()['data']['total'] == 0
    options = client.get(root + '/supply-options', params={'item_id': item.id}).json()['data']
    assert [line['invoice_item_id'] for line in options['items']] == [invoices[0].items[0].id]
    assert options['items'][0]['remaining_quantity'] == 3
    current['permissions'].append('invoice:read_all')
    seed_authority(db, int(admin['sub']), 'invoice:read_all')
    assert client.get(root + '/supply-options', params={'item_id': item.id}).json()['data']['total'] == 2
    detail = client.get(root + f'/orders/{order.id}').json()['data']
    receipt = detail['receipts'][0]
    assert receipt['warehouse_name'] == warehouse.name and receipt['quantity'] == 1
    assert receipt['item_id'] == item.id and receipt['reversed'] is False
    assert 'request_key' not in receipt
    assert client.get(root + '/reference-data').json()['data']['warehouses'][0]['id'] == warehouse.id
    assert client.get(root + '/material-options').status_code == 403
    current['permissions'] = ['production:read']
    assert client.get('/api/catalog/products').status_code == 403
    assert client.get(root + '/supply-options', params={'item_id': item.id}).status_code == 403


def test_supply_candidates_stop_disclosing_order_after_current_customer_handover(db, stock, buyer):
    from app.auth.models import ArkUser
    from app.customer.models import CustomerAssignment
    from app.core.time import beijing_now
    from app.invoice.models import Invoice
    from tests.authority_helpers import seed_authority
    customer, admin = buyer
    sku, _ = stock
    order, item = create(db, stock, buyer)
    invoice = create_draft(db, draft(customer, admin, sku, request_key='scoped-sale', order_type='production',
        items=[dict(local_sku_id=sku.id, quantity=3, price_per_piece=10)]), admin)
    confirm(db, invoice.id, action('confirm-scoped-sale', 1), admin)
    successor = ArkUser(username='production-customer-successor', password_hash='synthetic', real_name='Successor')
    db.add(successor); db.flush()
    assignment = CustomerAssignment(customer_id=customer.id, user_id=int(admin['sub']), assignment_role='primary',
        assignment_status='active', assignment_source='admin_assign', effective_from=beijing_now())
    db.add(assignment)
    seed_authority(db, int(admin['sub']), 'production:read', 'production:write')
    current = {'sub': admin['sub'], 'roles': [], 'permissions': ['production:read', 'production:write']}
    app = FastAPI(); app.include_router(router, prefix='/api/production/local')
    app.dependency_overrides[get_current_user] = lambda: current
    app.dependency_overrides[get_db] = lambda: (db.rollback(), db)[1]
    with TestClient(app) as client:
        endpoint = '/api/production/local/supply-options'
        response = client.get(endpoint, params={'item_id': item.id, 'page_size': 1})
        assert response.status_code == 200, response.text
        assert response.json()['data']['total'] == 1
        original_salesperson = invoice.sales_user_id
        assignment.user_id = successor.id
        db.commit()
        response = client.get(endpoint, params={'item_id': item.id, 'page_size': 1})
        assert response.status_code == 200, response.text
        assert response.json()['data']['total'] == 0 and response.json()['data']['items'] == []
    assert db.scalar(select(Invoice.sales_user_id).where(Invoice.id == invoice.id)) == original_salesperson
