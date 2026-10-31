"""Financial mutation permissions and live customer handover visibility."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser
from app.core.database import get_db
from app.core.time import beijing_now
from app.customer.models import CustomerAssignment
from app.finance.router import router
from app.finance import service
from tests.test_finance_local import finance, payment, cmd
from tests.test_invoice_commerce import buyer
from tests.test_inventory_local import stock


def test_financial_admin_boundary_and_customer_handover(db, finance):
    from tests.authority_helpers import seed_authority
    customer, admin, account = finance
    row = service.register(db, payment(customer, account), admin)
    successor = ArkUser(username="successor", password_hash="test-only", real_name="Successor")
    db.add(successor)
    db.flush()
    assignment = CustomerAssignment(customer_id=customer.id, user_id=int(admin["sub"]), assignment_role="primary",
        assignment_status="active", assignment_source="admin_assign", effective_from=beijing_now())
    db.add(assignment)
    seed_authority(db, int(admin['sub']), 'receipt:read', 'receipt:write')
    seed_authority(db, successor.id, 'receipt:read', 'receipt:write')
    current = {"sub": admin["sub"], "roles": [], "permissions": ["receipt:read", "receipt:write"]}
    app = FastAPI()
    app.include_router(router, prefix="/api/finance")
    app.dependency_overrides[get_current_user] = lambda: current
    def fresh_db():
        db.rollback()
        try:
            yield db
        finally:
            db.rollback()
    app.dependency_overrides[get_db] = fresh_db
    client = TestClient(app)
    endpoint = f"/api/finance/payments/{row.id}"
    assert client.post(endpoint + "/confirm", json=cmd("confirm", 1).model_dump(mode="json")).status_code == 403
    assert len(client.get("/api/finance/payments").json()["data"]["items"]) == 1
    assignment.user_id = successor.id
    db.commit()
    assert client.get("/api/finance/payments").json()["data"]["items"] == []
    assert client.get(endpoint).status_code == 404
    current["sub"] = str(successor.id)
    assert len(client.get("/api/finance/payments").json()["data"]["items"]) == 1
    current["roles"] = ["super_admin"]
    # Stale JWT admin status cannot grant financial confirmation.
    assert client.post(endpoint + '/confirm', json=cmd('confirm', 1).model_dump(mode='json')).status_code == 403
    seed_authority(db, successor.id, 'receipt:admin')
    response = client.post(endpoint + "/confirm", json=cmd("confirm", 1).model_dump(mode="json"))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["available_amount"] == "1000.00"
    unsupported = client.put("/api/finance/currencies", json={"request_key": "unsupported-code", "code": "TEST",
        "name": "Unsupported", "rate_to_cny": "1", "active": True})
    assert unsupported.status_code == 422 and unsupported.json()["detail"][0]["loc"] == ["body", "code"]
