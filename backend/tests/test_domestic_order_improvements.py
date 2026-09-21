from decimal import Decimal as D

import pytest

from app.domestic import constants as C, order_service, request_service
from app.domestic.models import DomesticOrderItem
from app.domestic.schemas import CustomerAdjust, DraftSubmitRequest, OrderItemAppend, OrderItemUpdate, OrderUpdate
from app.system.models import SysDict
from tests.test_domestic_review_flow import _pricing_context, _order_payload, _user


@pytest.mark.parametrize("level", ["silver", "black", "supreme"])
@pytest.mark.parametrize("draft", [False, True])
def test_default_member_price_with_labor_never_requires_review(db, level, draft):
    db.autoflush = False
    user, customer, expected, attrs = _pricing_context(db, f"default-{level}-{draft}", membership_level=level)
    payload = _order_payload(customer, attrs, expected, "default-member-order", is_draft=draft, qty=2)
    payload.items[0].labor_fee = D("25")
    result = order_service.create_order(db, payload, user.id)
    detail = order_service.get_order_detail(db, result["id"])
    total = (expected["discount_price"] + D("25")) * 2
    assert D(str(detail["total_amount"])) == total
    assert not detail["items"][0]["price_changed"]
    if draft:
        result = order_service.submit_draft(db, result["id"], DraftSubmitRequest(
            request_id="default-member-submit", expected_quotes=detail["current_expected_quotes"],
        ), user.id)
    assert result["status"] == C.ORDER_PRODUCING
    db.refresh(customer)
    assert customer.balance == D("10000") - total


@pytest.mark.parametrize("price,changed", [(D("880"), False), (D("800"), True), (D("1000"), True)])
def test_review_compares_default_member_price_in_both_directions(db, price, changed):
    user, customer, expected, attrs = _pricing_context(db, "manual-compare", membership_level="black")
    result = order_service.create_order(db, _order_payload(
        customer, attrs, expected, "compare-manual-price", manual=price,
    ), user.id)
    assert result["status"] == (C.ORDER_PENDING_REVIEW if changed else C.ORDER_PRODUCING)
    detail = order_service.get_order_detail(db, result["id"])
    assert detail["items"][0]["default_discount_price"] == 880
    assert detail["items"][0]["price_changed"] is changed


@pytest.mark.parametrize("draft", [False, True])
def test_zero_sample_price_survives_submit_and_requires_review(db, draft):
    user, customer, expected, attrs = _pricing_context(db, "sample")
    db.add(SysDict(type=C.ORDER_TYPE_DICT, code="sample", label="样单"))
    db.commit()
    payload = _order_payload(customer, attrs, expected, "zero-sample-order", is_draft=draft, manual=D("0"))
    with pytest.raises(ValueError, match="仅样单"):
        order_service.create_order(db, payload, user.id)
    payload.order_type = "sample"
    result = order_service.create_order(db, payload, user.id)
    detail = order_service.get_order_detail(db, result["id"])
    assert detail["total_amount"] == 0
    assert detail["items"][0]["price_changed"]
    if draft:
        with pytest.raises(ValueError, match="零价样单"):
            order_service.update_order(db, result["id"], OrderUpdate(order_type="first_order"), user.id)
        result = order_service.submit_draft(db, result["id"], DraftSubmitRequest(
            request_id="zero-sample-submit", expected_quotes=detail["current_expected_quotes"],
        ), user.id)
    assert result["status"] == C.ORDER_PENDING_REVIEW


def test_recharge_still_overrides_manually_approved_membership(db):
    db.autoflush = False
    user, customer, _, _ = _pricing_context(db, "membership-reset")
    reviewer = _user(db, "membership-reset-reviewer")
    db.commit()
    req = request_service.create_adjust_request(db, customer.id, CustomerAdjust(
        amount=0, membership_level="black", remark="人工调整", request_id="manual-membership-black",
    ), user.id)
    request_service.approve_request(db, req["id"], reviewer_id=reviewer.id, can_admin=False)
    db.refresh(customer)
    assert customer.membership_level == "black"
    recharge = request_service.create_recharge_request(
        db, customer_id=customer.id, amount=D("2994"), voucher_path="test/voucher.png",
        user_id=user.id, request_id="small-recharge-reset",
    )
    request_service.approve_request(db, recharge["id"], reviewer_id=reviewer.id, can_admin=False)
    db.refresh(customer)
    assert customer.membership_level is None


@pytest.mark.parametrize("draft", [False, True])
def test_sample_zero_edit_and_append_only_allowed_before_review(db, draft):
    user, customer, expected, attrs = _pricing_context(db, "sample-edit")
    db.add(SysDict(type=C.ORDER_TYPE_DICT, code="sample", label="样单"))
    db.commit()
    payload = _order_payload(customer, attrs, expected, "sample-edit-order", is_draft=draft)
    payload.order_type = "sample"
    created = order_service.create_order(db, payload, user.id)
    item = db.query(DomesticOrderItem).filter_by(order_id=created["id"]).one()
    item_id = item.id
    append = OrderItemAppend.model_validate({
        "request_id": "sample-append-zero", "client_key": "second", "attrs": attrs, "order_qty": 1,
        "expected_quote": expected, "manual_discount_price": 0,
    })
    if not draft:
        with pytest.raises(ValueError, match="零价样单"):
            order_service.update_item(db, item_id, OrderItemUpdate(unit_price=0), user.id)
        with pytest.raises(ValueError, match="零价样单"):
            order_service.add_item(db, created["id"], append, user.id)
        return
    order_service.update_item(db, item_id, OrderItemUpdate(unit_price=0), user.id)
    order_service.add_item(db, created["id"], append, user.id)
    detail = order_service.get_order_detail(db, created["id"])
    assert len(detail["items"]) == 2
    assert detail["total_amount"] == 0
    result = order_service.submit_draft(db, created["id"], DraftSubmitRequest(
        request_id="sample-edited-submit", expected_quotes=detail["current_expected_quotes"],
    ), user.id)
    assert result["status"] == C.ORDER_PENDING_REVIEW
    reviewer = _user(db, "sample-zero-approver")
    db.commit()
    approved = order_service.review_order(db, created["id"], decision="approve", remark=None,
                                         reviewer_id=reviewer.id, can_admin=False)
    assert approved["status"] == C.ORDER_PRODUCING
    assert approved["charged_amount"] == 0
