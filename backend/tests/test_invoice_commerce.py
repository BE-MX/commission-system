"""Local order lifecycle needs no transaction mirror and is atomic with stock."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.customer.models import CustomerAccount
from app.invoice.commerce_schemas import LocalInvoiceAction, LocalInvoiceDraft, LocalItem
from app.invoice.commerce_service import create_draft, update_draft, confirm, cancel
from app.invoice.models import Invoice, InvoiceCommerceEvent
from app.invoice.settlement_models import Receivable
from app.inventory.service import post_document
from tests.test_inventory_local import stock, command, balance


@pytest.fixture
def buyer(db, stock):
    from app.commerce_transition.models import PlatformPolicy
    from app.commerce_transition import service as transition
    current = db.get(PlatformPolicy, 1)
    if current.phase == 'legacy_only':
        transition.set_writer_receipt(db, 'isolated-native-fixture', 1, 'compatible', {'enforced': True})
        transition.set_policy(db, phase='local_only', expected_version=current.version,
                              inventory_evidence={'all_writers': ['isolated-native-fixture']})
    account = CustomerAccount(customer_code="C1", display_name="Original buyer", entity_type="registered_company",
                              identity_status="verified", relationship_stage="active_customer",
                              relationship_stage_changed_at=beijing_now(), relationship_stage_reason="test",
                              record_status="active", identity_confidence=1, profile_completeness=100, profile_input_seq=1)
    user = ArkUser(username="seller", real_name="Seller", password_hash="unused")
    db.add_all([account, user])
    db.flush()
    return account, {"sub": str(user.id), "roles": ["super_admin"], "permissions": ["invoice:write"]}


def draft(customer, user, sku, **changes):
    values = dict(request_key="create", local_customer_id=customer.id, sales_user_id=int(user["sub"]),
                  invoice_date=date(2026, 10, 3), shipping_fee=Decimal("10"), surcharge_amount=Decimal("2"),
                  items=[LocalItem(local_sku_id=sku.id, quantity=3, price_per_piece=Decimal("12.3456"),
                                   discount_amount=Decimal("-1"))])
    values.update(changes)
    return LocalInvoiceDraft(**values)


def action(key, version, warehouse=None):
    return LocalInvoiceAction(request_key=key, expected_version=version, expected_authority_epoch=1,
                              warehouse_id=warehouse, reason="test")


def test_draft_confirm_cancel_without_mirror_tables(db, stock, buyer):
    sku, (wh, _) = stock
    customer, user = buyer
    post_document(db, command("opening", "receipt", wh, sku, 5), actor_id=None)
    body = draft(customer, user, sku)
    invoice = create_draft(db, body, user)
    assert create_draft(db, body, user).id == invoice.id
    assert invoice.total_amount == Decimal("48.04")
    assert invoice.customer_name == "Original buyer" and invoice.customer_id == f"ark:{customer.id}"
    customer.display_name = "Renamed buyer"
    confirmed = confirm(db, invoice.id, action("confirm", 1, wh.id), user)
    assert confirmed.customer_name == "Original buyer"
    assert confirm(db, invoice.id, action("confirm", 1, wh.id), user).id == invoice.id
    assert balance(db, wh, sku).reserved == 3
    receivables = db.scalars(select(Receivable).order_by(Receivable.id)).all()
    assert [(r.kind, r.amount) for r in receivables] == [("goods", Decimal("38.04")), ("freight", Decimal("10"))]
    from app.invoice.settlement_service import target
    assert target(db, invoice).id == receivables[0].id
    cancel(db, invoice.id, action("cancel", 2), user)
    assert cancel(db, invoice.id, action("cancel", 2), user).commerce_status == "cancelled"
    assert balance(db, wh, sku).reserved == 0
    assert balance(db, wh, sku).on_hand == 5
    assert len(db.scalars(select(InvoiceCommerceEvent)).all()) == 3


def test_failed_confirmation_rolls_back_whole_order(db, stock, buyer):
    sku, (wh, _) = stock
    customer, user = buyer
    post_document(db, command("opening", "receipt", wh, sku, 5), actor_id=None)
    body = draft(customer, user, sku, items=[LocalItem(local_sku_id=sku.id, quantity=3, price_per_piece=1)] * 2)
    invoice = create_draft(db, body, user)
    with pytest.raises(ValueError, match="库存"):
        confirm(db, invoice.id, action("confirm", 1, wh.id), user)
    assert invoice.commerce_status == "draft" and invoice.commerce_version == 1
    assert balance(db, wh, sku).reserved == 0
    assert not db.scalars(select(Receivable)).all()
    assert len(db.scalars(select(InvoiceCommerceEvent)).all()) == 1


def test_stale_edit_and_wrong_item_id_are_rejected(db, stock, buyer):
    sku, _ = stock
    customer, user = buyer
    invoice = create_draft(db, draft(customer, user, sku), user)
    old_item_id = invoice.items[0].id
    body = draft(customer, user, sku, request_key="edit", expected_version=1,
                 items=[LocalItem(id=old_item_id, local_sku_id=sku.id, quantity=2, price_per_piece=5)])
    update_draft(db, invoice.id, body, user)
    assert invoice.items[0].id == old_item_id and invoice.commerce_version == 2
    with pytest.raises(ValueError, match="刷新"):
        update_draft(db, invoice.id, body.model_copy(update={"request_key": "stale"}), user)
    with pytest.raises(ValueError, match="明细ID"):
        update_draft(db, invoice.id, body.model_copy(update={"request_key": "wrong-id", "expected_version": 2,
                     "items": [LocalItem(id=99999, local_sku_id=sku.id, quantity=1, price_per_piece=1)]}), user)
    assert invoice.items[0].quantity == 2


def test_different_request_and_missing_customer_scope_are_rejected(db, stock, buyer):
    sku, _ = stock
    customer, user = buyer
    body = draft(customer, user, sku)
    create_draft(db, body, user)
    with pytest.raises(ValueError, match="幂等"):
        create_draft(db, body.model_copy(update={"shipping_fee": Decimal("11")}), user)
    scoped_user = {**user, "roles": []}
    with pytest.raises(ValueError, match="FORBIDDEN"):
        create_draft(db, body.model_copy(update={"request_key": "no-scope"}), scoped_user)
    assert len(db.scalars(select(Invoice)).all()) == 1


def test_local_order_http_contract_and_legacy_write_fence(db, stock, buyer, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.invoice.commerce_router import router
    from app.invoice.lifecycle_guard import ensure_mutable
    from app.invoice.xiaoman_service import sync_invoice
    sku, (wh, _) = stock
    customer, current = buyer
    post_document(db, command("opening", "receipt", wh, sku, 5), actor_id=None)
    from tests.authority_helpers import seed_authority
    seed_authority(db, int(current['sub']), roles=('super_admin',))
    app = FastAPI()
    app.include_router(router, prefix="/api/invoice/local")
    app.dependency_overrides[get_current_user] = lambda: current
    def fresh_db():
        db.rollback()
        try:
            yield db
        finally:
            db.rollback()
    app.dependency_overrides[get_db] = fresh_db
    client = TestClient(app)
    payload = draft(customer, current, sku).model_dump(mode="json")
    response = client.post("/api/invoice/local/invoices", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["transaction_mode"] == "local" and data["commerce_version"] == 1
    assert data["items"][0]["local_sku_id"] == sku.id
    invoice_id = data["id"]
    response = client.post(f"/api/invoice/local/invoices/{invoice_id}/confirm",
                           json=action("confirm", 1, wh.id).model_dump(mode="json"))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["items"][0]["stock_reserved_quantity"] == 3
    invoice = db.get(Invoice, invoice_id)
    with pytest.raises(ValueError, match="本地交易"):
        ensure_mutable(db, invoice)
    with pytest.raises(ValueError, match="入口已停用"):
        sync_invoice(db, invoice)
    from app.invoice import order_sync_execution
    from fastapi import HTTPException
    import httpx
    def forbidden(*args, **kwargs):
        pytest.fail('Local invoice must never reach a legacy provider')
    monkeypatch.setattr(httpx, 'get', forbidden)
    monkeypatch.setattr(httpx, 'post', forbidden)
    db.rollback()
    with pytest.raises(HTTPException) as blocked:
        order_sync_execution.run(db, invoice_id, current, follow_outbound=False)
    assert blocked.value.status_code == 409
    current["roles"], current["permissions"] = [], []
    assert client.post(f"/api/invoice/local/invoices/{invoice_id}/cancel",
                       json=action("cancel", 2).model_dump(mode="json")).status_code == 403


def test_confirmation_rechecks_customer_and_bounds_packaging(db, stock, buyer):
    sku, (wh, _) = stock
    customer, user = buyer
    with pytest.raises(ValueError):
        draft(customer, user, sku, packaging_quantity=2147483648)
    invoice = create_draft(db, draft(customer, user, sku), user)
    customer.identity_status = "disputed"
    db.flush()
    with pytest.raises(ValueError, match="客户身份"):
        confirm(db, invoice.id, action("confirm", 1, wh.id), user)
    assert invoice.commerce_status == "draft"
    assert len(db.scalars(select(InvoiceCommerceEvent)).all()) == 1


def test_catalog_snapshot_keeps_long_model_and_decimal_weight(db, stock, buyer):
    from app.catalog.models import CatalogProduct
    sku, _ = stock
    customer, user = buyer
    db.get(CatalogProduct, sku.product_id).model = "M" * 200
    sku.weight_grams = Decimal("20.000")
    db.flush()
    invoice = create_draft(db, draft(customer, user, sku), user)
    assert invoice.items[0].model == "M" * 200
    assert invoice.items[0].net_weight_grams == "20g"
