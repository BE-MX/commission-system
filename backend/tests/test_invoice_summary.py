"""Invoice overview totals across visible orders and a selected order-date range."""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.models import ArkUser
from app.auth.utils import create_access_token
from app.core.database import get_db
from app.invoice.models import Invoice, InvoiceDelegateGrant
from app.invoice.router import router
from tests.authority_helpers import seed_authority


@contextmanager
def _client(db, *, user_id=5, permissions=("invoice:read",)):
    app = FastAPI()
    app.include_router(router, prefix="/api/invoice")
    # The hardened read path requires a fresh transaction boundary; a shared
    # session must roll back the previous request's read transaction first.
    app.dependency_overrides[get_db] = lambda: (db.rollback(), db)[1]
    token = create_access_token({
        "sub": str(user_id), "username": f"user{user_id}", "roles": [],
        "permissions": list(permissions),
    })
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


def _invoice(db, number, *, day=date(2026, 9, 15), salesperson=5, creator=5,
             customer="A", amount="100.00", currency="USD", new_deal=0,
             sync_status="synced", status="ready"):
    db.add(Invoice(
        invoice_no=number, order_type="stock", customer_id=customer,
        customer_name=f"Customer {customer}", invoice_date=day,
        sales_user_id=salesperson, created_by=creator,
        total_amount=Decimal(amount), currency=currency, okki_new_deal=new_deal,
        sync_status=sync_status, status=status,
    ))


def test_summary_uses_all_visible_synced_invoices_not_current_page(db):
    db.add_all([
        ArkUser(id=5, username="viewer", password_hash="x", real_name="Viewer"),
        ArkUser(id=6, username="owner", password_hash="x", real_name="Owner"),
    ])
    db.flush()
    grant = InvoiceDelegateGrant(delegate_user_id=5, sales_user_id=6, created_by=6)
    db.add(grant)
    _invoice(db, "A-1", day=date(2026, 9, 1), customer="A", amount="100", new_deal=1)
    _invoice(db, "A-2", day=date(2026, 9, 30), customer="A", amount="50", new_deal=1)
    _invoice(db, "B-1", salesperson=6, creator=5, customer="B", amount="200", new_deal=1)
    _invoice(db, "EUR-1", customer="D", amount="99", currency="EUR")
    _invoice(db, "LEGACY-NULL", customer="E", amount="40", new_deal=None)
    _invoice(db, "OTHER", salesperson=6, creator=6, customer="C", amount="1000", new_deal=1)
    _invoice(db, "AUG", day=date(2026, 8, 31), amount="400")
    _invoice(db, "DRAFT", amount="300", sync_status="not_synced")
    _invoice(db, "CANCEL-PENDING", amount="500", status="cancel_pending")
    _invoice(db, "CANCELLED", amount="500", status="cancelled")
    # Live authorization is read from the database: the viewer holds invoice:read,
    # the read-all viewer is a separate account with the data-scope grant.
    seed_authority(db, 5, "invoice:read")
    seed_authority(db, 8, "invoice:read", "invoice:read_all")

    with _client(db) as client:
        result = client.get("/api/invoice/invoices/summary", params={
            "date_from": "2026-09-01", "date_to": "2026-09-30",
        })
        assert result.status_code == 200
        summary = result.json()["data"]
        assert summary == {
            "gmv": 390.0, "new_sign_count": 2, "unknown_new_sign_count": 1,
            "order_count": 5, "average_order_amount": 97.5, "non_usd_count": 1,
        }
        page = client.get("/api/invoice/invoices", params={"page_size": 1})
        assert page.status_code == 200
        assert len(page.json()["data"]["items"]) == 1

    with _client(db, user_id=8, permissions=("invoice:read", "invoice:read_all")) as client:
        result = client.get("/api/invoice/invoices/summary", params={
            "date_from": "2026-09-01", "date_to": "2026-09-30",
        })
        assert result.json()["data"]["order_count"] == 6

    db.delete(grant)
    db.commit()
    with _client(db) as client:
        result = client.get("/api/invoice/invoices/summary", params={
            "date_from": "2026-09-01", "date_to": "2026-09-30",
        })
        assert result.json()["data"]["order_count"] == 4
        assert result.json()["data"]["new_sign_count"] == 1


def test_summary_rejects_invalid_range_and_requires_read_permission(db):
    # The reader holds a live invoice:read grant; the second account has none.
    seed_authority(db, 5, "invoice:read")
    seed_authority(db, 7)
    with _client(db) as client:
        empty = client.get("/api/invoice/invoices/summary", params={
            "date_from": "2026-10-01", "date_to": "2026-10-31",
        })
        assert empty.json()["data"]["gmv"] == 0.0
        assert empty.json()["data"]["average_order_amount"] == 0.0
        result = client.get("/api/invoice/invoices/summary", params={
            "date_from": "2026-10-01", "date_to": "2026-09-30",
        })
        assert result.status_code == 422

    with _client(db, user_id=7, permissions=()) as client:
        result = client.get("/api/invoice/invoices/summary", params={
            "date_from": "2026-09-01", "date_to": "2026-09-30",
        })
        assert result.status_code == 403
