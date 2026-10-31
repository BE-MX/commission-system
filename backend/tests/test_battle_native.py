"""Native battle participants and scoped facts require no external binding."""
from datetime import date, datetime
from decimal import Decimal
import pytest
from fastapi import HTTPException
from sqlalchemy import event
from app.auth.models import ArkUser
from app.battle_report import query_service, service, poster_service
from app.battle_report.access import bound_accounts
from app.battle_report.models import BattleReport, BattleReportMember
from app.battle_report.schemas import ReportInput, StateChange
from app.core.config import get_settings
from app.invoice.commerce_service import create_draft, confirm, cancel
from app.trade.projection_service import project_invoice
from tests.test_invoice_commerce import buyer, draft, action
from tests.test_inventory_local import stock


def test_native_roster_scope_refresh_and_poster_gate(db, stock, buyer, monkeypatch):
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "local")
    now = datetime(2026, 10, 3, 12)
    monkeypatch.setattr(query_service, "beijing_now", lambda: now)
    monkeypatch.setattr(service, "beijing_now", lambda: now)
    customer, seller = buyer
    sku, _ = stock
    colleague = ArkUser(username="native-colleague", real_name="Colleague", password_hash="unused")
    db.add(colleague)
    db.flush()
    uid = int(seller["sub"])
    admin = {"sub": seller["sub"], "roles": ["super_admin"]}
    me = {"sub": seller["sub"], "roles": [], "permissions": ["battle_report:read"]}
    def reject_mirror(conn, cursor, statement, parameters, context, executemany):
        assert "lsordertest" not in statement.lower() and "okki_orders" not in statement.lower()
    event.listen(db.get_bind(), "before_cursor_execute", reject_mirror)
    try:
        assert {uid, colleague.id} <= {r["ark_user_id"] for r in bound_accounts(db)}
        payload = ReportInput(name="Native", start_date=date(2026, 10, 3), end_date=date(2026, 10, 4),
            target_deadline=datetime(2026, 10, 4, 12), members=[
                {"ark_user_id": uid, "team": "A"}, {"ark_user_id": colleague.id, "team": "B"}])
        result = service.create_report(db, admin, payload)
        rid = result["id"]
        service.change_state(db, rid, admin, StateChange(action="publish", version=1))
        report = db.get(BattleReport, rid)
        members = db.query(BattleReportMember).filter_by(report_id=rid).all()
        assert all(m.okki_user_id is None for m in members)
        report.work_dates = ["2026-10-03", "2026-10-04"]
        for member in members:
            member.target_usd = Decimal(100)
        db.flush()
        invoice = create_draft(db, draft(customer, seller, sku, order_type="production"), seller)
        confirm(db, invoice.id, action("native-battle-confirm", 1), seller)
        pending = query_service.get_overview(db, rid, me)
        assert pending["summary"]["data_complete"] is False
        with pytest.raises(HTTPException) as blocked:
            poster_service.build_snapshot(db, report, members, now)
        assert blocked.value.status_code == 422
        fact = project_invoice(db, invoice.id)
        data = query_service.get_overview(db, rid, me)
        assert data["summary"]["gmv"] == "46.04" and data["summary"]["data_complete"]
        assert data["projection_status"]["status"] == "current"
        assert data["source_synced_at"]
        assert query_service.list_orders(db, rid, me)["items"][0]["order_id"] == f"ark:customer_order:{fact.id}"
        other = next(m for m in members if m.ark_user_id == colleague.id)
        with pytest.raises(HTTPException) as denied:
            query_service.list_orders(db, rid, me, member_id=other.id)
        assert denied.value.status_code == 403
        assert poster_service.build_snapshot(db, report, members, now)["summary"]["gmv"] == "46.04"
        cancel(db, invoice.id, action("native-battle-cancel", 2), seller)
        assert not query_service.list_orders(db, rid, me)["data_complete"]
        project_invoice(db, invoice.id)
        assert query_service.list_orders(db, rid, me)["total"] == 0
        db.get(ArkUser, uid).is_active = False
        db.flush()
        with pytest.raises(HTTPException) as disabled:
            query_service.get_overview(db, rid, me)
        assert disabled.value.status_code == 422
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", reject_mirror)


def test_pending_report_scope_covers_old_and_new_fact_without_unrelated_orders(db, stock, buyer):
    from app.trade.refresh_service import projection_status
    customer, seller = buyer
    sku, _ = stock
    invoice = create_draft(db, draft(customer, seller, sku, order_type="production"), seller)
    confirm(db, invoice.id, action("scoped-confirm", 1), seller)
    uid = int(seller["sub"])
    scope = dict(owner_ids=[uid], date_from=date(2026, 10, 3), date_to=date(2026, 10, 3))
    assert projection_status(db, **scope)["pending_count"] == 1
    assert projection_status(db, **{**scope, "owner_ids": [uid + 100]})["pending_count"] == 0
    assert projection_status(db, **{**scope, "date_from": date(2026, 10, 4)})["pending_count"] == 0
    project_invoice(db, invoice.id)
    invoice.sales_user_id = None
    invoice.invoice_date = date(2026, 10, 2)
    invoice.commerce_version += 1
    db.flush()
    assert projection_status(db, **scope)["pending_count"] == 1
    project_invoice(db, invoice.id)
    assert projection_status(db, **scope)["pending_count"] == 0
