"""Shadow permissions intersect live action, invoice scope and finance access."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
import pytest
from app.auth.dependencies import get_current_user
from app.auth.models import ArkRole, ArkPermission, ArkUserRole, ArkRolePermission
from app.core.database import get_db
from app.commerce_shadow.router import router
from app.commerce_shadow.schemas import ReplayRequest
from app.commerce_shadow import service
from tests.test_commerce_shadow import isolated, observe
from app.commerce_shadow.models import ShadowDifference, ShadowOutbox, ShadowResult
from tests.test_inventory_local import stock
from tests.test_invoice_commerce import buyer
from tests.test_finance_local import finance


def client_for(db, isolated):
    app = FastAPI()
    app.include_router(router, prefix="/api/commerce-shadow")
    app.dependency_overrides[get_db] = lambda: db
    # Stale/forged JWT roles do not grant any live shadow permissions.
    app.dependency_overrides[get_current_user] = lambda: {"sub": isolated[3]["sub"], "roles": ["super_admin"]}
    return TestClient(app)


def grant(db, isolated, codes):
    role = ArkRole(name="shadow-observer", label="Observer")
    db.add(role)
    db.flush()
    db.add(ArkUserRole(user_id=int(isolated[3]["sub"]), role_id=role.id))
    for code in codes:
        module, action = code.split(":")
        permission = ArkPermission(code=code, module=module, action=action, label=code)
        db.add(permission)
        db.flush()
        db.add(ArkRolePermission(role_id=role.id, permission_id=permission.id))
    db.commit()
    return role


def test_live_permissions_override_claims_and_revocation_is_immediate(db, isolated):
    client = client_for(db, isolated)
    assert client.get("/api/commerce-shadow/status").status_code == 403
    role = grant(db, isolated, ["commerce_shadow:read", "invoice:read"])
    assert client.get("/api/commerce-shadow/status").status_code == 200
    db.query(ArkUserRole).filter_by(user_id=int(isolated[3]["sub"]), role_id=role.id).delete()
    db.commit()
    assert client.get("/api/commerce-shadow/status").status_code == 403


def test_shadow_role_does_not_grant_financial_evidence_or_other_invoice_scope(db, isolated):
    grant(db, isolated, ["commerce_shadow:read", "invoice:read"])
    observation = observe(db, isolated, expected={"gross_amount": "1000"})
    row = service.request_run(db, ReplayRequest(dataset_id="dataset-1", request_key="scope", invoice_ids=[901],
        through_observation_id=observation.id), isolated[3])
    db.commit()
    client = client_for(db, isolated)
    assert client.get("/api/commerce-shadow/status").json()["data"]["pending_outbox"] == 0
    assert client.get("/api/commerce-shadow/runs").json()["data"]["items"] == []
    assert client.get(f"/api/commerce-shadow/runs/{row.id}").status_code == 404
    # With finance permission the same object becomes visible, no credentials.
    role = db.scalar(select(ArkRole).where(ArkRole.name == "shadow-observer"))
    permission = ArkPermission(code="receipt:read", module="receipt", action="read", label="Receipt read")
    db.add(permission)
    db.flush()
    db.add(ArkRolePermission(role_id=role.id, permission_id=permission.id))
    db.commit()
    response = client.get(f"/api/commerce-shadow/runs/{row.id}")
    assert response.status_code == 200
    assert "command" not in response.json()["data"]
    assert "database_url" not in response.text.lower()
    # Transfer current object access; old run ownership never grants access.
    isolated[2].sales_user_id = 999
    isolated[2].created_by = 999
    db.commit()
    assert client.get(f"/api/commerce-shadow/runs/{row.id}").status_code == 404


def test_public_replay_cannot_accept_target_seed_credentials_or_shadow_bypass(db, isolated):
    grant(db, isolated, ["commerce_shadow:write", "invoice:read"])
    client = client_for(db, isolated)
    response = client.post("/api/commerce-shadow/runs", json={"dataset_id": "dataset-1", "request_key": "malicious",
        "invoice_ids": [901], "through_observation_id": 1, "target_url": "mysql://invalid", "actor": {"roles": ["super_admin"]}})
    assert response.status_code == 422


def test_pagination_and_filters_count_only_live_visible_rows(db, isolated):
    grant(db, isolated, ["commerce_shadow:read", "invoice:read"])
    observation = observe(db, isolated, action="contract.create", expected={"total_amount": "10"})
    rows = [service.request_run(db, ReplayRequest(dataset_id="dataset-1", request_key=f"page-{index}", invoice_ids=[901],
        through_observation_id=observation.id), isolated[3]) for index in range(3)]
    # Read-model fixtures only: this test does not execute/declare a comparison.
    db.add_all([ShadowDifference(run_id=rows[0].id, observation_id=observation.id, invoice_id=901,
        field=field, expected={"value": "10"}, actual={"value": "11"}) for field in ("total_amount", "product_amount")])
    db.commit()
    client = client_for(db, isolated)
    first = client.get("/api/commerce-shadow/runs", params={"page": 1, "page_size": 1, "dataset_id": "dataset-1", "invoice_id": 901}).json()["data"]
    second = client.get("/api/commerce-shadow/runs", params={"page": 2, "page_size": 1, "dataset_id": "dataset-1", "invoice_id": 901}).json()["data"]
    assert first["total"] == second["total"] == 3
    assert len(first["items"]) == len(second["items"]) == 1
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert client.get("/api/commerce-shadow/runs", params={"dataset_id": "other"}).json()["data"]["total"] == 0
    differences = client.get("/api/commerce-shadow/differences", params={"page": 2, "page_size": 1, "dataset_id": "dataset-1", "invoice_id": 901}).json()["data"]
    assert differences["total"] == 2 and len(differences["items"]) == 1
    isolated[2].sales_user_id = 999
    isolated[2].created_by = 999
    db.commit()
    assert client.get("/api/commerce-shadow/runs").json()["data"]["total"] == 0
    assert client.get("/api/commerce-shadow/differences").json()["data"]["total"] == 0


def test_operator_transport_exports_inputs_only_and_imports_exact_candidate_receipt(db, isolated, finance):
    from app.commerce_shadow.transport import execute_input_bundle
    from tests.test_finance_local import payment
    from app.invoice.settlement_models import ReceiptBatch
    from sqlalchemy import func
    from sqlalchemy.orm import Session
    grant(db, isolated, ["commerce_shadow:admin", "invoice:read", "receipt:read"])
    customer, _, bank = finance
    observation = observe(db, isolated, body=payment(customer, bank).model_dump(mode="json"),
        expected={"gross_amount": "1000.00", "net_amount": "980.00", "finance_status": "registered"})
    row = service.request_run(db, ReplayRequest(dataset_id="dataset-1", request_key="operator-transport", invoice_ids=[901],
        through_observation_id=observation.id), isolated[3])
    db.commit()
    client = client_for(db, isolated)
    exported = client.get(f"/api/commerce-shadow/runs/{row.id}/input")
    assert exported.status_code == 200, exported.text
    assert exported.headers["cache-control"] == "private, no-store"
    bundle = exported.json()["data"]
    assert "result" not in bundle["commands"][0] and "outcome" not in bundle["commands"][0]
    assert db.scalar(select(ShadowOutbox)).state == "pending"
    report = execute_input_bundle(isolated[0], bundle)
    imported = client.post(f"/api/commerce-shadow/runs/{row.id}/receipts", json=report)
    assert imported.status_code == 200, imported.text
    assert imported.json()["data"]["status"] == "consistent"
    assert client.post(f"/api/commerce-shadow/runs/{row.id}/receipts", json=report).status_code == 200
    assert db.scalar(select(func.count()).select_from(ShadowResult)) == 1
    with Session(isolated[0]) as target:
        assert target.scalar(select(func.count()).select_from(ReceiptBatch)) == 1
    forged = {**report, "bundle_hash": "b" * 64}
    assert client.post(f"/api/commerce-shadow/runs/{row.id}/receipts", json=forged).status_code == 409
    forged = {**report, "target_url": "mysql://forbidden"}
    assert client.post(f"/api/commerce-shadow/runs/{row.id}/receipts", json=forged).status_code == 422
    # Current ownership is checked again on BOTH transport operations.
    isolated[2].sales_user_id = 999
    isolated[2].created_by = 999
    db.commit()
    assert client.get(f"/api/commerce-shadow/runs/{row.id}/input").status_code == 404
    assert client.post(f"/api/commerce-shadow/runs/{row.id}/receipts", json=report).status_code == 404


def test_shadow_read_role_cannot_export_commands_or_import_receipts(db, isolated):
    grant(db, isolated, ["commerce_shadow:read", "invoice:read", "receipt:read"])
    observation = observe(db, isolated, expected={"gross_amount": "1000"})
    row = service.request_run(db, ReplayRequest(dataset_id="dataset-1", request_key="read-transport", invoice_ids=[901],
        through_observation_id=observation.id), isolated[3])
    db.commit()
    client = client_for(db, isolated)
    assert client.get(f"/api/commerce-shadow/runs/{row.id}/input").status_code == 403
    response = client.post(f"/api/commerce-shadow/runs/{row.id}/receipts", json={"run_id": row.id, "dataset_id": "dataset-1",
        "bundle_hash": "a" * 64, "target_fingerprint": "a" * 64, "results": [], "missing_dependencies": []})
    assert response.status_code == 403


@pytest.mark.parametrize("action,required", [
    ("contract.confirm", ("invoice:write",)),
    ("payment.confirm", ("receipt:admin",)),
    ("payment.void", ("receipt:write",)),
    ("allocation.reverse", ("receipt:admin",)),
    ("shipment.create", ("shipment:write", "invoice:write")),
    ("shipment.dispatch", ("shipment:write", "invoice:write", "inventory:write")),
    ("shipment.ready", ("shipment:write",)),
])
def test_candidate_authority_matches_formal_action_permissions(action, required):
    from app.commerce_shadow.dispatcher import action_permissions, require_permissions
    from fastapi import HTTPException
    assert action_permissions(action) == required
    require_permissions({"roles": ["operator"], "permissions": list(required)}, *required)
    with pytest.raises(HTTPException) as denied:
        require_permissions({"roles": ["operator"], "permissions": []}, *required)
    assert denied.value.status_code == 403


def test_candidate_cannot_confirm_money_using_a_frozen_non_finance_admin(db, isolated, finance):
    from tests.test_finance_local import payment, cmd
    from tests.test_commerce_shadow import run
    from app.commerce_shadow.models import ShadowExecution
    from app.finance.models import FinanceEvent
    from app.invoice.settlement_models import ReceiptBatch
    from sqlalchemy.orm import Session
    from sqlalchemy import func
    customer, _, bank = finance
    first = observe(db, isolated, body=payment(customer, bank).model_dump(mode="json"), expected={"gross_amount": "1000"})
    actor = {"sub": isolated[3]["sub"], "roles": ["sales"], "permissions": ["receipt:write", "receipt:read"]}
    service.record_observation(db, source_event_id="denied-finance-confirm", invoice_id=901, action="payment.confirm",
        request_key="denied-finance-confirm", command={"body": cmd("denied-finance-confirm", 1).model_dump(mode="json"),
            "actor": actor, "target_id": {"$ref": first.source_event_id, "field": "id"}},
        outcome="rejected", result={}, contract_revision=1, causal_version=2, dependencies=[first.source_event_id],
        actor_id=int(actor["sub"]), reason_code="原始操作人无权执行该候选命令")
    row = run(db, isolated)
    assert row.status == "consistent", row.coverage
    with Session(isolated[0]) as target:
        assert target.scalar(select(ReceiptBatch)).finance_status == "registered"
        assert target.scalar(select(func.count()).select_from(FinanceEvent)) == 1
        rejected = target.scalar(select(ShadowExecution).where(ShadowExecution.source_event_id == "denied-finance-confirm"))
        assert rejected.outcome == "rejected"
