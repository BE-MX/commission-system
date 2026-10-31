"""Local reporting configuration and immutable confirmation-time FX."""
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.finance.models import Currency
from app.trade.models import SalesRoster
from app.trade.router import router
from app.trade.service import freeze_order_fx
from app.invoice.models import Invoice
from tests.test_invoice_commerce import buyer, draft, action
from tests.test_inventory_local import stock, command
from app.invoice.commerce_service import create_draft, confirm
from app.inventory.service import post_document
from app.trade.snapshot_service import build_snapshot
from tests.test_finance_local import finance, order, payment, cmd


def test_native_long_product_display_projects_without_truncating_family(db, stock, buyer):
    from app.catalog.models import CatalogProduct
    from app.customer.models import CustomerOrderItem
    from app.trade.projection_service import project_invoice
    sku, warehouses = stock
    db.get(CatalogProduct, sku.product_id).display_name = 'P'*256
    invoice = create_draft(db, draft(buyer[0], buyer[1], sku, order_type='production'), buyer[1])
    confirm(db, invoice.id, action('long-family-confirm', 1, warehouses[0].id), buyer[1])
    projected = project_invoice(db, invoice.id); db.flush()
    assert invoice.items[0].product_display == 'P'*256
    assert db.query(CustomerOrderItem).filter_by(order_id=projected.id).one().product_family == 'P'*256


def test_roster_native_members_permissions_and_stale_write(db, stock, buyer):
    _, seller = buyer
    uid = int(seller["sub"])
    current = {"sub": str(uid), "roles": [], "permissions": ["employee:read"]}
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current
    db.commit()
    with TestClient(app) as client:
        rows = client.get("/roster").json()["data"]
        member = next(row for row in rows if row["ark_user_id"] == uid)
        assert member["version"] == 0 and not member["configured"]
        body = {"expected_version": 0, "team": "Native", "camp": "A", "amount_target": "125.50"}
        assert client.put(f"/roster/{uid}", json=body).status_code == 403
        current["permissions"] = ["employee:write"]
        result = client.put(f"/roster/{uid}", json=body)
        assert result.status_code == 200, result.text
        assert result.json()["data"]["version"] == 1
        assert client.put(f"/roster/{uid}", json={**body, "team": "stale"}).status_code == 409
        assert db.get(SalesRoster, uid).team == "Native"
        assert client.put(f"/roster/{uid}", json={**body, "expected_version": 1, "legacy_user_id": "other"}).status_code == 422
        assert client.put(f"/roster/{uid}", json={**body, "expected_version": 1, "amount_target": "-1"}).status_code == 422
        result = client.put(f"/roster/{uid}", json={**body, "expected_version": 1, "active": False})
        assert result.status_code == 200 and not result.json()["data"]["active"]


def test_confirmation_freezes_fx_and_commercial_customer_snapshot(db, stock, buyer):
    sku, (wh, _) = stock
    customer, seller = buyer
    customer.primary_country_code = "FR"
    db.add_all([Currency(code="EUR", name="EUR", rate_to_cny=8, active=True),
                Currency(code="USD", name="USD", rate_to_cny=7, active=True)])
    post_document(db, command("fx-stock", "receipt", wh, sku, 5), actor_id=None)
    invoice = create_draft(db, draft(customer, seller, sku, currency="EUR", commercial_source="unknown"), seller)
    confirm(db, invoice.id, action("confirm-fx", 1, wh.id), seller)
    assert invoice.local_rate_to_usd == Decimal("1.14285714")
    assert invoice.local_commercial["country"] == "FR"
    db.get(Currency, "EUR").rate_to_cny = Decimal(9)
    customer.primary_country_code = "US"
    freeze_order_fx(db, invoice)
    assert invoice.local_rate_to_usd == Decimal("1.14285714")
    assert invoice.local_commercial["country"] == "FR"


def test_missing_fx_does_not_confirm_or_reserve(db, stock, buyer):
    sku, (wh, _) = stock
    customer, seller = buyer
    post_document(db, command("missing-fx-stock", "receipt", wh, sku, 5), actor_id=None)
    invoice = create_draft(db, draft(customer, seller, sku, currency="EUR"), seller)
    with pytest.raises(ValueError, match="汇率"):
        confirm(db, invoice.id, action("confirm-fx", 1, wh.id), seller)
    assert db.get(Invoice, invoice.id).commerce_status == "draft"
    assert invoice.items[0].stock_reserved_quantity == 0


def test_commercial_snapshot_distinguishes_cash_reversal_from_credit(db, finance, stock, buyer):
    from app.finance import service
    from app.finance.schemas import AllocationCreate, AdjustmentCreate
    from datetime import date
    customer, seller, bank = finance
    invoice, target = order(db, stock, buyer)
    original = build_snapshot(db, invoice.id)
    assert original["amount_usd"] == "1000.00"
    cash = service.register(db, payment(customer, bank), seller)
    service.confirm(db, cash.id, cmd("confirm-cash", 1), seller)
    receipt = service.allocate(db, cash.id, AllocationCreate(request_key="allocate", expected_version=2,
        invoice_id=invoice.id, receivable_id=target.id, amount=100, business_date=date(2026, 10, 3)), seller)
    service.reverse_allocation(db, receipt.id, cmd("reverse", 1), seller)
    reversed_snapshot = build_snapshot(db, invoice.id)
    assert reversed_snapshot["amount_usd"] == "1000.00"
    assert reversed_snapshot["finance_event_id"] > original["finance_event_id"]
    service.adjust_receivable(db, target.id, AdjustmentCreate(request_key="credit", expected_version=target.version,
        invoice_id=invoice.id, amount=-1000, business_date=date(2026, 10, 3), reason="Cancelled commercial sale"), seller)
    credited = build_snapshot(db, invoice.id)
    assert credited["amount_usd"] == "0.00" and not credited["is_valid_business_order"]
    assert credited["items"][0]["quantity"] == "10"
    assert credited["items"][0]["sku_id"].startswith("ark:")


def test_draft_is_not_a_commercial_fact_and_cancellation_excludes_confirmed_order(db, stock, buyer):
    from app.invoice.commerce_service import cancel
    sku, _ = stock
    customer, seller = buyer
    invoice = create_draft(db, draft(customer, seller, sku, order_type="production"), seller)
    assert build_snapshot(db, invoice.id) is None
    confirm(db, invoice.id, action("confirmed", 1), seller)
    snapshot = build_snapshot(db, invoice.id)
    assert Decimal(snapshot["amount_original"]) == invoice.total_amount - invoice.surcharge_amount
    cancel(db, invoice.id, action("cancelled", 2), seller)
    assert build_snapshot(db, invoice.id)["invalid_reason"] == "cancelled"


def test_native_projection_replays_once_and_cancellation_updates_same_fact(db, stock, buyer):
    from sqlalchemy import select, func
    from app.trade.projection_service import project_invoice
    from app.trade.models import TradeProjection
    from app.customer.models import CustomerOrder, CustomerOrderItem, CustomerSourceRecord, CustomerEvent
    from app.invoice.commerce_service import cancel
    sku, _ = stock
    customer, seller = buyer
    invoice = create_draft(db, draft(customer, seller, sku, order_type="production"), seller)
    assert project_invoice(db, invoice.id) is None
    confirm(db, invoice.id, action("confirmed", 1), seller)
    order = project_invoice(db, invoice.id)
    first_source = order.source_record_id
    assert order.source_system == "ark" and order.customer_id == customer.id
    assert order.is_valid_business_order
    first_count = db.scalar(select(func.count()).select_from(CustomerSourceRecord))
    assert project_invoice(db, invoice.id).id == order.id
    assert db.scalar(select(func.count()).select_from(CustomerSourceRecord)) == first_count
    cancel(db, invoice.id, action("cancelled", 2), seller)
    assert project_invoice(db, invoice.id).id == order.id
    assert order.source_record_id != first_source and not order.is_valid_business_order
    assert db.scalar(select(func.count()).select_from(CustomerOrder)) == 1
    assert db.scalar(select(func.count()).select_from(CustomerOrderItem)) == 1
    assert db.get(TradeProjection, invoice.id).invoice_version == 3
    assert db.scalar(select(CustomerEvent).where(CustomerEvent.event_type == "order.validity_revoked")) is not None


@pytest.mark.parametrize("storage_status", ["merged", "archived"])
def test_projection_after_customer_merge_preserves_storage_and_uses_logical_owner(db, stock, buyer, storage_status):
    from datetime import timedelta
    from app.core.time import beijing_now
    from app.customer.models import CustomerChangeProposal, CustomerSourceRecord
    from app.trade.projection_service import project_invoice
    from tests.test_customer_facts import _customer
    from tests.test_customer_governance_policy import _profile, _digest
    from tests.test_customer_logical_fact_writes import _move
    sku, _ = stock
    storage, seller = buyer
    invoice = create_draft(db, draft(storage, seller, sku, order_type="production"), seller)
    confirm(db, invoice.id, action("confirm-merge", 1), seller)
    order = project_invoice(db, invoice.id)
    target = _customer(db, "native-merged-target")
    target.relationship_stage = "developing"
    profile = _profile(db, storage)
    proposal = CustomerChangeProposal(customer_id=storage.id, target_customer_id=target.id,
        action_type="merge", payload_schema_version="customer_merge_v1", payload_json={},
        profile_version_id=profile.id, evidence_fact_ids=[], risk_level="critical",
        data_classification="restricted_internal", visibility_scope="management", action_hash=_digest("native-merge"),
        status="executed", expires_at=beijing_now() + timedelta(days=1))
    db.add(proposal)
    db.flush()
    _move(db, object_type="order", row=order, storage=storage, target=target, proposal=proposal)
    storage.record_status, storage.merged_into_customer_id = storage_status, target.id if storage_status == "merged" else None
    db.flush()
    projected = project_invoice(db, invoice.id)
    assert projected.id == order.id and projected.customer_id == storage.id
    assert invoice.local_customer_id == storage.id
    assert db.get(CustomerSourceRecord, projected.source_record_id).customer_id == target.id
    assert target.relationship_stage == "active_customer"


def test_projection_failure_keeps_prior_checkpoint_and_source(db, stock, buyer, monkeypatch):
    from app.trade import projection_service
    from app.trade.models import TradeProjection
    sku, _ = stock
    customer, seller = buyer
    invoice = create_draft(db, draft(customer, seller, sku, order_type="production"), seller)
    confirm(db, invoice.id, action("confirm-rollback", 1), seller)
    projected = projection_service.project_invoice(db, invoice.id)
    source_id = projected.source_record_id
    checkpoint_hash = db.get(TradeProjection, invoice.id).content_hash
    invoice.commerce_version += 1
    db.flush()
    def fail(*args):
        raise ValueError("window update failed")
    monkeypatch.setattr(projection_service, "on_order_projected", fail)
    with pytest.raises(ValueError, match="window update failed"):
        projection_service.project_invoice(db, invoice.id)
    assert projected.source_record_id == source_id
    assert db.get(TradeProjection, invoice.id).content_hash == checkpoint_hash


@pytest.mark.parametrize("status", ["partially_shipped", "shipped", "closed"])
def test_fulfillment_remains_commercially_valid(db, stock, buyer, status):
    sku, _ = stock
    customer, seller = buyer
    invoice = create_draft(db, draft(customer, seller, sku, order_type="production"), seller)
    confirm(db, invoice.id, action("confirm-status", 1), seller)
    invoice.commerce_status = status
    db.flush()
    assert build_snapshot(db, invoice.id)["is_valid_business_order"]


def test_contract_freight_credit_reduces_gmv_but_extra_freight_does_not(db, stock, buyer):
    from app.invoice.settlement_models import Receivable
    from sqlalchemy import select
    sku, _ = stock
    customer, seller = buyer
    invoice = create_draft(db, draft(customer, seller, sku, order_type="production", shipping_fee=100), seller)
    confirm(db, invoice.id, action("confirm-freight", 1), seller)
    before = Decimal(build_snapshot(db, invoice.id)["amount_usd"])
    freight = db.scalar(select(Receivable).where(Receivable.invoice_id == invoice.id, Receivable.kind == "freight"))
    freight.adjustment_amount = -25
    db.flush()
    assert Decimal(build_snapshot(db, invoice.id)["amount_usd"]) == before - 25
    # Batch freight is created after contract confirmation and is not GMV.
    freight.settlement_id = 123
    db.flush()
    assert Decimal(build_snapshot(db, invoice.id)["amount_usd"]) == before


def test_dirty_selection_and_worker_checkpoint(db, stock, buyer):
    from sqlalchemy.orm import sessionmaker
    from app.trade.refresh_service import projection_status
    from app.trade.scheduler import refresh_orders
    sku, _ = stock
    customer, seller = buyer
    invoice = create_draft(db, draft(customer, seller, sku, order_type="production"), seller)
    confirm(db, invoice.id, action("confirm-worker", 1), seller)
    db.commit()
    factory = sessionmaker(bind=db.get_bind())
    assert projection_status(db)["pending_count"] == 1
    db.rollback()
    assert refresh_orders(session_factory=factory)["processed"] == 1
    assert projection_status(db)["pending_count"] == 0
    assert refresh_orders(session_factory=factory)["processed"] == 0


def test_worker_rotates_past_failed_batch(db, stock, buyer, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.trade import scheduler
    sku, _ = stock
    customer, seller = buyer
    ids = []
    for index in range(2):
        invoice = create_draft(db, draft(customer, seller, sku, order_type="production", request_key=f"rotate-{index}"), seller)
        confirm(db, invoice.id, action(f"confirm-rotate-{index}", 1), seller)
        ids.append(invoice.id)
    db.commit()
    original = scheduler.project_invoice
    def project(db, invoice_id):
        if invoice_id == ids[0]:
            raise ValueError("incomplete history")
        return original(db, invoice_id)
    monkeypatch.setattr(scheduler, "project_invoice", project)
    factory = sessionmaker(bind=db.get_bind())
    first = scheduler.refresh_orders(session_factory=factory, limit=1)
    assert first["failed"] == 1
    second = scheduler.refresh_orders(session_factory=factory, limit=1, after_id=first["next_after_id"])
    assert second["processed"] == 1


def test_native_watermark_never_advances_okki_and_shows_pending(db, stock, buyer, monkeypatch):
    from app.core.config import get_settings
    from app.core.time import beijing_now
    from app.trade.projection_service import project_invoice
    from app.customer.pcw_order_service import _source_watermarks
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "local")
    sku, _ = stock
    customer, seller = buyer
    invoice = create_draft(db, draft(customer, seller, sku, order_type="production"), seller)
    confirm(db, invoice.id, action("confirm-watermark", 1), seller)
    before = _source_watermarks(db, customer.id, beijing_now())
    assert before[-1]["source"] == "ark" and before[-1]["status"] == "pending"
    project_invoice(db, invoice.id)
    after = _source_watermarks(db, customer.id, beijing_now())
    assert after[-1]["status"] == "fresh"
    assert all(row["synced_through"] is None for row in after if row["source"] == "okki")
    invoice.commerce_version += 1
    db.flush()
    assert _source_watermarks(db, customer.id, beijing_now())[-1]["status"] == "pending"


def test_analysis_native_scope_filters_and_private_exclusion_without_mirror(db, stock, buyer, monkeypatch):
    from datetime import date
    from sqlalchemy import event
    from fastapi import HTTPException
    from app.core.config import get_settings
    from app.order_intelligence import service
    from app.order_intelligence.filtering import AnalysisFilters
    from app.trade.projection_service import project_invoice
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "local")
    service._clear_profile_cache()
    service._clear_filter_cache()
    sku, _ = stock
    customer, seller = buyer
    customer.primary_country_code = "FR"
    for index, private in enumerate((False, True)):
        invoice = create_draft(db, draft(customer, seller, sku, request_key=f"analysis-{index}", order_type="production",
            commercial_source="social_owned", is_new_deal=True, is_private_order=private), seller)
        confirm(db, invoice.id, action(f"confirm-analysis-{index}", 1), seller)
        project_invoice(db, invoice.id)
    def reject_mirror(conn, cursor, statement, parameters, context, executemany):
        assert "lsordertest" not in statement.lower() and "okki_orders" not in statement.lower()
    event.listen(db.get_bind(), "before_cursor_execute", reject_mirror)
    try:
        user = {"sub": seller["sub"], "permissions": ["order_intelligence:read"], "roles": []}
        scope = service.resolve_scope(db, user)
        assert scope.user_id == seller["sub"]
        with pytest.raises(HTTPException) as denied:
            service.resolve_scope(db, user, requested_user_id=str(int(seller["sub"]) + 1))
        assert denied.value.status_code == 403
        rows = service._load_orders(db, scope, filters=AnalysisFilters(countries=("FR",), sources=("social_owned",)))
        assert len(rows) == 1 and rows[0]["new_deal"] == "是"
        assert service._load_orders(db, scope, filters=AnalysisFilters(models=("not-sold",))) == []
        day = date(2026, 10, 3)
        assert service.get_overview(db, scope, day, day)
        assert service.get_country_analysis(db, scope, day, day)
        assert service.get_people_analysis(db, scope, day, day, "person")
        assert service.get_filter_options(db, scope, day, day)["countries"] == ["FR"]
        from app.customer.models import CustomerOrderItem
        for item in db.query(CustomerOrderItem).all():
            item.model, item.color = None, "   "
        db.flush()
        unknown = AnalysisFilters(models=("未知",), colors=("未知",))
        assert len(service._load_orders(db, scope, filters=unknown)) == 1
        products = service._load_product_rows(db, scope, day, day, unknown)
        assert len(products) == 1 and products[0]["filter_model"] == products[0]["color"] == "未知"
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", reject_mirror)


def test_free_sample_counts_but_zero_bulk_and_replacement_do_not(db, stock, buyer):
    from app.aftersales.models import AfterSalesExecution
    from datetime import date
    sku, _ = stock
    customer, seller = buyer
    for kind in ("sample", "bulk"):
        body = draft(customer, seller, sku, request_key=f"free-{kind}", order_type="production", shipping_fee=0, surcharge_amount=0)
        body.items = [body.items[0].model_copy(update={"price_per_piece": Decimal(0), "discount_amount": Decimal(0), "commercial_kind": kind})]
        invoice = create_draft(db, body, seller)
        confirm(db, invoice.id, action(f"confirm-free-{kind}", 1), seller)
        assert build_snapshot(db, invoice.id)["is_valid_business_order"] is (kind == "sample")
        if kind == "sample":
            db.add(AfterSalesExecution(case_id=1, related_invoice_id=invoice.id, action="replacement", quantity=1,
                business_date=date(2026, 10, 3), request_key="free-replacement", request_hash="a" * 64, payload={}, created_by=int(seller["sub"])))
            db.flush()
            assert not build_snapshot(db, invoice.id)["is_valid_business_order"]


def test_festival_native_totals_details_and_permissions_without_mirror(db, stock, buyer, monkeypatch):
    from datetime import date
    from sqlalchemy import event
    from app.core.config import get_settings
    from app.festival import service, order_service, events_service
    from app.trade.projection_service import project_invoice
    from app.trade.roster_service import write_roster
    from app.trade.schemas import RosterWrite
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "local")
    monkeypatch.setattr(service, "ACTIVITY_NEW_SIGN_WINDOW", ("2026-10-03", "2026-10-03"))
    monkeypatch.setattr(service, "ACTIVITY_GMV_WINDOW", ("2026-10-03", "2026-10-03"))
    sku, _ = stock
    customer, seller = buyer
    write_roster(db, int(seller["sub"]), RosterWrite(expected_version=0, team="乘风", new_customer_target=1), seller)
    total = Decimal(0)
    for index in range(2):
        invoice = create_draft(db, draft(customer, seller, sku, request_key=f"festival-{index}", order_type="production",
            commercial_source="social_owned", is_new_deal=True), seller)
        confirm(db, invoice.id, action(f"confirm-festival-{index}", 1), seller)
        total += project_invoice(db, invoice.id).amount_usd
    def reject_mirror(conn, cursor, statement, parameters, context, executemany):
        assert "lsordertest" not in statement.lower()
    event.listen(db.get_bind(), "before_cursor_execute", reject_mirror)
    try:
        scope = order_service.resolve_scope(db, {"sub": seller["sub"], "roles": [], "permissions": []})
        assert scope.mode == "self"
        assert service.get_company_new_total(db, "2026-10-03", "2026-10-03", source="okki") == 1
        assert service.get_gmv_total(db, "2026-10-03", "2026-10-03") == float(total)
        member = service.get_new_sign_board(db, "2026-10-03", "2026-10-03")["items"][0]
        assert member["new_count"] == 1 and member["new_points"] == 1.5
        details = order_service.list_orders(db, "new_sign", scope, 1, 20)
        assert details["total"] == 2 and sum(row["points"] for row in details["items"]) == 1.5
        assert len(service.get_daily_orders(db, date(2026, 10, 3))[seller["sub"]]) == 2
        assert service.get_repurchase_payload(db, "2026-10-03", "2026-10-03")["first_board"][0]["first_count"] == 0
        first = events_service._first_sign_candidate(db, "2026-10-03", "2026-10-03")
        candidates = events_service._new_sign_order_candidates(db, "2026-10-03", "2026-10-03")
        assert len(first) == 1 and len(candidates) == 2
        assert len({row["dedup_key"] for row in candidates}) == 2
        assert candidates == events_service._new_sign_order_candidates(db, "2026-10-03", "2026-10-03")
        assert events_service._deal_candidates(db, "2026-10-03", "2026-10-03") == []
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", reject_mirror)


def test_september_local_history_excludes_old_customer_outside_roster(db, stock, buyer, monkeypatch):
    from datetime import date
    from collections import defaultdict
    from app.auth.models import ArkUser
    from app.core.config import get_settings
    from app.festival import september_service
    from app.trade.projection_service import project_invoice
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "local")
    monkeypatch.setattr(september_service, "START", date(2026, 10, 3))
    sku, _ = stock
    customer, seller = buyer
    retired = ArkUser(username="retired-seller", real_name="Retired", password_hash="unused", is_active=False)
    db.add(retired)
    db.flush()
    for index, day in enumerate((date(2026, 10, 2), date(2026, 10, 3))):
        invoice = create_draft(db, draft(customer, seller, sku, request_key=f"sept-history-{index}",
            invoice_date=day, order_type="production", is_new_deal=True), seller)
        confirm(db, invoice.id, action(f"confirm-sept-history-{index}", 1), seller)
        if index == 0:
            invoice.sales_user_id = retired.id
            db.flush()
        project_invoice(db, invoice.id)
    rows, old = september_service._orders(db, [seller["sub"]], date(2026, 10, 3), defaultdict(int))
    assert len(rows) == 1 and old == {str(customer.id)}


def test_unknown_confirmed_country_remains_unknown_after_customer_edit(db, stock, buyer):
    from app.trade.projection_service import project_invoice
    from app.trade.query_service import load_orders
    sku, _ = stock
    customer, seller = buyer
    customer.primary_country_code = None
    invoice = create_draft(db, draft(customer, seller, sku, order_type="production"), seller)
    confirm(db, invoice.id, action("confirm-unknown-country", 1), seller)
    project_invoice(db, invoice.id)
    customer.primary_country_code = "US"
    db.flush()
    assert load_orders(db)[0]["country"] == "未知"


def test_pending_projection_blocks_festival_event_publication(db, stock, buyer, monkeypatch):
    from app.core.config import get_settings
    from app.festival import service, events_service, notification_service
    from sqlalchemy.orm import sessionmaker
    from datetime import date
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "local")
    sku, _ = stock
    customer, seller = buyer
    invoice = create_draft(db, draft(customer, seller, sku, order_type="production"), seller)
    confirm(db, invoice.id, action("confirm-pending-event", 1), seller)
    db.commit()
    def reject_publication(*args, **kwargs):
        raise AssertionError("pending facts must not publish events")
    monkeypatch.setattr(events_service, "persist_new", reject_publication)
    result = service.get_headline_payload(db, None, None)
    assert result["summary"]["projection_status"]["pending_count"] == 1
    db.rollback()
    monkeypatch.setattr(notification_service, "SessionLocal", sessionmaker(bind=db.get_bind()))
    assert notification_service._daily_claim(date(2026, 10, 3)) is False
