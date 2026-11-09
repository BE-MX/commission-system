"""Customer overview keeps distinct customer counts, scoped contact search, and audited evidence."""
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.utils import create_access_token
from app.core.database import get_db
from app.core.time import beijing_now
from app.domestic import constants as order_constants
from app.domestic.models import DomesticOrder
from app.domestic.order_service import terminate_order
from app.domestic_decision.models import DecisionConfig
from app.domestic_followup.collaboration_access import COORDINATE, READ, WRITE
from app.domestic_followup.collaboration_models import (
    FollowupCollaborationEvent, FollowupCollaborator, FollowupCustomerProfile, FollowupHandoff,
    FollowupResponsibility, FollowupScope,
)
from app.domestic_followup.customer_overview import list_customer_overview
from app.domestic_followup.customer_overview_contacts import check_contact_duplicates, update_contact, verify_deal
from app.domestic_followup.customer_overview_router import router
from app.domestic_followup.models import DomesticFollowup
from app.system.models import SysDict
from tests.domestic_followup_helpers import grant, make_customer, make_user

OLD_DATE = date(2020, 1, 2)


def _user(user, *permissions):
    return {"sub": str(user.id), "permissions": [READ, WRITE, *permissions]}


def _order(db, customer, *, kind="business", order_type=None, status=1, amount=100, deleted=0, day=2, charged=0):
    number = f"DF-{customer.id}-{day}-{status}-{amount}-{order_type}-{kind}-{deleted}"
    order = DomesticOrder(
        domestic_no=number[:32], order_no=number[:64], customer_id=customer.id, order_kind=kind,
        order_category="normal" if kind == "business" else None, order_type=order_type,
        order_date=date(2020, 1, day), status=status, total_amount=amount,
        charged_amount=charged, deleted_flag=deleted, created_by=customer.created_by,
    )
    db.add(order)
    return order


def _scope(db, user, customer, actor):
    db.add(FollowupScope(user_id=user.id, customer_id=customer.id, scope_key=f"c:{customer.id}", added_by_user_id=actor.id))


def _item_map(result):
    return {row["id"]: row for row in result["items"]}


def test_deal_evidence_and_counts_follow_customer_grain(db):
    actor = make_user(db, "overview-evidence")
    credit, sample, unknown, historical, verified, conflicting, aftersales, mixed = (
        make_customer(db, actor, name)
        for name in ("Credit", "Sample", "Unknown", "History", "Verified", "Conflict", "Aftersales", "Mixed")
    )
    for customer in (credit, sample, unknown, historical, verified, conflicting, aftersales, mixed):
        customer.province, customer.city = "福建", "泉州"
    credit.lifecycle_status = "潜在"
    _order(db, credit)
    _order(db, credit, day=4)
    _order(db, sample, order_type="sample", status=order_constants.ORDER_SHIPPED)
    _order(db, unknown, order_type="sample", amount=0)
    _order(db, unknown, kind="production", amount=0)
    _order(db, unknown, deleted=1)
    for status in (0, 4, 5, 6):
        _order(db, unknown, status=status)
    unknown.total_order_count = 7  # a bare legacy count is not evidence
    historical.first_order_date = OLD_DATE
    historical.total_order_count = 2
    conflicting.first_order_date = OLD_DATE
    conflicting.last_order_date = date(2019, 12, 3)
    conflicting.total_order_count = 2
    db.add(FollowupCustomerProfile(customer_id=verified.id, deal_status="unwon", deal_evidence="核对纸质台账",
                                   deal_verified_by_user_id=actor.id, deal_verified_at=beijing_now()))
    db.add(DecisionConfig(key="aftersales_order_types", value=["compensation"]))
    db.add(SysDict(type="domestic_order_type", code="rma-only", label="售后订单", sort=10, is_active=False))
    _order(db, aftersales, order_type="compensation")
    _order(db, aftersales, order_type="rma-only")
    _order(db, mixed, order_type="sample", day=2)
    _order(db, mixed, day=4)
    db.flush()

    result = list_customer_overview(db, _user(actor), province="福建", city="泉州")
    items = _item_map(result)
    assert result["counts"] == {"total": 8, "won": 4, "unwon": 1, "unknown": 3, "sample_only": 1}
    assert result["total"] == 8
    assert items[credit.id]["deal_status"] == "won" and items[credit.id]["deal_conflict"]
    assert items[credit.id]["deal_source"] == "system_order"
    assert items[credit.id]["first_deal_date"] == OLD_DATE.isoformat()
    assert items[credit.id]["last_followup_date"] is None  # no followups still included
    assert items[sample.id]["sample_only"] and not items[mixed.id]["sample_only"]
    assert items[mixed.id]["first_deal_date"] == OLD_DATE.isoformat()
    assert items[historical.id]["deal_source"] == "historical_archive"
    assert items[verified.id]["deal_source"] == "manual_verification"
    assert items[conflicting.id]["deal_conflict"] and items[conflicting.id]["deal_status"] == "unknown"
    for row in items.values():
        assert not {"total_amount", "charged_amount", "deal_evidence", "order_id"} & row.keys()
    selected = list_customer_overview(db, _user(actor), province="福建", city="泉州", deal_status="sample_only")
    assert selected["total"] == 1 and set(_item_map(selected)) == {sample.id}
    assert selected["counts"] == result["counts"]
    paged = list_customer_overview(db, _user(actor), page=2, page_size=1)
    assert paged["total"] == 8 and paged["items"][0]["id"] == sample.id


def test_overview_masks_contact_search_summary_and_scope_statistics(db):
    owner, viewer, outsider = (make_user(db, name) for name in ("Owner", "Viewer", "Outsider"))
    grant(db, owner, READ, WRITE)
    grant(db, viewer, READ, WRITE)
    grant(db, outsider, READ, WRITE)
    restricted = make_customer(db, owner, "Shared account")
    restricted.contact, restricted.phone = "Private Name", "123456"
    restricted.province, restricted.city = "广东", "深圳"
    hidden = make_customer(db, owner, "Hidden account")
    hidden.contact, hidden.phone, hidden.province = "Hidden Name", "987654", "隐藏省"
    _scope(db, viewer, restricted, owner)
    _scope(db, owner, restricted, owner)
    db.add(FollowupResponsibility(customer_id=restricted.id, owner_user_id=owner.id, status="handoff"))
    db.add(FollowupCustomerProfile(customer_id=restricted.id, wechat="SecretWX"))
    db.add(FollowupHandoff(
        customer_id=restricted.id, from_user_id=owner.id, requester_user_id=owner.id, recipient_user_id=viewer.id,
        kind="offer", status="pending", responsibility_version=1, reason="next", tasks=[], selected_record_ids=[],
    ))
    for day, status, summary in ((4, "confirmed", "Actual"), (2, "confirmed", "Backfill"), (5, "draft", "Draft")):
        db.add(DomesticFollowup(customer_id=restricted.id, author_user_id=owner.id, status=status,
                                followup_date=date(2020, 1, day), summary=summary,
                                shared_summary="Share only" if day == 4 else None, request_id=f"customer-overview-{day}"))
    db.flush()
    result = list_customer_overview(db, _user(viewer), scope="authorized")
    assert result["total"] == result["counts"]["total"] == 1
    assert result["regions"] == [{"province": "广东", "cities": ["深圳"]}]
    row = result["items"][0]
    assert [row[key] for key in ("contact", "phone", "wechat")] == [None, None, None]
    assert row["last_followup_summary"] == "Share only" and row["last_followup_date"] == "2020-01-04"
    assert row["assignee_name"] == owner.real_name
    assert row["handoff_recipient_name"] == viewer.real_name
    assert result["assignees"] == [{"id": owner.id, "name": owner.real_name}]
    assert not row["can_view_timeline"] and not row["can_record"]
    for keyword in ("Private Name", "123456", "SecretWX", "Hidden account", "987654"):
        assert list_customer_overview(db, _user(viewer), scope="authorized", keyword=keyword)["total"] == 0
    assert list_customer_overview(db, _user(viewer), scope="incoming")["total"] == 1
    assert list_customer_overview(db, _user(outsider), scope="incoming")["total"] == 0
    db.add(FollowupCollaborator(customer_id=restricted.id, user_id=viewer.id, added_by_user_id=owner.id))
    db.flush()
    result = list_customer_overview(db, _user(viewer), scope="collaborating", keyword="SecretWX")
    assert result["total"] == 1 and result["items"][0]["can_view_timeline"] and result["items"][0]["can_record"]
    assert result["items"][0]["last_followup_summary"] == "Actual"


def test_completion_refund_preserves_prior_deal_but_early_termination_does_not(db):
    owner = make_user(db, "RefundOwner")
    completed = make_customer(db, owner, "Completed and refunded")
    early = make_customer(db, owner, "Terminated during production")
    completed_order = _order(db, completed, status=order_constants.ORDER_DONE, charged=100)
    early_order = _order(db, early, status=order_constants.ORDER_PRODUCING, charged=100)
    db.flush()
    terminate_order(db, completed_order.id, "成交后退款", owner.id)
    terminate_order(db, early_order.id, "早期取消", owner.id)
    assert completed_order.status == early_order.status == order_constants.ORDER_TERMINATED
    assert completed_order.charged_amount == early_order.charged_amount == 0

    items = _item_map(list_customer_overview(db, _user(owner)))
    assert items[completed.id]["deal_status"] == "won"
    assert items[early.id]["deal_status"] == "unknown"


def test_contact_duplicates_and_manual_verification_do_not_override_system_orders(db):
    owner, manager, other = (make_user(db, name) for name in ("ContactOwner", "ContactManager", "ContactOther"))
    grant(db, manager, READ, WRITE, COORDINATE)
    customer = make_customer(db, owner, "Contact client")
    duplicate = make_customer(db, other, "Invisible duplicate")
    duplicate.phone = "１３８－００１２－３４５６"
    _scope(db, manager, customer, owner)
    _order(db, customer)
    db.flush()
    hidden = check_contact_duplicates(db, _user(owner), "+86 138-0012-3456", None, duplicate_confirmed=True)
    assert hidden == {"matches": [], "requires_review": True, "blocking": True}
    public = check_contact_duplicates(db, _user(other), "13800123456", None)
    assert public["matches"][0]["id"] == duplicate.id and public["blocking"]
    edited = update_contact(db, _user(manager, COORDINATE), customer.id,
                            {"wechat": "  CustomerWX  ", "province": "广东"}, False)
    assert edited["updated"] and edited["wechat"] == "CustomerWX"
    assert check_contact_duplicates(db, _user(other), None, "customerwx")["matches"] == []
    with pytest.raises(PermissionError):
        verify_deal(db, _user(owner), customer.id, "unwon", "试填")
    result = verify_deal(db, _user(manager, COORDINATE), customer.id, "unwon", "另行核实")
    assert result["verified_by_user_id"] == manager.id
    event = db.query(FollowupCollaborationEvent).filter_by(customer_id=customer.id, action="deal_verified").one()
    assert event.details == {"deal_status": "unwon", "evidence": "另行核实"}
    projected = list_customer_overview(db, _user(manager, COORDINATE), keyword="CustomerWX")["items"][0]
    assert projected["deal_status"] == "won" and projected["deal_conflict"]
    assert projected["can_edit_contact"] and not projected["can_record"]


def test_overview_routes_apply_permission_and_hide_out_of_scope_ids(db):
    owner, shared_viewer = (make_user(db, name) for name in ("RouteOwner", "RouteViewer"))
    grant(db, shared_viewer, READ, WRITE)
    summary = make_customer(db, owner, "Route Shared")
    hidden = make_customer(db, owner, "Route Hidden")
    summary.phone = "55500001"
    _scope(db, shared_viewer, summary, owner)
    db.flush()

    app = FastAPI()
    app.include_router(router, prefix="/api/domestic-followup")
    app.dependency_overrides[get_db] = lambda: db
    root = "/api/domestic-followup"
    token = create_access_token(_user(shared_viewer))
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        response = client.get(f"{root}/customers/{summary.id}/overview")
        assert response.status_code == 200
        row = response.json()["data"]
        assert row["id"] == summary.id and not row["can_view_contacts"] and row["phone"] is None
        hidden_response = client.get(f"{root}/customers/{hidden.id}/overview")
        missing_response = client.get(f"{root}/customers/{hidden.id + 100}/overview")
        assert hidden_response.status_code == missing_response.status_code == 404
        assert hidden_response.json() == missing_response.json()
        assert client.get(f"{root}/customer-overview?scope=wrong").status_code == 422
        assert client.put(f"{root}/customers/{summary.id}/contact", json={"contact": "测试"}).status_code == 403
        assert client.put(f"{root}/customers/{summary.id}/deal-verification",
                          json={"deal_status": "unwon", "evidence": "核实"}).status_code == 403
        client.headers["Authorization"] = f'Bearer {create_access_token({"sub": str(owner.id), "permissions": []})}'
        assert client.get(f"{root}/customer-overview").status_code == 403
