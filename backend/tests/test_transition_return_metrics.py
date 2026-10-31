"""Main's frozen return effects remain visible after enabling both routes."""
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app.battle_report.award_statistics import calculate, source_facts
from app.battle_report.statistics import source_orders, summarize
from app.core.config import get_settings
from app.dingtalk import gmv_daily_config, gmv_daily_service
from app.festival import local_service
from app.trade.models import SalesRoster
from app.trade.return_adjustments import load_return_adjustments
from tests.test_inventory_local import stock
from tests.test_invoice_commerce import buyer
from tests.test_sales_return_metrics import effect


@pytest.fixture
def historical_owner(db, stock, buyer):
    uid = int(buyer[1]["sub"])
    db.add(SalesRoster(ark_user_id=uid, legacy_user_id="old-A", team="Original", updated_by=uid))
    db.flush()
    return SimpleNamespace(id=1, okki_user_id="old-A", ark_user_id=uid,
        user_name="Seller", team="Original", target_usd=100, is_captain=False)


def test_local_reports_keep_prior_period_return_without_new_orders(db, historical_owner):
    effect(db, 1, role="new_sign")
    effect(db, 2, amount="-70", role="repeat")
    report = SimpleNamespace(start_date=date(2026, 10, 1), end_date=date(2026, 10, 31),
        award_rules={}, award_kind="new_sign_pk")
    now = datetime(2026, 10, 30)
    rows, issues = source_orders(db, report, [historical_owner], now)
    summary = summarize([historical_owner], rows, issues)
    assert summary["gmv"] == "-270.00" and summary["order_count"] == 0
    raw, stamp = source_facts(db, report, [historical_owner], now)
    person = calculate(report, [historical_owner], raw, now, stamp, native=True)["people"][0]
    assert person["new_amount"] == "-200.00" and person["repeat_amount"] == "-70.00"
    assert person["new_count"] == person["repeat_count"] == person["repeat_orders"] == 0
    assert local_service.gmv_total(db, report.start_date, report.end_date) == -270
    assert local_service.company_new_total(db, report.start_date, report.end_date) == 0
    stats = local_service.repurchase_stats(db, report.start_date, report.end_date)
    assert stats[str(historical_owner.ark_user_id)] == {"first_count": 0, "re_amount": -70}


def test_unmapped_numeric_owner_never_collides_with_ark_and_reversal_is_dated(db, historical_owner):
    uid = str(historical_owner.ark_user_id)
    effect(db, 1, owner=uid)
    effect(db, 1, owner=uid, amount="200", day=date(2026, 11, 1), kind="reverse")
    assert load_return_adjustments(db, "2026-10-01", "2026-10-31", owner_ids=[uid]) == []
    facts = load_return_adjustments(db, "2026-10-01", "2026-10-31")
    assert facts[0]["owner"] == f"okki:user:{uid}"
    assert sum(f["amount"] for f in facts) == -200
    assert sum(f["amount"] for f in load_return_adjustments(db, "2026-10-01", "2026-11-30")) == 0


def test_daily_uses_persistent_phase_and_refuses_unmapped_department_collision(db, historical_owner, monkeypatch):
    # Environment remains old while persistent routing already changed.
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "legacy")
    effect(db, 1)
    def no_mirror(conn, cursor, statement, parameters, context, executemany):
        assert "lsordertest" not in statement.lower()
    event.listen(db.get_bind(), "before_cursor_execute", no_mirror)
    try:
        assert gmv_daily_config.load_config(db)["source"] == "local"
        facts = gmv_daily_service.load_valid_orders(db, date(2026, 10, 1))
        assert facts[0]["user_id"] == str(historical_owner.ark_user_id)
        assert facts[0]["departments"] == []
        totals = gmv_daily_service.calculate_report(date(2026, 10, 1), {"source": "local", "teams": []}, facts)
        assert totals["company_return_adjustment_gmv"] == Decimal(-200)
        assert totals["fatal_anomalies"]  # Do not interpret old department 1 as Ark department 1.
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", no_mirror)


def test_legacy_order_mapping_keeps_frozen_seller_after_handover(db, stock, buyer, historical_owner, monkeypatch):
    from app.invoice.commerce_service import create_draft, confirm
    from app.trade.projection_service import project_invoice
    from tests.test_invoice_commerce import draft, action
    customer, seller = buyer
    invoice = create_draft(db, draft(customer, seller, stock[0], order_type="production"), seller)
    confirm(db, invoice.id, action("metrics-confirm", 1), seller)
    order = project_invoice(db, invoice.id)
    order.source_system, order.source_account_key, order.external_order_id = "okki", "reviewed-tenant", "old-1"
    order.owner_user_id = None  # Current owner cannot rewrite the frozen return seller.
    order.is_valid_business_order = False  # A later cancellation cannot erase a return.
    effect(db, 1)
    db.flush()
    monkeypatch.setattr(get_settings(), "PORTAL_OKKI_NAMESPACE", "reviewed-tenant")
    fact = load_return_adjustments(db, "2026-10-01", "2026-10-31")[0]
    assert fact["local_order_id"] == str(order.id) and fact["company_id"] == str(customer.id)
    assert fact["owner"] == str(historical_owner.ark_user_id)
    from app.order_intelligence.service import get_overview, AnalysisScope
    from app.order_intelligence.filtering import AnalysisFilters
    original = get_overview(db, AnalysisScope("all", None, "Original", True),
        date(2026, 10, 1), date(2026, 10, 31),
        analysis_filters=AnalysisFilters(sources=(order.source_category or "unknown",)))
    assert original["metrics"]["return_adjustment_gmv_usd"] == -200
    assert original["metrics"]["net_gmv_usd"] == -200
    other = get_overview(db, AnalysisScope("all", None, "Different", True),
        date(2026, 10, 1), date(2026, 10, 31))
    assert other["metrics"]["return_adjustment_gmv_usd"] == 0
    monkeypatch.setattr(get_settings(), "PORTAL_OKKI_NAMESPACE", "different-tenant")
    unknown = load_return_adjustments(db, "2026-10-01", "2026-10-31")[0]
    assert unknown["local_order_id"] is None and unknown["company_id"].startswith("okki:customer:")


def test_big_deal_threshold_uses_returned_value_once(db, historical_owner, monkeypatch):
    from app.festival.events_service import _deal_candidates
    effect(db, 1, amount="-2000")
    monkeypatch.setattr(local_service, "orders", lambda *a, **kw: [{
        "amount_usd": Decimal(6000), "event_order_id": "old-1",
        "user_id": str(historical_owner.ark_user_id), "user_name": "Seller"}])
    assert _deal_candidates(db, "2026-10-01", "2026-10-31") == []
