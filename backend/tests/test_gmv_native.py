"""Native department snapshots and daily configuration remain independent of OKKI."""
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock
import pytest
from pydantic import ValidationError
from sqlalchemy import event
from app.auth.models import ArkUser
from app.core.config import get_settings
from app.dingtalk import gmv_daily_config, gmv_daily_service
from app.dingtalk.gmv_daily_schemas import GmvNativeConfigUpdate
from app.dingtalk.models import DingTalkMessageLog
from app.invoice.commerce_service import create_draft, confirm
from app.invoice.models import InvoiceCommerceEvent
from app.system.models import SysDict
from app.trade.department_service import assign_departments
from app.trade.models import SalesRoster
from app.trade.schemas import AttributionWrite, DepartmentShares
from app.trade.projection_service import project_invoice
from tests.test_invoice_commerce import buyer, draft, action
from tests.test_inventory_local import stock


@pytest.fixture
def departments(db, buyer, monkeypatch):
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "local")
    _, seller = buyer
    uid = int(seller["sub"])
    db.get(ArkUser, uid).dingtalk_id = "test-dingtalk"
    other = ArkUser(username="daily-other", real_name="Other", password_hash="unused", dingtalk_id="test-other")
    first, second = [SysDict(type="sales_department", code=code, label=code) for code in ("A", "B")]
    db.add_all([other, first, second])
    db.flush()
    request = GmvNativeConfigUpdate(source="local", teams=[
        {"department_id": first.id, "name": "A", "captain_ark_user_id": uid,
         "members": [{"ark_user_id": uid, "name": "ignored", "exclude_from_total": True}]},
        {"department_id": second.id, "name": "B", "captain_ark_user_id": other.id,
         "members": [{"ark_user_id": other.id, "name": "Other"}]}], admin_recipient_user_ids=[uid])
    saved = gmv_daily_config.save_config(db, request)
    assert saved["teams"][0]["members"][0]["name"] == "Seller"
    return first, second, other


def test_native_split_freezes_names_preserves_decimal_and_recipient_identity(db, stock, buyer, departments):
    first, second, other = departments
    customer, seller = buyer
    sku, _ = stock
    shares = [{"department_id": first.id, "rate": "33.3333"}, {"department_id": second.id, "rate": "66.6667"}]
    invoice = create_draft(db, draft(customer, seller, sku, order_type="production", department_allocations=shares), seller)
    confirm(db, invoice.id, action("department-confirm", 1), seller)
    first.label = "Renamed"
    db.flush()
    assert invoice.local_commercial["departments"][0]["name"] == "A"
    def reject_mirror(conn, cursor, statement, parameters, context, executemany):
        assert "lsordertest" not in statement.lower() and "okki_orders" not in statement.lower()
    event.listen(db.get_bind(), "before_cursor_execute", reject_mirror)
    try:
        pending, _ = gmv_daily_service.build_report(db, date(2026, 10, 3))
        assert "本地订单统计更新中" in pending["fatal_anomalies"]
        project_invoice(db, invoice.id)
        report, config = gmv_daily_service.build_report(db, date(2026, 10, 3))
        assert not report["fatal_anomalies"]
        assert report["company_raw_gmv"] == Decimal("46.04")
        assert report["company_total_gmv"] == Decimal("30.69")
        assert report["teams"][0]["raw_gmv"] == Decimal("15.35")
        assert report["teams"][1]["raw_gmv"] == Decimal("30.69")
        assert config["teams"][0]["captain_ark_user_id"] == int(seller["sub"])
        assert gmv_daily_config.config_options(db)["source"] == "local"
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", reject_mirror)


def test_roster_default_and_explicit_audited_attribution(db, stock, buyer, departments):
    first, second, _ = departments
    customer, seller = buyer
    sku, _ = stock
    uid = int(seller["sub"])
    roster = SalesRoster(ark_user_id=uid, department_id=first.id, updated_by=uid)
    db.add(roster)
    invoice = create_draft(db, draft(customer, seller, sku, order_type="production"), seller)
    confirm(db, invoice.id, action("default-department", 1), seller)
    roster.department_id = second.id
    db.flush()
    assert invoice.local_commercial["departments"] == [{"department_id": first.id, "name": "A", "rate": "100"}]
    body = AttributionWrite(request_key="correct-department", expected_version=2, reason="Verified historical allocation",
        department_allocations=[{"department_id": second.id, "rate": "100"}])
    assign_departments(db, invoice.id, body, seller)
    assign_departments(db, invoice.id, body, seller)
    assert invoice.commerce_version == 3
    record = db.query(InvoiceCommerceEvent).filter_by(request_key="correct-department").one()
    assert record.payload["before_departments"][0]["department_id"] == first.id
    assert record.payload["after_departments"][0]["department_id"] == second.id
    with pytest.raises(ValueError, match="刷新"):
        assign_departments(db, invoice.id, body.model_copy(update={"request_key": "stale"}), seller)
    with pytest.raises(ValidationError, match="100%"):
        DepartmentShares(department_allocations=[{"department_id": first.id, "rate": 99}])


@pytest.mark.asyncio
async def test_pending_daily_cannot_create_outgoing_snapshot_and_native_retry_is_idempotent(db, stock, buyer, departments):
    customer, seller = buyer
    sku, _ = stock
    first, _, _ = departments
    invoice = create_draft(db, draft(customer, seller, sku, order_type="production",
        department_allocations=[{"department_id": first.id, "rate": 100}]), seller)
    confirm(db, invoice.id, action("daily-confirm", 1), seller)
    notifier = AsyncMock()
    notifier.send_to_users.return_value = True
    with pytest.raises(ValueError, match="更新中"):
        await gmv_daily_service.send_daily_report(db, date(2026, 10, 3), notifier=notifier)
    assert not notifier.send_to_users.called and db.query(DingTalkMessageLog).count() == 0
    project_invoice(db, invoice.id)
    await gmv_daily_service.send_daily_report(db, date(2026, 10, 3), notifier=notifier)
    calls = notifier.send_to_users.call_count
    assert calls == 3
    await gmv_daily_service.send_daily_report(db, date(2026, 10, 3), notifier=notifier)
    assert notifier.send_to_users.call_count == calls


@pytest.mark.parametrize("amount", ["0.01", "0.03", "0.04", "123.45"])
def test_department_rounding_never_creates_negative_remainder(amount):
    shares = [{"department_id": index, "rate": 20} for index in range(1, 6)]
    allocations, _, fatal = gmv_daily_service._parse_allocations(Decimal(amount), shares, "split")
    assert not fatal
    assert sum(item["amount"] for item in allocations) == Decimal(amount)
    assert all(item["amount"] >= 0 for item in allocations)


def test_native_gmv_config_route_and_department_permission_contract(db, stock, buyer, departments):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.dingtalk.router import router as dingtalk_router
    from app.trade.router import router as trade_router
    customer, seller = buyer
    first, _, _ = departments
    sku, _ = stock
    invoice = create_draft(db, draft(customer, seller, sku, order_type="production"), seller)
    confirm(db, invoice.id, action("api-confirm", 1), seller)
    db.commit()
    current = {"sub": seller["sub"], "roles": [], "permissions": ["invoice:write"]}
    app = FastAPI()
    app.include_router(dingtalk_router, prefix="/dingtalk")
    app.include_router(trade_router, prefix="/trade")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current
    body = dict(request_key="api-department", expected_version=2, reason="Verified assignment",
        department_allocations=[{"department_id": first.id, "rate": "100"}])
    with TestClient(app) as client:
        assert client.get("/trade/departments").status_code == 200
        assert client.put(f"/trade/invoices/{invoice.id}/departments", json=body).status_code == 403
        current["permissions"] = ["employee:write", "invoice:read_all", "dingtalk:admin"]
        result = client.put(f"/trade/invoices/{invoice.id}/departments", json=body)
        assert result.status_code == 200, result.text
        assert result.json()["data"]["version"] == 3
        assert client.put(f"/trade/invoices/{invoice.id}/departments", json={**body, "request_key": "api-stale"}).status_code == 409
        config = client.get("/dingtalk/gmv-daily/config").json()["data"]["config"]
        request = {key: config[key] for key in ("source", "teams", "admin_recipient_user_ids")}
        request["teams"] = [{key: value for key, value in team.items() if key in {
            "department_id", "name", "captain_ark_user_id", "is_active", "members"}} for team in request["teams"]]
        result = client.put("/dingtalk/gmv-daily/config", json=request)
        assert result.status_code == 200, result.text
        assert result.json()["data"]["source"] == "local"
