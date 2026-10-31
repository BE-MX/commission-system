"""Mixed formal consumers use real isolated rows, identities and source cursors."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.auth.models import ArkUser
from app.catalog.models import CatalogExternalIdentity, CatalogProduct, CatalogSku
from app.commerce_transition.models import PlatformPolicy, ResourceScope
from app.core.time import beijing_now, beijing_today
from app.customer.models import CustomerAccount, CustomerOrder, CustomerOrderItem, CustomerSyncCursor
from app.customer.projection_common import append_raw
from app.inventory.models import StockBalance, Warehouse
from app.invoice.models import Invoice
from app.trade.models import SalesRoster, TradeProjection
from app.trade.query_service import load_orders
from app.trade.refresh_service import projection_status
from app.trade.service import formal_projection_enabled
from tests.test_inventory_local import stock  # noqa: F401 - explicit isolated catalog fixture


@pytest.fixture
def mixed(db):
    db.get(PlatformPolicy, 1).phase = "transition"
    user = ArkUser(username="mixed-seller", real_name="Mixed seller", password_hash="unused")
    customer = CustomerAccount(customer_code="mixed", display_name="Mixed buyer", entity_type="registered_company",
        identity_status="verified", relationship_stage="active_customer", relationship_stage_changed_at=beijing_now(),
        relationship_stage_reason="isolated", record_status="active", identity_confidence=1,
        profile_completeness=100, profile_input_seq=1)
    db.add_all([user, customer]); db.flush()
    db.add(SalesRoster(ark_user_id=user.id, legacy_user_id="old-seller", team="Mixed", active=True, updated_by=user.id))

    def order(key, source="okki", native=False, amount=100):
        invoice = None
        if native:
            invoice = Invoice(invoice_no=key, customer_id="mixed", customer_name="Mixed buyer",
                invoice_date=beijing_today(), transaction_mode="local", commerce_status="confirmed", status="draft", created_by=user.id)
            db.add(invoice); db.flush()
        raw = append_raw(db, source_system=source if source in {"okki", "ark"} else "okki", source_account_key="local" if source == "ark" else "default",
            source_entity_type="order", external_record_id=key, schema_version="isolated_v1", payload={"commercial": {}},
            occurred_at=beijing_now(), captured_at=beijing_now(), sync_cursor=None)
        raw.customer_id = customer.id
        row = CustomerOrder(customer_id=customer.id, source_system=source, source_account_key=raw.source_account_key,
            external_order_id=key, order_no=key, account_date=beijing_today(), amount_usd=amount,
            is_valid_business_order=True, is_new_deal=True, owner_user_id=user.id, source_record_id=raw.id,
            source_hash=raw.content_hash, synced_at=beijing_now(), local_invoice_id=invoice.id if invoice else None)
        db.add(row); db.flush()
        if invoice:
            db.add(TradeProjection(invoice_id=invoice.id, customer_order_id=row.id, invoice_version=invoice.commerce_version,
                finance_event_id=0, aftersales_execution_id=0, content_hash="x" * 64))
        db.flush()
        return row
    return user, customer, order


def cursor(db, scope="default", *, age=0, status="idle"):
    row = CustomerSyncCursor(source_system="okki", resource_type="orders", scope_key=scope,
        sync_status=status, generation=1, last_success_at=beijing_now() - timedelta(hours=age), last_counts_json={})
    db.add(row); db.flush()
    return row


def test_phase_uses_database_and_mix_counts_each_formal_identity_once(db, mixed, monkeypatch):
    user, _, create = mixed
    monkeypatch.setattr("app.trade.service.get_settings", lambda: SimpleNamespace(TRANSACTION_MODE="legacy"))
    create("legacy")
    # A migrated order retains its OKKI identity and gains one local binding.
    migrated = create("migrated", native=True, amount=200)
    create("new-local", source="ark", native=True, amount=300)
    create("shadow", source="shadow", amount=9000)
    create("orphan-ark", source="ark", amount=8000)
    assert formal_projection_enabled(db)
    rows = load_orders(db, owner_ids=[user.id])
    assert {r["order_no"] for r in rows} == {"legacy", "migrated", "new-local"}
    assert sum(r["amount_usd"] for r in rows) == Decimal("600")
    assert next(r for r in rows if r["order_id"] == str(migrated.id))["source"] == "local"
    assert len({r["order_key"] for r in rows}) == 3


def test_missing_or_one_stale_scope_never_looks_current(db, mixed):
    _, _, create = mixed
    create("local", source="ark", native=True)
    state = projection_status(db)
    assert state["pending_count"] == 0 and state["status"] == "incomplete"
    cursor(db, "old-account", age=25)
    cursor(db, "fresh-account")
    state = projection_status(db)
    assert not state["data_complete"]
    assert {s["source"] for s in state["sources"]} == {"legacy", "local"}
    assert state["sources"][0]["scopes"][0]["status"] == "current"  # sorted fresh-account
    db.query(CustomerSyncCursor).filter_by(scope_key="old-account").one().last_success_at = beijing_now()
    db.flush()
    assert projection_status(db)["status"] == "current"


def test_final_rank_and_color_publication_block_on_missing_legacy_source(db, mixed):
    from app.battle_report.statistics import source_orders
    from app.color.local_sales_service import aggregate_sales
    user, _, create = mixed
    create("formal", source="ark", native=True)
    report = SimpleNamespace(start_date=beijing_today(), end_date=beijing_today())
    member = SimpleNamespace(id=1, ark_user_id=user.id, okki_user_id="old-seller", user_name="Seller", team="Mixed")
    rows, issues = source_orders(db, report, [member], beijing_now())
    assert len(rows) == 1 and issues
    assert aggregate_sales(db)["status"] == "pending"


def test_festival_and_intelligence_consume_both_routes(db, mixed):
    from app.festival.local_service import gmv_total
    from app.order_intelligence.service import AnalysisScope, _load_orders
    user, _, create = mixed
    create("legacy", amount=100)
    create("local", source="ark", native=True, amount=200)
    assert gmv_total(db, beijing_today(), beijing_today()) == 300
    rows = _load_orders(db, AnalysisScope("self", str(user.id), None, False), beijing_today(), beijing_today())
    assert sum(r["amount_usd"] for r in rows) == 300


def test_public_inventory_excludes_warehouse_less_mirror_and_unowned_local_bucket(db, mixed, monkeypatch):
    from app.stock.public_service import query_public_inventory
    monkeypatch.setattr("app.stock.public_service.get_settings", lambda: SimpleNamespace(BUSINESS_DB_NAME="lsordertest"))
    db.execute(text("CREATE TABLE lsordertest.okki_products (product_id TEXT, name TEXT, model TEXT, disable_flag INT)"))
    db.execute(text("CREATE TABLE lsordertest.okki_inventory (product_id TEXT, enable_count INT, disable_flag INT)"))
    db.execute(text("INSERT INTO lsordertest.okki_products VALUES ('old-local', 'Hair/18/#1/20g', '', 0), ('old-only', 'Other/20/#2/20g', '', 0)"))
    db.execute(text("INSERT INTO lsordertest.okki_inventory VALUES ('old-local', 999, 0), ('old-only', 3, 0)"))
    product = CatalogProduct(code="M", name="Hair", display_name="Hair", kind="hair")
    db.add(product); db.flush()
    sku = CatalogSku(product_id=product.id, code="M1", color="#1", size="18", unit="piece")
    a, b = Warehouse(code="M-A", name="A"), Warehouse(code="M-B", name="B")
    db.add_all([sku, a, b]); db.flush()
    db.add_all([StockBalance(warehouse_id=a.id, sku_id=sku.id, quality="sellable", on_hand=0, reserved=0),
        StockBalance(warehouse_id=b.id, sku_id=sku.id, quality="sellable", on_hand=100, reserved=0),
        ResourceScope(resource_kind="sku", resource_key=str(sku.id), warehouse_key=str(a.id), route="local", state="active", evidence={"checkpoint": "fixed"}),
        CatalogExternalIdentity(source="okki", tenant="default", external_product_id="old-local", external_sku_id="", sku_id=sku.id)])
    db.flush()
    result = query_public_inventory(db)
    assert result["total"] == 2
    by_id = {r["product_id"]: r for r in result["items"]}
    assert "old-local" not in by_id and by_id["old-only"]["in_stock"]
    assert not by_id[f"ark:sku:{sku.id}"]["in_stock"]
    db.query(StockBalance).filter_by(warehouse_id=a.id).one().on_hand = 1
    db.flush()
    assert query_public_inventory(db, in_stock_only=True)["total"] == 2


def test_pure_modes_keep_single_route_entry_selection(db, mixed):
    policy = db.get(PlatformPolicy, 1)
    policy.phase = "legacy_only"
    assert not formal_projection_enabled(db)
    policy.phase = "local_only"
    db.flush()
    assert formal_projection_enabled(db)
    assert [s["source"] for s in projection_status(db)["sources"]] == ["local"]


def test_missing_installed_policy_cannot_fall_back_to_process_mode(db):
    from app.commerce_transition.service import TransitionError
    db.query(PlatformPolicy).delete()
    db.flush()
    with pytest.raises(TransitionError, match="未安装"):
        formal_projection_enabled(db)


def test_healthy_cursor_for_other_account_does_not_cover_missing_account(db, mixed):
    _, _, create = mixed
    create("legacy-without-cursor")
    cursor(db, "unrelated-account")
    state = projection_status(db)
    assert state["status"] == "incomplete"
    assert any(s["scope"] == "default" and s["status"] == "unknown" for s in state["sources"][0]["scopes"])


def test_mcp_mixed_catalog_deduplicates_mapped_product_and_never_exports_stock(db, mixed, stock, monkeypatch):
    import json
    from app.mcp.price_tools import _find_product
    sku, _ = stock
    db.get(CatalogProduct, sku.product_id).model = "weft"
    db.add(CatalogExternalIdentity(source="okki", tenant="default", external_product_id="mapped",
        external_sku_id="", sku_id=sku.id))
    db.flush()
    monkeypatch.setattr("app.invoice.product_service.match_legacy_product", lambda db, **kwargs: {
        "is_unique": False, "matches": [{"product_id": "mapped", "available_stock": 999},
                                         {"product_id": "other", "available_stock": 5}]})
    result = json.loads(_find_product(db, {"roles": ["super_admin"]}, model="weft", color="black", size="18", unit="piece"))
    assert result["ok"] and not result["is_unique"]
    assert {r["product_id"] for r in result["matches"]} == {f"ark:product:{sku.product_id}", "other"}
    assert all("available_stock" not in r and "stock_warning" not in r for r in result["matches"])


def test_colorwork_availability_ignores_other_unassigned_bucket(db, mixed, stock):
    from app.colorwork.local_service import template_statuses
    sku, (a, b) = stock
    db.add_all([StockBalance(warehouse_id=b.id, sku_id=sku.id, quality="sellable", on_hand=100, reserved=0),
        ResourceScope(resource_kind="sku", resource_key=str(sku.id), warehouse_key=str(a.id), route="local",
            state="active", evidence={"checkpoint": "counted"})])
    db.flush()
    result = template_statuses(db, "isolated", {"prefixes": ["Hair"], "weight": None})
    assert result["statuses"]["black|18"] == "restocking"


def test_transition_projection_scheduler_runs_with_legacy_process_setting(db, mixed, monkeypatch):
    from contextlib import contextmanager
    from app.trade import scheduler
    @contextmanager
    def session():
        yield db
    monkeypatch.setattr(scheduler, "SessionLocal", session)
    monkeypatch.setattr(scheduler, "refresh_orders", lambda **kwargs: {"processed": 1, "failed": 0, "next_after_id": 0})
    assert scheduler.refresh_orders_job()["processed"] == 1


def test_replenishment_sales_map_legacy_units_once_and_exclude_historical_aliases(db, mixed, stock):
    from app.stock.local_query_service import get_sales
    _, _, create = mixed
    sku, _ = stock
    order = create("legacy-stock-sale")
    cursor(db)
    db.add(CatalogExternalIdentity(source="okki", tenant="default", external_product_id="legacy-sku",
        external_sku_id="", sku_id=sku.id))
    for index, role, unit, quantity in [(1, "active", "piece", 7), (2, "historical_alias", "piece", 90),
                                       (3, "active", "kg", 100)]:
        db.add(CustomerOrderItem(order_id=order.id, item_fingerprint=str(index) * 64,
            source_record_id=order.source_record_id, external_product_id="legacy-sku", projection_role=role,
            quantity=quantity, quantity_unit=unit, item_type="bulk"))
    db.flush()
    assert get_sales(db, f"ark:sku:{sku.id}", 30) == 7
