"""订单代创建授权：执行人与业务归属必须分离。"""

from datetime import date

import pytest
from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.models import ArkUser, ArkUserExternalBinding
from app.invoice import delegation_service, service
from app.invoice.models import Invoice, InvoiceDelegateGrant
from app.invoice.schemas import InvoiceCreate
from app.auth.utils import create_access_token
from app.core.database import get_db


def _user(db, user_id: int, name: str, *, active: bool = True) -> ArkUser:
    row = ArkUser(
        id=user_id,
        username=name.lower(),
        real_name=name,
        password_hash="x",
        email=f"{name.lower()}@example.com",
        phone=f"1380000{user_id:04d}",
        is_active=active,
    )
    db.add(row)
    db.flush()
    return row


def _client(db, *, sub: int, permissions: list[str]):
    from app.invoice.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/invoice")
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    token = create_access_token({
        "sub": str(sub), "username": f"user{sub}", "roles": [], "permissions": permissions,
    })
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def test_assignees_include_self_and_only_active_grants(db):
    assistant = _user(db, 201, "B")
    sales_a = _user(db, 202, "A")
    sales_c = _user(db, 203, "C", active=False)
    db.add_all([
        InvoiceDelegateGrant(delegate_user_id=assistant.id, sales_user_id=sales_a.id, created_by=999),
        InvoiceDelegateGrant(delegate_user_id=assistant.id, sales_user_id=sales_c.id, created_by=999),
        ArkUserExternalBinding(
            ark_user_id=sales_a.id,
            provider="okki",
            external_account_id="okki-a",
            binding_status="active",
        ),
    ])
    db.flush()

    rows = delegation_service.list_assignees(db, assistant.id)

    assert [row["id"] for row in rows] == [assistant.id, sales_a.id]
    assert rows[1]["real_name"] == "A"
    assert rows[1]["email"] == "a@example.com"
    assert rows[1]["okki_bound"] is True
    assert rows[1]["okki_department_configured"] is False


def test_replace_grants_is_exact_and_rejects_self_or_inactive_users(db):
    assistant = _user(db, 211, "B")
    sales_a = _user(db, 212, "A")
    sales_c = _user(db, 213, "C")
    inactive = _user(db, 214, "D", active=False)

    delegation_service.replace_grants(db, assistant.id, [sales_a.id, sales_c.id], operator_id=900)
    assert delegation_service.granted_sales_user_ids(db, assistant.id) == {sales_a.id, sales_c.id}

    delegation_service.replace_grants(db, assistant.id, [sales_c.id], operator_id=901)
    assert delegation_service.granted_sales_user_ids(db, assistant.id) == {sales_c.id}

    with pytest.raises(ValueError, match="不能授权自己"):
        delegation_service.replace_grants(db, assistant.id, [assistant.id], operator_id=900)
    with pytest.raises(ValueError, match="无效或已停用"):
        delegation_service.replace_grants(db, assistant.id, [inactive.id], operator_id=900)


def test_create_delegated_invoice_preserves_creator_and_derives_sales_snapshot(db):
    assistant = _user(db, 221, "B")
    sales_a = _user(db, 222, "A")
    db.add(InvoiceDelegateGrant(
        delegate_user_id=assistant.id,
        sales_user_id=sales_a.id,
        created_by=999,
    ))
    db.flush()
    body = InvoiceCreate(
        sales_user_id=sales_a.id,
        customer_id="10001",
        customer_name="Customer",
        invoice_date=date(2026, 8, 12),
        sales_user_name="FORGED",
        sales_email="forged@example.com",
        items=[],
    )

    invoice = service.create_invoice(db, body, user_id=assistant.id)

    assert invoice.created_by == assistant.id
    assert invoice.sales_user_id == sales_a.id
    assert invoice.sales_user_name == sales_a.username
    assert invoice.sales_email == sales_a.email
    assert invoice.sales_phone == sales_a.phone


def test_create_delegated_invoice_rejects_unauthorized_salesperson(db):
    assistant = _user(db, 231, "B")
    sales_a = _user(db, 232, "A")
    body = InvoiceCreate(
        sales_user_id=sales_a.id,
        customer_id="10001",
        customer_name="Customer",
        invoice_date=date(2026, 8, 12),
        items=[],
    )

    with pytest.raises(HTTPException) as exc:
        service.create_invoice(db, body, user_id=assistant.id)
    assert exc.value.status_code == 403


def test_visibility_separates_sales_owner_from_delegate_audit(db):
    assistant = _user(db, 241, "B")
    other_assistant = _user(db, 242, "E")
    sales_a = _user(db, 243, "A")
    db.add(InvoiceDelegateGrant(
        delegate_user_id=assistant.id, sales_user_id=sales_a.id, created_by=999,
    ))
    own_delegated = Invoice(
        invoice_no="DELEGATED-1", customer_id="1", customer_name="One",
        sales_user_id=sales_a.id, created_by=assistant.id,
        invoice_date=date(2026, 8, 12), currency="USD",
    )
    someone_elses = Invoice(
        invoice_no="DELEGATED-2", customer_id="2", customer_name="Two",
        sales_user_id=sales_a.id, created_by=other_assistant.id,
        invoice_date=date(2026, 8, 12), currency="USD",
    )
    db.add_all([own_delegated, someone_elses])
    db.flush()

    assert delegation_service.can_access_invoice(db, sales_a.id, own_delegated)
    assert delegation_service.can_access_invoice(db, sales_a.id, someone_elses)
    assert delegation_service.can_access_invoice(db, assistant.id, own_delegated)
    assert not delegation_service.can_access_invoice(db, assistant.id, someone_elses)

    db.query(InvoiceDelegateGrant).filter_by(delegate_user_id=assistant.id).delete()
    db.flush()
    assert not delegation_service.can_access_invoice(db, assistant.id, own_delegated)
    assert delegation_service.can_access_invoice(db, sales_a.id, own_delegated)


def test_list_scope_returns_owned_orders_and_only_own_authorized_delegations(db):
    assistant = _user(db, 251, "B")
    other_assistant = _user(db, 252, "E")
    sales_a = _user(db, 253, "A")
    db.add(InvoiceDelegateGrant(
        delegate_user_id=assistant.id, sales_user_id=sales_a.id, created_by=999,
    ))
    db.add_all([
        Invoice(invoice_no="OWN", customer_id="1", customer_name="Own", sales_user_id=assistant.id,
                created_by=assistant.id, invoice_date=date(2026, 8, 12), currency="USD"),
        Invoice(invoice_no="MINE", customer_id="2", customer_name="Mine", sales_user_id=sales_a.id,
                created_by=assistant.id, invoice_date=date(2026, 8, 12), currency="USD"),
        Invoice(invoice_no="OTHER", customer_id="3", customer_name="Other", sales_user_id=sales_a.id,
                created_by=other_assistant.id, invoice_date=date(2026, 8, 12), currency="USD"),
    ])
    db.flush()

    rows, total = service.list_invoices(db, viewer_user_id=assistant.id)

    assert total == 2
    assert {row["invoice_no"] for row in rows} == {"OWN", "MINE"}

    sales_a.is_active = False
    db.flush()
    rows, total = service.list_invoices(db, viewer_user_id=assistant.id)
    assert total == 1
    assert [row["invoice_no"] for row in rows] == ["OWN"]


def test_delegation_http_contract_lists_replaces_and_enforces_permissions(db):
    admin = _user(db, 261, "Admin")
    assistant = _user(db, 262, "B")
    sales_a = _user(db, 263, "A")

    with _client(db, sub=admin.id, permissions=["user:read", "user:write"]) as client:
        before = client.get(f"/api/invoice/delegations/users/{assistant.id}")
        assert before.status_code == 200
        assert before.json()["data"]["sales_user_ids"] == []

        saved = client.put(
            f"/api/invoice/delegations/users/{assistant.id}",
            json={"sales_user_ids": [sales_a.id]},
        )
        assert saved.status_code == 200

    with _client(db, sub=assistant.id, permissions=["invoice:write"]) as client:
        assignees = client.get("/api/invoice/delegations/assignees")
        assert assignees.status_code == 200
        assert {row["id"] for row in assignees.json()["data"]["items"]} == {assistant.id, sales_a.id}
        assert client.get(f"/api/invoice/delegations/users/{assistant.id}").status_code == 403
