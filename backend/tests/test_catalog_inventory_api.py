"""Permissions and public contracts of the local master-data/stock entry path."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser
from app.catalog.router import router as catalog_router
from app.core.database import get_db
from app.inventory.router import router as inventory_router


@pytest.mark.parametrize('operation', ['create_product', 'update_product', 'create_sku', 'sku_status', 'update_sku'])
def test_revoked_catalog_writer_cannot_mutate_master_data_with_stale_token(db, operation):
    from app.catalog.models import CatalogProduct, CatalogSku
    from tests.authority_helpers import seed_authority
    actor = ArkUser(username='catalog-revoked', password_hash='synthetic', real_name='Catalog reader')
    db.add(actor)
    product = CatalogProduct(code='ORIGINAL', name='Original product', display_name='Original product')
    db.add(product); db.flush()
    sku = CatalogSku(product_id=product.id, code='ORIGINAL-SKU', color='black')
    db.add(sku); db.flush()
    actor_id, product_id, sku_id = actor.id, product.id, sku.id
    seed_authority(db, actor_id, 'catalog:read')
    app = FastAPI()
    app.include_router(catalog_router, prefix='/api/catalog')
    app.dependency_overrides[get_current_user] = lambda: {'sub': str(actor_id), 'roles': [],
        'permissions': ['catalog:write', 'catalog:read']}
    def fresh_db():
        db.rollback()
        yield db
        db.rollback()
    app.dependency_overrides[get_db] = fresh_db
    commands = {
        'create_product': ('POST', '/products', {'code': 'FORBIDDEN', 'name': 'Changed', 'display_name': 'Changed'}),
        'update_product': ('PUT', f'/products/{product_id}', {'name': 'Changed', 'display_name': 'Changed', 'active': True}),
        'create_sku': ('POST', f'/products/{product_id}/skus', {'code': 'FORBIDDEN-SKU', 'color': 'brown'}),
        'sku_status': ('PUT', f'/skus/{sku_id}/status', {'active': False}),
        'update_sku': ('PUT', f'/skus/{sku_id}', {'code': 'ORIGINAL-SKU', 'color': 'brown'}),
    }
    method, path, body = commands[operation]
    with TestClient(app) as client:
        response = client.request(method, '/api/catalog' + path, json=body)
        assert response.status_code == 403, response.text
        assert client.get('/api/catalog/products').status_code == 200
    assert db.query(CatalogProduct).count() == db.query(CatalogSku).count() == 1
    assert db.get(CatalogProduct, product_id).name == 'Original product'
    assert db.get(CatalogSku, sku_id).color == 'black' and db.get(CatalogSku, sku_id).active


def test_revoked_catalog_reader_cannot_use_stale_read_grant(db):
    from tests.authority_helpers import seed_authority
    actor = ArkUser(username='catalog-no-read', password_hash='synthetic', real_name='Catalog actor')
    db.add(actor); db.flush()
    actor_id = actor.id
    seed_authority(db, actor_id, 'catalog:write')
    app = FastAPI()
    app.include_router(catalog_router, prefix='/api/catalog')
    app.dependency_overrides[get_current_user] = lambda: {'sub': str(actor_id), 'roles': [],
        'permissions': ['catalog:read']}
    app.dependency_overrides[get_db] = lambda: (db.rollback(), db)[1]
    with TestClient(app) as client:
        assert client.get('/api/catalog/products').status_code == 403


def test_catalog_to_stock_http_flow_and_permission_boundaries(db):
    from tests.authority_helpers import seed_authority
    from tests.test_commerce_transition_authority import install
    install(db, phase='local_only')
    user = ArkUser(username="warehouse", password_hash="test-only", real_name="Warehouse")
    db.add(user)
    db.flush()
    current = {"sub": str(user.id), "roles": [], "permissions": []}
    app = FastAPI()
    app.include_router(catalog_router, prefix="/api/catalog")
    app.include_router(inventory_router, prefix="/api/inventory")
    app.dependency_overrides[get_current_user] = lambda: current
    db.commit()
    def fresh_db():
        db.rollback()
        try:
            yield db
        finally:
            db.rollback()
    app.dependency_overrides[get_db] = fresh_db
    client = TestClient(app)
    product = {"code": "P1", "name": "Hair", "display_name": "Hair"}
    assert client.post("/api/catalog/products", json=product).status_code == 403
    current["permissions"] = ["catalog:write", "catalog:read", "inventory:read", "inventory:write", "inventory:admin"]
    def grant_current():
        from app.auth.models import ArkRolePermission, ArkUserRole
        role_ids = [r.role_id for r in db.query(ArkUserRole).filter_by(user_id=user.id)]
        db.query(ArkRolePermission).filter(ArkRolePermission.role_id.in_(role_ids)).delete(synchronize_session=False)
        db.commit()
        seed_authority(db, user.id, *current['permissions'])
    grant_current()
    created = client.post("/api/catalog/products", json=product)
    assert created.status_code == 200, created.text
    product_id = created.json()["data"]["id"]
    created_sku = client.post(f"/api/catalog/products/{product_id}/skus", json={"code": "S1", "color": "black"})
    assert created_sku.status_code == 200, created_sku.text
    sku_id = created_sku.json()["data"]["id"]
    changed_sku = {"code": "S1", "color": "brown", "weight_grams": "20"}
    assert client.put(f"/api/catalog/skus/{sku_id}", json=changed_sku).status_code == 200
    assert client.put(f"/api/catalog/skus/{sku_id}", json={**changed_sku, "code": "S2"}).status_code == 409
    created_wh = client.post("/api/inventory/warehouses", json={"code": "W1", "name": "Main"})
    assert created_wh.status_code == 200, created_wh.text
    warehouse_id = created_wh.json()["data"]["id"]
    command = {"idempotency_key": "receipt-1", "kind": "receipt", "reason": "delivered",
               "lines": [{"warehouse_id": warehouse_id, "sku_id": sku_id, "quantity": 10}]}
    current["permissions"].remove("inventory:admin")
    grant_current()
    command["kind"] = "opening"
    assert client.post("/api/inventory/documents", json=command).status_code == 403
    command["kind"] = "receipt"
    posted = client.post("/api/inventory/documents", json=command)
    assert posted.status_code == 200, posted.text
    assert client.post("/api/inventory/documents", json=command).json()["data"]["id"] == posted.json()["data"]["id"]
    rows = client.get("/api/inventory/balances").json()["data"]
    assert len(rows) == 1 and rows[0]["available"] == 10
    assert client.put(f"/api/catalog/skus/{sku_id}", json={**changed_sku, "color": "black"}).status_code == 409
    assert client.put(f"/api/catalog/skus/{sku_id}", json=changed_sku).status_code == 200
    assert client.post(f'/api/inventory/documents/{posted.json()["data"]["id"]}/reversal',
                       json={"idempotency_key": "reverse", "reason": "wrong count"}).status_code == 403
    current["permissions"].append("inventory:admin")
    grant_current()
    assert client.post(f'/api/inventory/documents/{posted.json()["data"]["id"]}/reversal',
                       json={"idempotency_key": "reverse", "reason": "wrong count"}).status_code == 200
    assert client.get("/api/inventory/balances").json()["data"][0]["available"] == 0
    assert rows[0]["warehouse_name"] == "Main" and rows[0]["sku_code"] == "S1"
    ledger_url = f"/api/inventory/ledger?warehouse_id={warehouse_id}&sku_id={sku_id}"
    movements = client.get(ledger_url).json()["data"]
    assert [row["on_hand_delta"] for row in movements] == [-10, 10]
    assert movements[0]["product_name"] == "Hair"
    assert client.get(ledger_url + "&offset=1&limit=1").json()["data"] == movements[1:]
    assert client.get("/api/inventory/ledger?sku_id=999999").json()["data"] == []
    current["permissions"].remove("inventory:read")
    assert client.get(ledger_url).status_code == 403
    current["permissions"].append("inventory:read")
    products = client.get("/api/catalog/products").json()["data"]
    assert products["total"] == 1 and products["items"][0]["skus"][0]["id"] == sku_id
