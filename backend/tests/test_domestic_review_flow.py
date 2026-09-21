"""内贸审核流：充值/调整申请审核 + 优惠价订单审核。

契约要点：
- 充值必须带凭证（银行流水/转账截图），申请落库为 pending，余额不变；
- 审核通过才入账（账本幂等键沿用 recharge:/adjust: 口径），驳回不动余额；
- 不能审自己提交的申请（admin 兜底除外）；驳回必须填原因；
- 业务订单任一明细成交价偏离系统默认价 → 落待审核（5），不扣款、不能改明细/报工；
  审核通过转生产中（1）并按快照扣款；驳回转已驳回（6），全程无扣款。
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser
from app.core.config import get_settings
from app.core.database import get_db
from app.domestic import (
    balance_service,
    constants as C,
    order_service,
    pricing_service,
    report_service,
    request_service,
)
from app.domestic import models as domestic_models
from app.domestic.models import (
    DomesticBasePrice,
    DomesticCustomer,
    DomesticCustomerLedger,
    DomesticCustomerRequest,
    DomesticOrder,
    DomesticOrderItem,
)
from app.domestic.product_service import find_or_create_product
from app.domestic.schemas import (
    CustomerAdjust,
    DraftSubmitRequest,
    OrderCreate,
    OrderItemAppend,
    OrderItemUpdate,
    ProductAttrs,
)
from app.system.models import SysDict

D = Decimal


def _user(db, name):
    user = ArkUser(username=name, password_hash="x", real_name=name)
    db.add(user)
    db.flush()
    return user


def _customer(db, user, name, **overrides):
    values = {
        "shop_name": name,
        "custom_code": f"C-{name}",
        "created_by": user.id,
        "owner_user_id": user.id,
    }
    values.update(overrides)
    customer = DomesticCustomer(**values)
    db.add(customer)
    db.flush()
    return customer


# ── 充值/调整申请 ────────────────────────────────────


def test_recharge_request_requires_voucher_and_stays_pending_until_approved(db):
    applicant = _user(db, "review-recharge-applicant")
    reviewer = _user(db, "review-recharge-reviewer")
    customer = _customer(db, applicant, "充值审核客户")

    with pytest.raises(ValueError, match="银行流水或转账截图"):
        request_service.create_recharge_request(
            db, customer_id=customer.id, amount=D("10000"), voucher_path="",
            user_id=applicant.id, request_id="recharge-no-voucher",
        )

    created = request_service.create_recharge_request(
        db, customer_id=customer.id, amount=D("10000"), voucher_path="ab/voucher.png",
        user_id=applicant.id, remark="银行转账", request_id="recharge-review-1",
    )
    db.refresh(customer)
    assert created["status"] == "pending"
    assert created["replayed"] is False
    assert customer.balance == D("0.00")
    assert customer.membership_level is None
    assert db.query(DomesticCustomerLedger).count() == 0

    # 同 request_id 同内容重放返回原申请，不重复落库
    replay = request_service.create_recharge_request(
        db, customer_id=customer.id, amount=D("10000"), voucher_path="ab/voucher.png",
        user_id=applicant.id, request_id="recharge-review-1",
    )
    assert replay["replayed"] is True
    assert replay["id"] == created["id"]
    assert db.query(DomesticCustomerRequest).count() == 1

    with pytest.raises(ValueError, match="不同申请内容"):
        request_service.create_recharge_request(
            db, customer_id=customer.id, amount=D("20000"), voucher_path="ab/voucher.png",
            user_id=applicant.id, request_id="recharge-review-1",
        )

    # 跨客户同键同额也不能静默重放到别人的申请上
    other_customer = _customer(db, applicant, "充值审核客户B")
    with pytest.raises(ValueError, match="不同申请内容"):
        request_service.create_recharge_request(
            db, customer_id=other_customer.id, amount=D("10000"), voucher_path="ab/voucher.png",
            user_id=applicant.id, request_id="recharge-review-1",
        )

    approved = request_service.approve_request(
        db, created["id"], reviewer_id=reviewer.id, can_admin=False,
    )
    db.refresh(customer)
    assert approved["request"]["status"] == "approved"
    assert approved["request"]["reviewed_by"] == reviewer.id
    assert customer.balance == D("10000.00")
    assert customer.membership_level == "silver"
    ledger = db.query(DomesticCustomerLedger).one()
    assert ledger.transaction_type == "recharge"
    assert ledger.business_key == f"recharge:{customer.id}:recharge-review-1"
    assert ledger.created_by == applicant.id

    # 重复审核被拒绝；账本只有一行
    with pytest.raises(ValueError, match="已审核过"):
        request_service.approve_request(
            db, created["id"], reviewer_id=reviewer.id, can_admin=False,
        )
    assert db.query(DomesticCustomerLedger).count() == 1


def test_request_review_forbids_self_review_and_reject_requires_reason(db):
    applicant = _user(db, "review-self-applicant")
    customer = _customer(db, applicant, "自审客户")
    created = request_service.create_recharge_request(
        db, customer_id=customer.id, amount=D("5000"), voucher_path="ab/v.png",
        user_id=applicant.id, request_id="self-review-1",
    )

    with pytest.raises(ValueError, match="不能审核自己"):
        request_service.approve_request(
            db, created["id"], reviewer_id=applicant.id, can_admin=False,
        )
    with pytest.raises(ValueError, match="不能审核自己"):
        request_service.reject_request(
            db, created["id"], reviewer_id=applicant.id, can_admin=False,
            remark="自己驳回自己",
        )

    reviewer = _user(db, "review-self-reviewer")
    with pytest.raises(ValueError, match="驳回必须填写原因"):
        request_service.reject_request(
            db, created["id"], reviewer_id=reviewer.id, can_admin=False, remark="短",
        )

    rejected = request_service.reject_request(
        db, created["id"], reviewer_id=reviewer.id, can_admin=False,
        remark="凭证与金额不符",
    )
    db.refresh(customer)
    assert rejected["status"] == "rejected"
    assert rejected["review_remark"] == "凭证与金额不符"
    assert customer.balance == D("0.00")
    assert db.query(DomesticCustomerLedger).count() == 0

    # admin 兜底可以审自己的申请
    own = request_service.create_recharge_request(
        db, customer_id=customer.id, amount=D("5000"), voucher_path="ab/v.png",
        user_id=applicant.id, request_id="self-review-2",
    )
    approved = request_service.approve_request(
        db, own["id"], reviewer_id=applicant.id, can_admin=True,
    )
    assert approved["request"]["status"] == "approved"
    db.refresh(customer)
    assert customer.balance == D("5000.00")


def test_adjust_request_covers_balance_and_level_after_approval(db):
    applicant = _user(db, "review-adjust-applicant")
    reviewer = _user(db, "review-adjust-reviewer")
    customer = _customer(db, applicant, "调整审核客户", balance=D("100.00"))

    created = request_service.create_adjust_request(
        db, customer.id,
        CustomerAdjust(amount=D("50.00"), remark="多扣退回", request_id="adjust-review-1"),
        applicant.id,
    )
    db.refresh(customer)
    assert created["status"] == "pending"
    assert created["request_type"] == "adjust"
    assert customer.balance == D("100.00")

    request_service.approve_request(
        db, created["id"], reviewer_id=reviewer.id, can_admin=False,
    )
    db.refresh(customer)
    assert customer.balance == D("150.00")
    ledger = db.query(DomesticCustomerLedger).one()
    assert ledger.transaction_type == "adjust"
    assert ledger.business_key == f"adjust:{customer.id}:adjust-review-1"

    # 仅调等级：审核通过才覆盖等级并落零金额审计行
    level_only = request_service.create_adjust_request(
        db, customer.id,
        CustomerAdjust(
            amount=D("0"), membership_level="black",
            remark="老板特批黑卡", request_id="adjust-review-2",
        ),
        applicant.id,
    )
    assert level_only["membership_label"] == "黑卡会员"
    db.refresh(customer)
    assert customer.membership_level is None
    request_service.approve_request(
        db, level_only["id"], reviewer_id=reviewer.id, can_admin=False,
    )
    db.refresh(customer)
    assert customer.membership_level == "black"
    audit = db.query(DomesticCustomerLedger).filter_by(
        transaction_type="level_adjust"
    ).one()
    assert audit.amount == D("0")

    # 空调整仍然被拦
    with pytest.raises(ValueError, match="没有需要调整的内容"):
        request_service.create_adjust_request(
            db, customer.id,
            CustomerAdjust(amount=D("0"), remark="空调整", request_id="adjust-review-3"),
            applicant.id,
        )


def test_adjust_approve_fails_when_prepay_balance_insufficient(db):
    applicant = _user(db, "review-adjust-prepay")
    reviewer = _user(db, "review-adjust-prepay-r")
    customer = _customer(
        db, applicant, "负调整客户", balance=D("100.00"), settle_mode="prepay",
    )
    created = request_service.create_adjust_request(
        db, customer.id,
        CustomerAdjust(amount=D("-500.00"), remark="误充追回", request_id="adjust-insufficient"),
        applicant.id,
    )
    with pytest.raises(ValueError, match="余额不足"):
        request_service.approve_request(
            db, created["id"], reviewer_id=reviewer.id, can_admin=False,
        )
    db.refresh(customer)
    row = db.get(DomesticCustomerRequest, created["id"])
    assert customer.balance == D("100.00")
    assert row.status == "pending"  # 执行失败，申请保持待审核


def test_list_requests_scopes_non_reviewer_to_own(db):
    applicant = _user(db, "review-list-a")
    other = _user(db, "review-list-b")
    reviewer = _user(db, "review-list-reviewer")
    customer = _customer(db, applicant, "列表客户")
    other_customer = _customer(db, other, "列表客户B")
    request_service.create_recharge_request(
        db, customer_id=customer.id, amount=D("100"), voucher_path="ab/v.png",
        user_id=applicant.id, request_id="list-scope-1",
    )
    request_service.create_recharge_request(
        db, customer_id=other_customer.id, amount=D("200"), voucher_path="ab/v.png",
        user_id=other.id, request_id="list-scope-2",
    )

    own_items, own_total = request_service.list_requests(
        db, viewer_user_id=applicant.id, can_review_all=False,
    )
    assert own_total == 1
    assert own_items[0]["created_by"] == applicant.id
    assert own_items[0]["customer_name"] == "列表客户"

    all_items, all_total = request_service.list_requests(
        db, viewer_user_id=reviewer.id, can_review_all=True, status="pending",
    )
    assert all_total == 2
    assert {item["created_by_name"] for item in all_items} == {
        "review-list-a", "review-list-b",
    }


def test_recharge_api_requires_voucher_file_and_creates_pending_request(db, tmp_path, monkeypatch):
    from app.domestic.router import router

    monkeypatch.setattr(get_settings(), "DOMESTIC_STORAGE_ROOT", str(tmp_path))
    applicant = _user(db, "review-api-applicant")
    customer = _customer(db, applicant, "接口充值客户")
    db.commit()

    app = FastAPI()
    app.include_router(router, prefix="/api/domestic")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": str(applicant.id),
        "roles": [],
        "permissions": ["domestic:read", "domestic:write", "domestic:recharge"],
    }
    client = TestClient(app)

    missing_file = client.post(
        f"/api/domestic/customers/{customer.id}/recharges",
        data={"amount": "10000", "request_id": "api-review-recharge-1"},
    )
    assert missing_file.status_code == 422

    response = client.post(
        f"/api/domestic/customers/{customer.id}/recharges",
        data={"amount": "10000", "request_id": "api-review-recharge-1", "remark": "银行转账"},
        files={"file": ("voucher.png", b"fake-image-bytes", "image/png")},
    )
    assert response.status_code == 200
    assert response.json()["message"] == "充值申请已提交，审核通过后生效"
    db.refresh(customer)
    assert customer.balance == D("0.00")
    req = db.query(DomesticCustomerRequest).one()
    assert req.voucher_path and req.status == "pending"
    # 凭证落盘且能经鉴权端点读回
    voucher_response = client.get(f"/api/domestic/customer-requests/{req.id}/voucher")
    assert voucher_response.status_code == 200
    assert voucher_response.content == b"fake-image-bytes"

    bad_type = client.post(
        f"/api/domestic/customers/{customer.id}/recharges",
        data={"amount": "100", "request_id": "api-review-recharge-2"},
        files={"file": ("voucher.txt", b"text", "text/plain")},
    )
    assert bad_type.status_code == 400


# ── 优惠价订单审核 ────────────────────────────────────


def _cap_attrs(**overrides):
    values = {
        "product_type": "cap",
        "craft": "递旋",
        "net_color": "自然色",
        "size": "12*14",
        "length": "20厘米",
        "hair_style_series": "标准款",
    }
    values.update(overrides)
    return values


def _seed_order_dicts(db, attrs):
    values = {
        C.ORDER_TYPE_DICT: "first_order",
        C.ORDER_CHANNEL_DICT: "wechat",
    }
    for field, dict_type in C.ATTR_DICTS[attrs["product_type"]].items():
        value = attrs.get(field)
        if value is not None:
            values[dict_type] = value
    for dict_type, code in values.items():
        if not db.query(SysDict.id).filter_by(type=dict_type, code=code).first():
            db.add(SysDict(
                type=dict_type, code=code, label=code, sort=1, is_active=True,
            ))
    db.flush()


def _pricing_context(
    db, suffix, *, membership_level=None, balance="10000.00", original_price="1000.00",
):
    attrs = _cap_attrs()
    user = _user(db, f"review-order-{suffix}")
    customer = _customer(
        db, user, f"审核订单客户-{suffix}",
        membership_level=membership_level, balance=D(balance),
    )
    _seed_order_dicts(db, attrs)
    product = find_or_create_product(db, ProductAttrs.model_validate(attrs))
    key = pricing_service.price_key_for_product(product)
    base = DomesticBasePrice(
        product_type=key[0], craft=key[1], length=key[2],
        original_price=D(original_price), version=1, updated_by=user.id,
    )
    db.add(base)
    db.flush()
    discount = pricing_service.resolve_discount(
        product_type=product.product_type, craft=product.craft, length=product.length,
        original_price=base.original_price, membership_level=membership_level,
    )
    expected = {
        "original_price": discount.original_price,
        "base_price_version": base.version,
        "discount_price": discount.final_price,
        "membership_level": membership_level,
        "pricing_rule": discount.pricing_rule,
        "pricing_version": pricing_service.PRICING_VERSION,
    }
    db.commit()
    return user, customer, expected, attrs


def _order_payload(customer, attrs, expected, request_id, *, is_draft=False, qty=1, manual=None):
    return OrderCreate.model_validate({
        "request_id": request_id,
        "order_no": request_id,
        "order_date": "2026-09-14",
        "required_ship_date": "2026-09-20",
        "customer_id": customer.id,
        "order_category": "normal",
        "order_type": "first_order",
        "order_channel": "wechat",
        "is_draft": is_draft,
        "items": [{
            "client_key": "line-1",
            "attrs": attrs,
            "order_qty": qty,
            "expected_quote": expected,
            "manual_discount_price": manual,
        }],
    })


def _approve(db, order_id, reviewer):
    return order_service.review_order(
        db, order_id, decision="approve", remark=None,
        reviewer_id=reviewer.id, can_admin=False,
    )


def test_discount_order_pends_review_then_approve_charges(db):
    # 非会员默认 1000，手工改成 880 → 待审核
    user, customer, expected, attrs = _pricing_context(
        db, "black-pending", membership_level=None,
    )
    reviewer = _user(db, "review-order-approver")

    created = order_service.create_order(
        db, _order_payload(customer, attrs, expected, "review-order-create-1", qty=2, manual=D("880")), user.id,
    )
    db.refresh(customer)
    order = db.get(DomesticOrder, created["id"])
    assert created["status"] == C.ORDER_PENDING_REVIEW
    assert order.status == C.ORDER_PENDING_REVIEW
    assert order.total_amount == D("1760.00")
    assert order.charged_amount == D("0.00")
    assert customer.balance == D("10000.00")  # 待审核不扣款
    assert db.query(DomesticCustomerLedger).count() == 0

    # 不能审自己的单
    with pytest.raises(ValueError, match="不能审核自己"):
        order_service.review_order(
            db, order.id, decision="approve", remark=None,
            reviewer_id=user.id, can_admin=False,
        )

    result = _approve(db, order.id, reviewer)
    db.refresh(customer)
    db.refresh(order)
    assert result["status"] == C.ORDER_PRODUCING
    assert order.charged_amount == D("1760.00")
    assert customer.balance == D("8240.00")
    ledger = db.query(DomesticCustomerLedger).one()
    assert ledger.transaction_type == "order_charge"
    assert ledger.remark.startswith(f"订单 {order.domestic_no} 审核通过扣款")

    # 已生效的单不能再审
    with pytest.raises(ValueError, match="不在待审核状态"):
        _approve(db, order.id, reviewer)


def test_full_price_order_skips_review(db):
    # 非会员：成交价 = 原始价，无优惠 → 直接生效
    user, customer, expected, attrs = _pricing_context(db, "full-price")
    created = order_service.create_order(
        db, _order_payload(customer, attrs, expected, "review-order-full-1"), user.id,
    )
    db.refresh(customer)
    order = db.get(DomesticOrder, created["id"])
    assert order.status == C.ORDER_PRODUCING
    assert order.charged_amount == D("1000.00")
    assert customer.balance == D("9000.00")


def test_reject_order_leaves_no_charge_and_blocks_resubmit(db):
    user, customer, expected, attrs = _pricing_context(
        db, "reject", membership_level=None,
    )
    reviewer = _user(db, "review-order-rejecter")
    created = order_service.create_order(
        db, _order_payload(customer, attrs, expected, "review-order-reject-1", manual=D("880")), user.id,
    )
    order = db.get(DomesticOrder, created["id"])

    with pytest.raises(ValueError, match="驳回必须填写原因"):
        order_service.review_order(
            db, order.id, decision="reject", remark="", reviewer_id=reviewer.id, can_admin=False,
        )

    result = order_service.review_order(
        db, order.id, decision="reject", remark="优惠价未经同意",
        reviewer_id=reviewer.id, can_admin=False,
    )
    db.refresh(customer)
    db.refresh(order)
    assert result["status"] == C.ORDER_REJECTED
    assert "[审核驳回] 优惠价未经同意" in order.remark
    assert order.charged_amount == D("0.00")
    assert customer.balance == D("10000.00")
    assert db.query(DomesticCustomerLedger).count() == 0

    item = db.query(DomesticOrderItem).filter_by(order_id=order.id).one()
    with pytest.raises(ValueError, match="只有草稿"):
        order_service.submit_draft(
            db, order.id,
            DraftSubmitRequest.model_validate({
                "request_id": "review-order-reject-resubmit",
                "expected_quotes": [{
                    "item_id": item.id,
                    "original_price": item.original_price,
                    "base_price_version": item.base_price_version_snapshot,
                    "discount_price": item.unit_price,
                    "membership_level": item.membership_level_snapshot,
                    "pricing_rule": item.pricing_rule,
                    "pricing_version": item.pricing_version,
                }],
            }),
            user.id,
        )


def test_draft_submit_with_discount_pends_review_until_approved(db):
    user, customer, expected, attrs = _pricing_context(
        db, "draft-review", membership_level=None,
    )
    reviewer = _user(db, "review-draft-approver")
    created = order_service.create_order(
        db, _order_payload(
            customer, attrs, expected, "review-draft-create", is_draft=True, qty=2, manual=D("880"),
        ), user.id,
    )
    order = db.get(DomesticOrder, created["id"])
    item = db.query(DomesticOrderItem).filter_by(order_id=order.id).one()
    assert order.status == C.ORDER_DRAFT  # 草稿不触发审核

    result = order_service.submit_draft(
        db, order.id,
        DraftSubmitRequest.model_validate({
            "request_id": "review-draft-submit",
            "expected_quotes": [{
                "item_id": item.id,
                "original_price": item.original_price,
                "base_price_version": item.base_price_version_snapshot,
                "discount_price": item.unit_price,
                "membership_level": item.membership_level_snapshot,
                "pricing_rule": item.pricing_rule,
                "pricing_version": item.pricing_version,
            }],
        }),
        user.id,
    )
    db.refresh(customer)
    db.refresh(order)
    assert result["status"] == C.ORDER_PENDING_REVIEW
    assert order.charged_amount == D("0.00")
    assert customer.balance == D("10000.00")

    _approve(db, order.id, reviewer)
    db.refresh(customer)
    db.refresh(order)
    assert order.status == C.ORDER_PRODUCING
    assert customer.balance == D("8240.00")


def test_pending_review_order_blocks_mutations_and_scan(db):
    user, customer, expected, attrs = _pricing_context(
        db, "frozen", membership_level=None,
    )
    created = order_service.create_order(
        db, _order_payload(customer, attrs, expected, "review-frozen-1", manual=D("880")), user.id,
    )
    order = db.get(DomesticOrder, created["id"])
    item = db.query(DomesticOrderItem).filter_by(order_id=order.id).one()

    with pytest.raises(ValueError, match="待审核"):
        order_service.update_item(db, item.id, OrderItemUpdate(remark="改备注"), user.id)
    with pytest.raises(ValueError, match="待审核"):
        order_service.delete_item(db, item.id, user.id)
    with pytest.raises(ValueError, match="待审核"):
        order_service.add_item(
            db, order.id,
            OrderItemAppend.model_validate({
                "client_key": "line-2",
                "attrs": attrs, "order_qty": 1, "request_id": "review-frozen-append",
            }),
            user.id,
        )
    scan = report_service.scan_item(db, item.id, user.id)
    assert scan["can_submit"] is False
    assert scan["block_reason"] == report_service.BLOCK_ORDER_REVIEW


def test_approve_fails_and_stays_pending_when_balance_insufficient(db):
    user, customer, expected, attrs = _pricing_context(
        db, "insufficient", membership_level="black", balance="2000.00",
    )
    reviewer = _user(db, "review-insufficient-approver")
    created = order_service.create_order(
        db, _order_payload(customer, attrs, expected, "review-insufficient-1", qty=2, manual=D("800")), user.id,
    )
    # 提交后客户余额被其他业务占用，审核时不够扣
    customer.balance = D("100.00")
    db.commit()

    with pytest.raises(ValueError, match="余额不足"):
        _approve(db, created["id"], reviewer)
    order = db.get(DomesticOrder, created["id"])
    db.refresh(customer)
    assert order.status == C.ORDER_PENDING_REVIEW
    assert order.charged_amount == D("0.00")
    assert customer.balance == D("100.00")
    assert db.query(DomesticCustomerLedger).count() == 0
