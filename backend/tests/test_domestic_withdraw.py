"""Fund/price withdrawal regressions; synthetic SQLite data only."""
from datetime import datetime, timezone
from decimal import Decimal as D
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.domestic import constants as C, order_service, request_service
from app.domestic.models import DomesticCustomerRequest, DomesticCustomerLedger, DomesticOrderItem, DomesticOrder
from app.domestic.router import router
from app.domestic.schemas import FundRequestResubmit, CustomerAdjust, DraftSubmitRequest, OrderItemUpdate
from tests.test_domestic_review_flow import _user, _customer, _pricing_context, _order_payload, _approve


def seed_request(db, kind="recharge"):
    user, reviewer = _user(db, "withdraw-owner"), _user(db, "withdraw-reviewer")
    customer = _customer(db, user, "Withdraw customer", balance=D("300"), membership_level="black")
    if kind == "recharge":
        result = request_service.create_recharge_request(db, customer_id=customer.id, amount=D("500"),
                    voucher_path="original/voucher.png", user_id=user.id, request_id="withdraw-original")
    else:
        result = request_service.create_adjust_request(db, customer.id,
                    CustomerAdjust(amount=20, membership_level="silver", remark="Test adjustment", request_id="withdraw-original"), user.id)
    return user, reviewer, customer, result["id"]


@pytest.mark.parametrize("kind", ["recharge", "adjust"])
def test_withdraw_keeps_funds_and_original_then_replacement_is_approved_once(db, kind):
    user, reviewer, customer, req_id = seed_request(db, kind)
    original = db.get(DomesticCustomerRequest, req_id)
    old_amount, old_remark = original.amount, original.remark
    with pytest.raises(ValueError, match="本人"):
        request_service.withdraw_request(db, req_id, reviewer.id)
    withdrawn = request_service.withdraw_request(db, req_id, user.id)
    assert withdrawn["status"] == "withdrawn" and withdrawn["withdrawn_at"]
    assert request_service.withdraw_request(db, req_id, user.id)["replayed"]
    assert request_service.pending_request_count(db, viewer_user_id=user.id, can_review_all=False) == 0
    with pytest.raises(ValueError, match="待审核"):
        request_service.approve_request(db, req_id, reviewer_id=reviewer.id, can_admin=True)
    assert customer.balance == D("300") and customer.membership_level == "black"
    assert db.query(DomesticCustomerLedger).count() == 0
    payload = FundRequestResubmit(amount=600 if kind == "recharge" else 30, request_id="withdraw-replacement",
                    remark="Updated application", change_membership=kind == "adjust", membership_level="silver" if kind == "adjust" else None)
    new = request_service.resubmit_request(db, req_id, payload, user.id)
    assert new["id"] != req_id and new["status"] == "pending"
    assert original.amount == old_amount and original.remark == old_remark
    assert original.resubmitted_request_id == new["id"] and original.status == "withdrawn"
    assert db.get(DomesticCustomerRequest, new["id"]).voucher_path == ("original/voucher.png" if kind == "recharge" else None)
    assert request_service.resubmit_request(db, req_id, payload, user.id)["replayed"]
    with pytest.raises(ValueError, match="不同"):
        request_service.resubmit_request(db, req_id, payload.model_copy(update={"amount": D("700")}), user.id)
    with pytest.raises(ValueError, match="已重新提交"):
        request_service.resubmit_request(db, req_id, payload.model_copy(update={"request_id": "another-replacement"}), user.id)
    assert db.query(DomesticCustomerLedger).count() == 0
    request_service.approve_request(db, new["id"], reviewer_id=reviewer.id, can_admin=True)
    with pytest.raises(ValueError, match="待审核"):
        request_service.withdraw_request(db, new["id"], user.id)
    request_service.resubmit_request(db, req_id, payload, user.id)
    assert db.query(DomesticCustomerRequest).count() == 2
    assert db.query(DomesticCustomerLedger).filter_by(transaction_type=kind).count() == 1
    assert customer.balance == D("900" if kind == "recharge" else "330")


def test_withdrawn_recharge_validates_money_owner_and_current_customer_scope(db):
    user, reviewer, customer, req_id = seed_request(db)
    request_service.withdraw_request(db, req_id, user.id)
    payload = FundRequestResubmit(amount=0, request_id="resubmit-boundary")
    with pytest.raises(ValueError, match="大于"):
        request_service.resubmit_request(db, req_id, payload, user.id)
    with pytest.raises(ValueError, match="本人"):
        request_service.resubmit_request(db, req_id, payload, reviewer.id)
    customer.owner_user_id = reviewer.id
    db.commit()
    with pytest.raises(ValueError, match="客户不存在"):
        request_service.resubmit_request(db, req_id, payload.model_copy(update={"amount": D("600")}), user.id)
    assert db.query(DomesticCustomerRequest).count() == 1


def test_order_withdraw_edit_resubmit_then_charge_only_updated_price(db):
    user, customer, expected, attrs = _pricing_context(db, "withdraw-price")
    reviewer = _user(db, "price-withdraw-reviewer")
    created = order_service.create_order(db, _order_payload(customer, attrs, expected, "withdraw-price-original", manual=D("880")), user.id)
    original_version = created["review_version"]
    with pytest.raises(ValueError):
        order_service.withdraw_review(db, created["id"], reviewer.id, review_version=db.get(order_service.DomesticOrder, created["id"]).review_version)
    order_service.withdraw_review(db, created["id"], user.id, review_version=db.get(order_service.DomesticOrder, created["id"]).review_version)
    assert customer.balance == D("10000")
    assert db.query(DomesticCustomerLedger).count() == 0
    with pytest.raises(ValueError, match="待审核"):
        _approve(db, created["id"], reviewer)
    item = db.query(DomesticOrderItem).filter_by(order_id=created["id"]).one()
    order_service.update_item(db, item.id, OrderItemUpdate(unit_price=D("800"), order_qty=2), user.id)
    db.refresh(item)
    payload = DraftSubmitRequest.model_validate({"request_id": "withdraw-price-submit", "expected_quotes": [{
        "item_id": item.id, "original_price": item.original_price, "base_price_version": item.base_price_version_snapshot,
        "discount_price": item.unit_price, "membership_level": item.membership_level_snapshot,
        "pricing_rule": item.pricing_rule, "pricing_version": item.pricing_version,
    }]})
    result = order_service.submit_draft(db, created["id"], payload, user.id)
    assert result["status"] == C.ORDER_PENDING_REVIEW
    assert result["review_version"] > original_version
    with pytest.raises(order_service.ReviewVersionConflict):
        order_service.review_order(db, created["id"], decision="approve", remark=None,
                    reviewer_id=reviewer.id, can_admin=False, review_version=original_version)
    with pytest.raises(order_service.ReviewVersionConflict):
        order_service.withdraw_review(db, created["id"], user.id, review_version=original_version)
    assert customer.balance == D("10000") and db.query(DomesticCustomerLedger).count() == 0
    app = FastAPI()
    app.include_router(router, prefix="/api/domestic")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(reviewer.id), "roles": [], "permissions": ["domestic:review"]}
    response = TestClient(app).post(f"/api/domestic/orders/{created['id']}/review", json={"decision": "approve", "review_version": original_version})
    assert response.status_code == 409
    order_service.withdraw_review(db, created["id"], user.id, review_version=result["review_version"])
    with pytest.raises(order_service.ReviewVersionConflict):
        order_service.submit_draft(db, created["id"], payload, user.id)
    order_service.submit_draft(db, created["id"], payload.model_copy(update={"request_id": "withdraw-next-round"}), user.id)
    with pytest.raises(order_service.ReviewVersionConflict):
        order_service.submit_draft(db, created["id"], payload, user.id)
    _approve(db, created["id"], reviewer)
    with pytest.raises(ValueError, match="待审核"):
        order_service.withdraw_review(db, created["id"], user.id, review_version=db.get(order_service.DomesticOrder, created["id"]).review_version)
    assert customer.balance == D("8400")
    assert db.query(DomesticCustomerLedger).count() == 1


@pytest.mark.parametrize("kind", ["recharge", "adjust"])
def test_http_owner_and_multipart_reuse_original_voucher(db, monkeypatch, kind):
    user, reviewer, customer, req_id = seed_request(db, kind)
    app = FastAPI()
    app.include_router(router, prefix="/api/domestic")
    identity = {"sub": str(user.id), "roles": [], "permissions": ["domestic:recharge"]}
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: identity
    client = TestClient(app)
    from unittest.mock import AsyncMock
    from app.domestic import request_notification_service
    monkeypatch.setattr(request_notification_service, "notify_submitted", AsyncMock())
    assert client.post(f"/api/domestic/customer-requests/{req_id}/withdraw").status_code == 200
    body = FundRequestResubmit(amount=550, request_id="http-replacement", remark="Updated application")
    result = client.post(f"/api/domestic/customer-requests/{req_id}/resubmit", data={"data": body.model_dump_json()})
    assert result.status_code == 200
    assert result.json()["data"]["has_voucher"] == (kind == "recharge")
    identity["sub"] = str(reviewer.id)
    assert client.post(f"/api/domestic/customer-requests/{result.json()['data']['id']}/withdraw").status_code == 400
    identity["permissions"] = []
    assert client.post(f"/api/domestic/customer-requests/{req_id}/withdraw").status_code == 403


def test_withdraw_timestamp_uses_beijing_at_utc_midnight(db, monkeypatch):
    from app.core.time import to_beijing_naive
    user, _, _, req_id = seed_request(db)
    monkeypatch.setattr(request_service, "beijing_now", lambda: to_beijing_naive(datetime(2026, 9, 30, 16, 1, tzinfo=timezone.utc)))
    result = request_service.withdraw_request(db, req_id, user.id)
    assert result["withdrawn_at"] == datetime(2026, 10, 1, 0, 1)


def test_review_migration_compiles_for_mysql_and_has_one_head():
    from io import StringIO
    from pathlib import Path
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    root = Path(__file__).parents[1]
    path = root / "alembic/versions/184_domestic_request_withdraw.py"
    spec = importlib.util.spec_from_file_location("withdraw_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = StringIO()
    migration.op = Operations(MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}))
    migration.upgrade()
    sql = output.getvalue()
    assert "withdrawn" in sql and "review_version" in sql and "resubmitted_request_id" in sql
    assert "DELETE" not in sql and "UPDATE" not in sql
    assert ScriptDirectory(str(root / "alembic")).get_heads() == ["196_domestic_commission"]
