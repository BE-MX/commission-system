"""Native forms resolve business identities and financial reversals within live scope."""
from datetime import date
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser
from app.core.database import get_db
from app.core.time import beijing_now
from app.customer.models import CustomerAssignment
from app.finance.router import router as finance_router
from app.finance import service
from app.finance.schemas import AllocationCreate
from app.invoice.commerce_router import router as invoice_router
from app.invoice.models import Invoice
from app.invoice.settlement_models import ShipmentSettlement
from tests.test_finance_local import finance, payment, cmd, order
from tests.test_invoice_commerce import buyer
from tests.test_inventory_local import stock


def test_form_candidates_and_finance_details_respect_actual_scope(db, finance, stock, buyer):
    customer, admin, account = finance
    invoice, target = order(db, stock, buyer)
    batch = service.register(db, payment(customer, account), admin)
    service.confirm(db, batch.id, cmd("confirm-pay", 1), admin)
    allocation = service.allocate(db, batch.id, AllocationCreate(request_key="allocated", expected_version=2,
        invoice_id=invoice.id, receivable_id=target.id, amount="400", business_date=date(2026, 10, 3)), admin)
    db.add(CustomerAssignment(customer_id=customer.id, user_id=int(admin["sub"]), assignment_role="primary",
        assignment_status="active", assignment_source="admin_assign", effective_from=beijing_now()))
    successor = ArkUser(username="unrelated", real_name="Other", password_hash="unused")
    db.add(successor)
    db.add(Invoice(invoice_no="LEGACY", invoice_date=date(2026, 10, 3), customer_id="99", customer_name="Legacy",
                   sales_user_id=int(admin["sub"]), transaction_mode="legacy"))
    settlement = ShipmentSettlement(invoice_id=invoice.id, sequence=1, settlement_no="BATCH-1", state="awaiting_payment",
        is_final=0, quote={"goods_amount": "100.00"}, quote_hash="unused", request_key="quote-test", request_hash="unused",
        created_by=int(admin["sub"]))
    db.add(settlement)
    db.commit()
    current = {"sub": admin["sub"], "roles": [], "permissions": ["invoice:read", "invoice:write", "receipt:read", "receipt:write"]}
    app = FastAPI()
    app.include_router(invoice_router, prefix="/api/invoice/local")
    app.include_router(finance_router, prefix="/api/finance")
    app.dependency_overrides[get_current_user] = lambda: current
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    for domain in ("invoice/local", "finance"):
        result = client.get(f"/api/{domain}/customer-options?keyword=Original").json()["data"]
        assert result["total"] == 1 and result["items"][0]["id"] == customer.id
        assert client.get(f"/api/{domain}/customer-options?page=2&page_size=1").json()["data"]["items"] == []
    native = client.get("/api/invoice/local/invoices").json()["data"]
    assert native["total"] == 1 and native["items"][0]["id"] == invoice.id
    assert native["items"][0]["total_amount"] == "1000.00"
    assert client.get("/api/invoice/local/invoices?commerce_status=draft").json()["data"]["total"] == 0
    reference = client.get("/api/invoice/local/reference-data").json()["data"]
    assert len(reference["warehouses"]) == 2 and len(reference["currencies"]) == 2
    options = client.get(f"/api/finance/order-options?customer_id={customer.id}&currency=USD").json()["data"]
    assert options["total"] == 1 and options["items"][0]["invoice_no"] == invoice.invoice_no
    detail = client.get(f"/api/finance/payments/{batch.id}").json()["data"]
    assert detail["customer_name"] == customer.display_name and detail["account_name"] == account.name
    assert detail["allocations"][0]["id"] == allocation.id and detail["allocations"][0]["effective_amount"] == "400.00"
    receivables = client.get(f"/api/finance/invoices/{invoice.id}/receivables").json()["data"]
    assert receivables["invoice"]["id"] == invoice.id and receivables["items"][0]["settlement_id"] is None
    assert receivables["settlements"][0]["id"] == settlement.id
    current["sub"] = str(successor.id)
    assert client.get("/api/invoice/local/customer-options").json()["data"]["total"] == 0
    assert client.get("/api/finance/customer-options").json()["data"]["total"] == 0
    assert client.get("/api/invoice/local/invoices").json()["data"]["total"] == 0
    assert client.get("/api/finance/order-options").json()["data"]["total"] == 0
    assert client.get(f"/api/finance/payments/{batch.id}").status_code == 404
    current["permissions"] = ["receipt:admin"]
    assert client.get("/api/finance/reference-data").status_code == 200
    assert client.get("/api/finance/payments").status_code == 403
    current["permissions"] = []
    assert client.get("/api/finance/reference-data").status_code == 403
    assert client.get("/api/invoice/local/customer-options").status_code == 403
    assert client.get("/api/finance/customer-options").status_code == 403
