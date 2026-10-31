"""Actual HTTP/domain hooks and the credential-free persistent worker process."""
import json
from pathlib import Path
import subprocess
import sys
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.auth.models import ArkRole, ArkUserRole, ArkPermission, ArkRolePermission, ArkUser
from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.commerce_shadow.models import ShadowObservation, ShadowOutbox, ShadowExecution
from app.commerce_shadow import service as shadow
from app.commerce_shadow.schemas import ReplayRequest
from app.commerce_shadow.transport import export_input_bundle, import_execution_receipts
from app.invoice.commerce_router import router as commerce_router
from app.invoice.models import Invoice, InvoiceCommerceEvent
from app.finance.router import router as finance_router
from app.finance.models import FinanceEvent
from tests.test_commerce_shadow import isolated, observe
from tests.test_inventory_local import stock
from tests.test_invoice_commerce import buyer, draft
from tests.test_finance_local import finance, payment


@pytest.fixture
def observing(db, isolated, monkeypatch):
    role = db.scalar(select(ArkRole).where(ArkRole.name == "super_admin"))
    if role is None:
        role = ArkRole(name="super_admin", label="Administrator")
        db.add(role)
        db.flush()
    db.add(ArkUserRole(user_id=int(isolated[3]["sub"]), role_id=role.id))
    db.commit()
    monkeypatch.setattr(get_settings(), "COMMERCE_SHADOW_ENABLED", True)
    app = FastAPI()
    app.include_router(commerce_router, prefix="/native")
    app.include_router(finance_router, prefix="/finance")
    def request_db():
        if db.in_transaction():
            assert not db.new and not db.dirty and not db.deleted
            db.rollback()  # Real get_db supplies a fresh session per HTTP request.
        yield db
        if db.in_transaction():
            db.rollback()
    app.dependency_overrides[get_db] = request_db
    app.dependency_overrides[get_current_user] = lambda: isolated[3]
    return TestClient(app, raise_server_exceptions=False), role


def test_actual_controller_observes_atomic_success_and_keeps_original_retry_snapshot(db, isolated, observing, buyer, stock):
    client, _ = observing
    customer, user = buyer
    body = draft(customer, user, stock[0], order_type="production", request_key="http-create", invoice_no="OBS-HTTP").model_dump(mode="json")
    first = client.post("/native/invoices", json=body)
    assert first.status_code == 201, first.text
    invoice_id = first.json()["data"]["id"]
    confirmed = client.post(f"/native/invoices/{invoice_id}/confirm", json={"request_key": "http-confirm", "expected_version": 1,
        "expected_authority_epoch": 1, "reason": "verified"})
    assert confirmed.status_code == 200, confirmed.text
    retried = client.post("/native/invoices", json=body)
    assert retried.status_code == 201, retried.text
    rows = db.scalars(select(ShadowObservation).order_by(ShadowObservation.id)).all()
    assert len(rows) == 2 and rows[0].result["metrics"]["commerce_status"] == "draft"
    assert rows[1].result["metrics"]["commerce_status"] == "confirmed"
    assert rows[1].command["target_id"]["$ref"] == rows[0].source_event_id
    assert rows[0].source_event_id in rows[1].dependencies
    assert db.scalar(select(func.count()).select_from(ShadowOutbox)) == 2


def test_actual_controller_failure_rolls_back_economy_then_commits_diagnostic(db, isolated, observing, buyer, stock):
    client, _ = observing
    customer, user = buyer
    created = client.post("/native/invoices", json=draft(customer, user, stock[0], order_type="production", request_key="reject-create").model_dump(mode="json"))
    assert created.status_code == 201, created.text
    identity = created.json()["data"]["id"]
    rejected = client.post(f"/native/invoices/{identity}/confirm", json={"request_key": "rejected-version", "expected_version": 99,
        "expected_authority_epoch": 1, "reason": "stale input"})
    assert rejected.status_code == 409, rejected.text
    assert db.get(Invoice, identity).commerce_status == "draft"
    assert db.scalar(select(InvoiceCommerceEvent.id).where(InvoiceCommerceEvent.request_key == "rejected-version")) is None
    diagnostic = db.scalar(select(ShadowObservation).where(ShadowObservation.outcome == "rejected"))
    assert diagnostic and diagnostic.command["body"]["expected_version"] == 99
    assert diagnostic.result == {} and db.scalar(select(ShadowOutbox).where(ShadowOutbox.observation_id == diagnostic.id))


def test_revoked_database_role_defeats_stale_superadmin_jwt_on_actual_mutations(db, isolated, observing, buyer, stock):
    client, role = observing
    user_id = int(isolated[3]["sub"])
    db.query(ArkUserRole).filter_by(user_id=user_id, role_id=role.id).delete()
    db.commit()
    customer, user = buyer
    response = client.post("/native/invoices", json=draft(customer, user, stock[0], order_type="production", request_key="revoked").model_dump(mode="json"))
    assert response.status_code == 403, response.text
    response = client.post("/finance/payments", json=payment(customer, finance_account(db), key="revoked-pay").model_dump(mode="json"))
    assert response.status_code == 403, response.text
    assert not db.scalars(select(ShadowObservation)).all()
    assert not db.scalars(select(InvoiceCommerceEvent)).all()


def finance_account(db):
    from app.finance.models import BankAccount
    return db.scalar(select(BankAccount))


def test_cli_ignores_environment_and_replays_real_domain_without_source_session(db, isolated, finance, tmp_path):
    customer, user, bank = finance
    observation = observe(db, isolated, body=payment(customer, bank).model_dump(mode="json"), expected={"gross_amount": "1000", "net_amount": "980"})
    row = shadow.request_run(db, ReplayRequest(dataset_id="dataset-1", request_key="cli-run", invoice_ids=[901],
        through_observation_id=observation.id), user)
    db.commit()
    bundle = export_input_bundle(db, row.id)
    path, report = tmp_path / "input.json", tmp_path / "report.json"
    path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    pollution = {"OKKI_CLIENT_SECRET": "must-never-inherit", "COMMISSION_DB_HOST": "production.invalid",
        "COMMISSION_DB_PASSWORD": "must-never-inherit", "SCHEDULER_ENABLED": "true", "PORTAL_ENABLED": "true",
        "HTTP_PROXY": "http://127.0.0.1:1", "PYTHONIOENCODING": "utf-8"}
    base = [sys.executable, "-m", "app.commerce_shadow.cli", "--target-url", str(isolated[0].url)]
    backend = str(Path(__file__).resolve().parents[1])
    audit = subprocess.run(base + ["--audit-settings"], cwd=backend, env=pollution, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert audit.returncode == 0, audit.stderr
    audit_data = json.loads(audit.stdout)
    assert audit_data["execution_only"] and not audit_data["external_credentials_present"] and not audit_data["scheduler_enabled"]
    command = base + ["--input", str(path), "--report", str(report)]
    for _ in range(2):
        executed = subprocess.run(command, cwd=backend, env=pollution, capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert executed.returncode == 0, executed.stderr + executed.stdout
        assert "must-never-inherit" not in executed.stdout + executed.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    import_execution_receipts(db, bundle, payload)
    db.commit()
    assert row.status == "consistent", row.coverage
    with Session(isolated[0]) as target:
        assert target.scalar(select(func.count()).select_from(FinanceEvent)) == 1
        assert target.scalar(select(func.count()).select_from(ShadowExecution)) == 1


def test_same_original_request_after_false_source_rejection_has_one_candidate_payment(db, isolated, finance):
    from app.commerce_shadow.worker import run_replay
    customer, user, bank = finance
    body = payment(customer, bank, key="same-economic-command").model_dump(mode="json")
    observe(db, isolated, event="wrongly-rejected", sequence=1, body=body, outcome="rejected", reason="source policy error")
    accepted = observe(db, isolated, event="later-accepted", sequence=2, body=body, expected={"gross_amount": "1000"})
    row = shadow.request_run(db, ReplayRequest(dataset_id="dataset-1", request_key="false-rejection-retry", invoice_ids=[901],
        through_observation_id=accepted.id), user)
    db.commit()
    run_replay(db, row.id, isolated[0])
    db.commit()
    assert row.status == "differences"
    with Session(isolated[0]) as target:
        assert target.scalar(select(func.count()).select_from(FinanceEvent)) == 1
        assert target.scalar(select(func.count()).select_from(ShadowExecution)) == 2
