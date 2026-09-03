"""内贸优化：草稿/余额/金额/逐件二维码/客户进度工序显隐。"""

import asyncio
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker

from app.auth.models import ArkPermission, ArkRole, ArkUser
from app.domestic import (
    balance_service,
    customer_service,
    order_service,
    pricing_service,
    progress_service,
    report_service,
    unit_service,
)
from app.domestic import constants as C
from app.domestic.models import (
    DomesticCraftRoute,
    DomesticBasePrice,
    DomesticCustomer,
    DomesticCustomerLedger,
    DomesticItemUnit,
    DomesticOrder,
    DomesticOrderItem,
    DomesticReportLog,
)
from app.domestic.schemas import (
    CustomerAdjust,
    CustomerCreate,
    CustomerUpdate,
    DraftSubmitRequest,
    OrderCreate,
    OrderItemAppend,
    OrderItemInput,
    OrderItemUpdate,
    ProductAttrs,
)
from app.mini.schemas import DomesticSubmitRequest
from app.production.models import Process, ProcessRoute, ProcessRouteStep, UserProcessBinding
from app.system.models import SysDict


def _user(db, username):
    user = ArkUser(username=username, password_hash="x", real_name=username)
    db.add(user)
    db.flush()
    return user


def _customer(db, user, name="余额客户"):
    return customer_service.create_customer(
        db,
        CustomerCreate(
            shop_name=name,
            custom_code=f"C-{name}",
            province="山东省",
            city="青岛市",
        ),
        user.id,
    )


def _attrs():
    return ProductAttrs(
        product_type="cap",
        craft="逐件工艺",
        net_color="呼吸红",
        size="S",
        length="15厘米",
        density="65%",
        hair_style_series="直发",
    )


def _seed_order_values(db):
    attrs = _attrs()
    values = {
        C.ORDER_TYPE_DICT: "first_order",
        C.ORDER_CHANNEL_DICT: "wechat",
    }
    for field, dict_type in C.ATTR_DICTS[attrs.product_type].items():
        value = getattr(attrs, field)
        if value is not None:
            values[dict_type] = value
    for dict_type, code in values.items():
        if not db.query(SysDict.id).filter_by(type=dict_type, code=code).first():
            db.add(SysDict(type=dict_type, code=code, label=code, sort=1, is_active=True))
    db.flush()


def _route_and_workers(db):
    _seed_order_values(db)
    route = ProcessRoute(name="逐件路线", status=1)
    db.add(route)
    db.flush()
    workers = []
    for index, name in enumerate(("制网", "钩织", "定型"), start=1):
        process = Process(
            name=f"逐件{name}", sort_order=index, status=1,
            show_in_domestic_track=0 if index == 2 else 1,
        )
        db.add(process)
        db.flush()
        db.add(ProcessRouteStep(route_id=route.id, process_id=process.id, step_order=index))
        worker = _user(db, f"unit-worker-{index}")
        db.add(UserProcessBinding(user_id=worker.id, process_id=process.id))
        workers.append(worker)
    db.add(DomesticCraftRoute(product_type="cap", craft="逐件工艺", route_id=route.id))
    db.flush()
    return route, workers


def _expected_for_price(db, customer, attrs, price):
    price = Decimal(price)
    customer.membership_level = "black"
    original = price + Decimal("120.00")
    row = db.query(DomesticBasePrice).filter_by(
        product_type=attrs.product_type,
        craft=attrs.craft,
        length=attrs.length,
    ).first()
    if row is None:
        row = DomesticBasePrice(
            product_type=attrs.product_type,
            craft=attrs.craft,
            length=attrs.length,
            original_price=original,
            version=1,
        )
        db.add(row)
    elif row.original_price != original:
        row.original_price = original
        row.version += 1
    db.flush()
    return {
        "original_price": original,
        "base_price_version": row.version,
        "discount_price": price,
        "membership_level": "black",
        "pricing_rule": "member_reduction",
        "pricing_version": pricing_service.PRICING_VERSION,
    }


def _priced_item(db, customer, *, qty, price, request_id=None):
    attrs = _attrs()
    values = {
        "client_key": f"line-{request_id or qty}-{price}",
        "attrs": attrs,
        "order_qty": qty,
        "expected_quote": _expected_for_price(db, customer, attrs, price),
    }
    if request_id is None:
        return OrderItemInput(**values)
    return OrderItemAppend(request_id=request_id, **values)


def _create_order(db, creator, customer, *, qty=5, price="10.00", is_draft=False):
    return order_service.create_order(
        db,
        OrderCreate(
            request_id=str(uuid4()),
            order_no="OPT-001",
            order_date=date(2026, 8, 17),
            required_ship_date=date(2026, 8, 24),
            customer_id=customer.id,
            order_category="normal",
            order_type="first_order",
            order_channel="wechat",
            is_draft=is_draft,
            items=[_priced_item(db, customer, qty=qty, price=price)],
        ),
        creator.id,
    )


def _item(db, order_id):
    return db.query(DomesticOrderItem).filter(DomesticOrderItem.order_id == order_id).one()


def _steps(db, item):
    return progress_service.build_progress_view(db, item)


def test_customer_profile_and_recharge_idempotency(db):
    operator = _user(db, "cashier")
    customer = _customer(db, operator)

    first = balance_service.recharge_customer(
        db, customer_id=customer.id, amount=Decimal("500.00"),
        user_id=operator.id, remark="首次充值", request_id="same-request",
    )
    replay = balance_service.recharge_customer(
        db, customer_id=customer.id, amount=Decimal("500.00"),
        user_id=operator.id, remark="弱网重试", request_id="same-request",
    )

    db.refresh(customer)
    assert customer.custom_code == "C-余额客户"
    assert customer.membership_level is None
    assert (customer.province, customer.city) == ("山东省", "青岛市")
    assert customer.balance == Decimal("500.00")
    assert replay["ledger_id"] == first["ledger_id"]
    assert replay["replayed"] is True
    assert db.query(DomesticCustomerLedger).count() == 1
    with pytest.raises(ValueError, match="不同金额"):
        balance_service.recharge_customer(
            db, customer_id=customer.id, amount=Decimal("600.00"),
            user_id=operator.id, request_id="same-request",
        )


def test_balance_lock_refreshes_preloaded_customer_identity(db, engine):
    operator = _user(db, "identity-cashier")
    customer = _customer(db, operator, "并发余额客户")
    balance_service.recharge_customer(
        db, customer_id=customer.id, amount=Decimal("100.00"), user_id=operator.id,
        request_id="identity-balance-recharge",
    )
    Session = sessionmaker(bind=engine)
    stale = Session()
    concurrent = Session()
    fresh = Session()
    try:
        preloaded = stale.query(DomesticCustomer).filter(
            DomesticCustomer.id == customer.id
        ).one()
        assert preloaded.balance == Decimal("100.00")

        concurrent_customer = concurrent.query(DomesticCustomer).filter(
            DomesticCustomer.id == customer.id
        ).one()
        concurrent_customer.balance = Decimal("200.00")
        concurrent.commit()

        balance_service.apply_balance_change(
            stale, customer_id=customer.id, amount=Decimal("-20.00"),
            transaction_type="order_adjustment", user_id=operator.id,
        )
        stale.commit()
        assert fresh.query(DomesticCustomer.balance).filter(
            DomesticCustomer.id == customer.id
        ).scalar() == Decimal("180.00")
    finally:
        stale.close()
        concurrent.close()
        fresh.close()


def test_customer_custom_code_is_unique_on_update(db):
    operator = _user(db, "profile-admin")
    first = _customer(db, operator, "甲店")
    second = _customer(db, operator, "乙店")

    with pytest.raises(ValueError, match="客户编码"):
        customer_service.update_customer(
            db, second.id, CustomerUpdate(custom_code=first.custom_code)
        )


def test_recharged_customer_cannot_be_deleted(db):
    operator = _user(db, "delete-cashier")
    customer = _customer(db, operator, "已充值客户")
    balance_service.recharge_customer(
        db, customer_id=customer.id, amount=Decimal("20.00"), user_id=operator.id,
        request_id="delete-ledger-recharge",
    )

    with pytest.raises(ValueError, match="资金流水"):
        customer_service.delete_customer(db, customer.id)
    assert db.query(DomesticCustomer).filter(DomesticCustomer.id == customer.id).count() == 1


def test_draft_does_not_charge_until_submit(db):
    _route_and_workers(db)
    creator = _user(db, "draft-planner")
    customer = _customer(db, creator, "草稿客户")
    balance_service.recharge_customer(
        db, customer_id=customer.id, amount=Decimal("100.00"), user_id=creator.id,
        request_id="draft-order-recharge",
    )

    created = _create_order(db, creator, customer, qty=3, price="15.00", is_draft=True)
    db.refresh(customer)
    order = db.query(DomesticOrder).get(created["id"])
    assert order.status == C.ORDER_DRAFT
    assert order.total_amount == Decimal("45.00")
    assert order.charged_amount == Decimal("0.00")
    assert customer.balance == Decimal("100.00")

    item = db.query(DomesticOrderItem).filter_by(order_id=order.id).one()
    quote = {
        "item_id": item.id,
        "original_price": item.original_price,
        "base_price_version": item.base_price_version_snapshot,
        "discount_price": item.unit_price,
        "membership_level": item.membership_level_snapshot,
        "pricing_rule": item.pricing_rule,
        "pricing_version": item.pricing_version,
    }
    payload = DraftSubmitRequest(
        request_id="draft-submit-optimization",
        expected_quotes=[quote],
    )
    order_service.submit_draft(db, order.id, payload, creator.id)
    db.refresh(customer)
    db.refresh(order)
    assert order.status == C.ORDER_PRODUCING
    assert order.charged_amount == Decimal("45.00")
    assert customer.balance == Decimal("55.00")
    assert order_service.submit_draft(
        db, order.id, payload, creator.id
    )["replayed"] is True
    with pytest.raises(ValueError, match="只有草稿"):
        order_service.submit_draft(
            db,
            order.id,
            DraftSubmitRequest(
                request_id="draft-submit-optimization-new",
                expected_quotes=[quote],
            ),
            creator.id,
        )


def test_insufficient_balance_rolls_back_whole_order(db):
    _route_and_workers(db)
    creator = _user(db, "poor-planner")
    customer = _customer(db, creator, "余额不足客户")
    balance_service.recharge_customer(
        db, customer_id=customer.id, amount=Decimal("10.00"), user_id=creator.id,
        request_id="insufficient-balance-recharge",
    )

    with pytest.raises(ValueError, match="余额不足"):
        _create_order(db, creator, customer, qty=2, price="10.00")

    assert db.query(DomesticOrder).count() == 0
    db.refresh(customer)
    assert customer.balance == Decimal("10.00")


def test_formal_order_request_id_prevents_double_charge(db):
    _route_and_workers(db)
    creator = _user(db, "retry-planner")
    customer = _customer(db, creator, "重试客户")
    balance_service.recharge_customer(
        db, customer_id=customer.id, amount=Decimal("100.00"), user_id=creator.id,
        request_id="formal-retry-recharge",
    )
    payload = OrderCreate(
        request_id="order-network-retry",
        order_no="RETRY-001",
        order_date=date(2026, 8, 17),
        required_ship_date=date(2026, 8, 24),
        customer_id=customer.id,
        order_category="normal",
        order_type="first_order",
        order_channel="wechat",
        items=[_priced_item(db, customer, qty=2, price="10.00")],
    )

    first = order_service.create_order(db, payload, creator.id)
    replay = order_service.create_order(db, payload, creator.id)
    db.refresh(customer)
    assert replay["id"] == first["id"]
    assert replay["replayed"] is True
    assert customer.balance == Decimal("80.00")
    assert db.query(DomesticOrder).count() == 1
    mini_rows, _ = order_service.list_orders(db, include_finance=False)
    assert "charged_amount" not in mini_rows[0]

    changed = payload.model_copy(update={"order_no": "RETRY-DIFFERENT"})
    with pytest.raises(ValueError, match="不同订单内容"):
        order_service.create_order(db, changed, creator.id)


def test_append_item_request_id_prevents_duplicate_item_and_charge(db):
    _route_and_workers(db)
    creator = _user(db, "append-retry-planner")
    customer = _customer(db, creator, "追加重试客户")
    balance_service.recharge_customer(
        db, customer_id=customer.id, amount=Decimal("100.00"), user_id=creator.id,
        request_id="append-retry-recharge",
    )
    created = _create_order(db, creator, customer, qty=1, price="0")
    payload = _priced_item(
        db, customer,
        request_id="append-network-retry",
        qty=2,
        price="5.00",
    )

    first = order_service.add_item(db, created["id"], payload, creator.id)
    replay = order_service.add_item(db, created["id"], payload, creator.id)

    db.refresh(customer)
    order = db.query(DomesticOrder).get(created["id"])
    assert replay == {"id": first["id"], "warning": None, "replayed": True}
    assert customer.balance == Decimal("90.00")
    assert db.query(DomesticOrderItem).filter(
        DomesticOrderItem.order_id == order.id
    ).count() == 2
    assert order.next_line_no == 3
    assert order.item_count == 2
    assert order.total_unit_qty == 3

    changed = payload.model_copy(update={"order_qty": 3})
    with pytest.raises(ValueError, match="不同明细内容"):
        order_service.add_item(db, order.id, changed, creator.id)

    order_service.delete_item(db, first["id"], creator.id)
    db.refresh(customer)
    db.refresh(order)
    assert customer.balance == Decimal("100.00")
    assert order.item_count == 1
    assert order.total_unit_qty == 1
    with pytest.raises(ValueError, match="已删除"):
        order_service.add_item(db, order.id, payload, creator.id)


def test_order_scale_limits_creation_and_append(db):
    item = OrderItemInput(
        client_key="scale-line",
        attrs=_attrs(),
        order_qty=1,
        expected_quote={
            "original_price": "120.00",
            "base_price_version": 1,
            "discount_price": "0.00",
            "membership_level": "black",
            "pricing_rule": "member_reduction",
            "pricing_version": "domestic-member-v1",
        },
    )
    base = {
        "request_id": "oversized-order",
        "order_no": "TOO-LARGE",
        "order_date": date(2026, 8, 17),
        "required_ship_date": date(2026, 8, 24),
        "customer_id": 1,
        "order_category": "normal",
        "order_type": "first_order",
        "order_channel": "wechat",
    }
    with pytest.raises(ValueError, match="50"):
        OrderCreate(**base, items=[item] * 51)
    with pytest.raises(ValueError, match="5000"):
        OrderCreate(
            **base,
            items=[
                item.model_copy(update={"order_qty": 2000}),
                item.model_copy(update={"order_qty": 2000}),
                item.model_copy(update={"order_qty": 1001}),
            ],
        )

    _route_and_workers(db)
    creator = _user(db, "limit-planner")
    customer = _customer(db, creator, "订单上限客户")
    created = _create_order(db, creator, customer, qty=1, price="0")
    order = db.query(DomesticOrder).get(created["id"])
    order.total_unit_qty = C.MAX_ORDER_UNITS - 1
    db.commit()
    with pytest.raises(ValueError, match="5000"):
        order_service.add_item(
            db,
            order.id,
            OrderItemAppend(
                request_id="append-over-limit",
                client_key="append-over-limit-line",
                attrs=_attrs(),
                order_qty=2,
                expected_quote=item.expected_quote,
            ),
            creator.id,
        )


def test_item_amount_edits_settle_difference_and_termination_refunds(db):
    _route_and_workers(db)
    creator = _user(db, "amount-planner")
    customer = _customer(db, creator, "差额客户")
    balance_service.recharge_customer(
        db, customer_id=customer.id, amount=Decimal("100.00"), user_id=creator.id,
        request_id="order-delta-recharge",
    )
    created = _create_order(db, creator, customer, qty=2, price="10.00")
    item = _item(db, created["id"])
    db.refresh(customer)
    assert customer.balance == Decimal("80.00")

    order_service.update_item(db, item.id, OrderItemUpdate(order_qty=3), creator.id)
    db.refresh(customer)
    assert customer.balance == Decimal("70.00")

    # 手工改价（不高于原价快照）同样走差额结算：3 件 × 10 降到 3 件 × 5，退 15
    order_service.update_item(db, item.id, OrderItemUpdate(unit_price=Decimal("5.00")), creator.id)
    db.refresh(customer)
    assert customer.balance == Decimal("85.00")
    with pytest.raises(ValidationError):
        OrderItemUpdate(unit_price=Decimal("0"))

    order_service.terminate_order(db, created["id"], "客户取消", creator.id)
    db.refresh(customer)
    assert customer.balance == Decimal("100.00")
    with pytest.raises(ValueError, match="已终止"):
        order_service.update_item(db, item.id, OrderItemUpdate(order_qty=4), creator.id)
    db.refresh(customer)
    assert customer.balance == Decimal("100.00")


def test_quantity_reports_consume_unit_codes_in_order(db):
    _, workers = _route_and_workers(db)
    creator = _user(db, "sequence-planner")
    customer = _customer(db, creator, "顺序客户")
    created = _create_order(db, creator, customer, qty=10, price="0")
    item = _item(db, created["id"])
    step = _steps(db, item)[0]

    first = report_service.submit_report(
        db, item_id=item.id, progress_id=step["progress_id"], qty=3,
        user_id=workers[0].id,
    )
    second = report_service.submit_report(
        db, item_id=item.id, progress_id=step["progress_id"], qty=1,
        user_id=workers[0].id,
    )
    assert first["unit_codes"] == ["A1-01", "A1-02", "A1-03"]
    assert second["unit_codes"] == ["A1-04"]

    with pytest.raises(ValueError, match="最新批次倒序撤销"):
        report_service.revoke_report(db, first["log_id"], workers[0].id)

    report_service.revoke_report(db, second["log_id"], workers[0].id)
    replacement = report_service.submit_report(
        db, item_id=item.id, progress_id=step["progress_id"], qty=1,
        user_id=workers[0].id,
    )
    assert replacement["unit_codes"] == ["A1-04"]


def test_report_replay_from_preexisting_session_returns_unit_mapping(db, engine):
    _, workers = _route_and_workers(db)
    creator = _user(db, "rr-replay-planner")
    customer = _customer(db, creator, "RR重放客户")
    created = _create_order(db, creator, customer, qty=2, price="0")
    item = _item(db, created["id"])
    progress_id = _steps(db, item)[0]["progress_id"]
    Session = sessionmaker(bind=engine)
    waiting = Session()
    winner = Session()
    try:
        assert waiting.query(DomesticReportLog).filter(
            DomesticReportLog.request_id == "rr-report-retry"
        ).first() is None
        first = report_service.submit_report(
            winner, item_id=item.id, progress_id=progress_id, qty=1,
            user_id=workers[0].id, request_id="rr-report-retry",
        )
        replay = report_service.submit_report(
            waiting, item_id=item.id, progress_id=progress_id, qty=1,
            user_id=workers[0].id, request_id="rr-report-retry",
        )
        assert replay["replayed"] is True
        assert replay["unit_ids"] == first["unit_ids"]
        assert replay["unit_codes"] == ["A1-01"]
    finally:
        waiting.close()
        winner.close()


def test_revoked_report_history_still_blocks_item_delete(db):
    _, workers = _route_and_workers(db)
    creator = _user(db, "audit-delete-planner")
    customer = _customer(db, creator, "审计删除客户")
    created = _create_order(db, creator, customer, qty=2, price="0")
    original = _item(db, created["id"])
    order_service.add_item(
        db, created["id"],
        _priced_item(
            db, customer, request_id="audit-delete-append", qty=1, price="0"
        ),
        creator.id,
    )
    log = report_service.submit_report(
        db, item_id=original.id, progress_id=_steps(db, original)[0]["progress_id"],
        qty=1, user_id=workers[0].id,
    )
    report_service.revoke_report(db, log["log_id"], workers[0].id)

    with pytest.raises(ValueError, match="报工记录"):
        order_service.delete_item(db, original.id, creator.id)


def test_unit_mode_requires_exact_upstream_unit_and_exact_revoke_guard(db):
    _, workers = _route_and_workers(db)
    creator = _user(db, "unit-planner")
    customer = _customer(db, creator, "逐件客户")
    created = _create_order(db, creator, customer, qty=5, price="0")
    item = _item(db, created["id"])
    steps = _steps(db, item)
    first_log = report_service.submit_report(
        db, item_id=item.id, progress_id=steps[0]["progress_id"], qty=3,
        user_id=workers[0].id,
    )
    report_service.submit_report(
        db, item_id=item.id, progress_id=steps[0]["progress_id"], qty=2,
        user_id=workers[0].id,
    )
    units = unit_service.ensure_item_units(db, item)

    scan = report_service.scan_unit(db, units[1].id, workers[1].id)
    assert scan["can_submit"] is True
    assert scan["unit_code"] == "A1-02"
    report_service.submit_report(
        db, item_id=item.id, progress_id=steps[1]["progress_id"], qty=1,
        unit_id=units[1].id, user_id=workers[1].id,
    )
    with pytest.raises(ValueError, match="已经报过"):
        report_service.submit_report(
            db, item_id=item.id, progress_id=steps[1]["progress_id"], qty=1,
            unit_id=units[1].id, user_id=workers[1].id,
        )

    # Aggregate counts would allow 5-3=2 >= downstream 1, but A1-02 itself is consumed.
    with pytest.raises(ValueError, match="A1-02"):
        report_service.revoke_report(db, first_log["log_id"], workers[0].id)


def test_shrink_rejects_high_numbered_reported_unit(db):
    _, workers = _route_and_workers(db)
    creator = _user(db, "shrink-planner")
    customer = _customer(db, creator, "缩量客户")
    created = _create_order(db, creator, customer, qty=10, price="0")
    item = _item(db, created["id"])
    step = _steps(db, item)[0]
    unit_ten = unit_service.ensure_item_units(db, item)[9]
    report_service.submit_report(
        db, item_id=item.id, progress_id=step["progress_id"], qty=1,
        unit_id=unit_ten.id, user_id=workers[0].id,
    )

    with pytest.raises(ValueError, match="A1-10"):
        order_service.update_item(db, item.id, OrderItemUpdate(order_qty=5), creator.id)


def test_unit_qr_roundtrip_and_public_progress_hides_process_property(db):
    _, _workers = _route_and_workers(db)
    creator = _user(db, "track-planner")
    customer = _customer(db, creator, "进度客户")
    created = _create_order(db, creator, customer, qty=2, price="0")
    item = _item(db, created["id"])
    unit = db.query(DomesticItemUnit).filter(DomesticItemUnit.item_id == item.id).first()
    qr = report_service.generate_unit_qr_data(unit.id)
    assert qr.startswith(f"{C.UNIT_QR_PREFIX}:{unit.id}:")
    assert report_service.verify_unit_qr_data(qr) == (True, unit.id)

    staff_steps = order_service.get_order_detail(db, created["id"])["items"][0]["steps"]
    public_steps = order_service.get_order_detail(
        db, created["id"], public_progress_only=True,
    )["items"][0]["steps"]
    assert len(staff_steps) == 3
    assert [step["process_name"] for step in public_steps] == ["逐件制网", "逐件定型"]

    for process in db.query(Process).filter(Process.name.like("逐件%")):
        process.show_in_domestic_track = 0
    db.flush()
    all_hidden = order_service.get_order_detail(
        db, created["id"], public_progress_only=True, include_finance=False,
    )["items"][0]
    assert all_hidden["steps"] == []
    assert all_hidden["progress_hidden"] is True
    assert all_hidden["current_process"] == "工序进度暂不展示"


def test_unit_display_codes_stay_stable_when_quantity_crosses_digit_boundary(db):
    _, _workers = _route_and_workers(db)
    creator = _user(db, "stable-code-planner")
    customer = _customer(db, creator, "稳定码客户")
    created = _create_order(db, creator, customer, qty=99, price="0")
    item = _item(db, created["id"])
    first = unit_service.ensure_item_units(db, item)[0]
    assert unit_service.unit_display_code(item, first.unit_no) == "A1-01"

    order_service.update_item(db, item.id, OrderItemUpdate(order_qty=100), creator.id)
    db.refresh(item)
    units = unit_service.ensure_item_units(db, item)
    assert unit_service.unit_display_code(item, units[0].unit_no) == "A1-01"
    assert unit_service.unit_display_code(item, units[-1].unit_no) == "A1-100"


def test_worker_permission_selects_quantity_or_unit_report_mode(db):
    from app.mini.router import _domestic_report_mode

    worker = _user(db, "mode-worker")
    role = ArkRole(name="mode-worker-role", label="内贸模式测试")
    unit_permission = ArkPermission(
        code=C.REPORT_UNIT_PERMISSION, module="domestic", action="write", label="逐件报工",
    )
    quantity_permission = ArkPermission(
        code=C.REPORT_QUANTITY_PERMISSION, module="domestic", action="write", label="数量报工",
    )
    role.permissions.append(unit_permission)
    worker.roles.append(role)
    db.add_all([role, unit_permission, quantity_permission])
    db.flush()

    assert _domestic_report_mode(worker) == "unit"
    role.permissions.append(quantity_permission)
    assert _domestic_report_mode(worker) == "quantity"
    role.permissions.remove(unit_permission)
    assert _domestic_report_mode(worker) == "quantity"


def test_unit_submit_requires_qr_signature_again_at_write_time(db):
    from app.mini.router import domestic_submit

    _, workers = _route_and_workers(db)
    worker = workers[0]
    role = ArkRole(name="unit-write-role", label="逐件写端签名测试")
    permission = ArkPermission(
        code=C.REPORT_UNIT_PERMISSION, module="domestic", action="write", label="逐件报工",
    )
    role.permissions.append(permission)
    worker.roles.append(role)
    db.add_all([role, permission])
    creator = _user(db, "signed-unit-planner")
    customer = _customer(db, creator, "签名逐件客户")
    created = _create_order(db, creator, customer, qty=2, price="0")
    item = _item(db, created["id"])
    unit = unit_service.ensure_item_units(db, item)[0]
    progress_id = _steps(db, item)[0]["progress_id"]

    invalid = DomesticSubmitRequest(
        item_id=item.id, progress_id=progress_id, qty=1,
        unit_id=unit.id, unit_sign="deadbeef",
    )
    with pytest.raises(HTTPException, match="单件二维码签名无效"):
        asyncio.run(domestic_submit(invalid, current_user=worker, db=db))

    sign = report_service.generate_unit_qr_data(unit.id).rsplit(":", 1)[1]
    valid = invalid.model_copy(update={"unit_sign": sign})
    result = asyncio.run(domestic_submit(valid, current_user=worker, db=db))
    assert result["unit_codes"] == ["A1-01"]


def test_credit_customer_orders_without_balance(db):
    _route_and_workers(db)
    creator = _user(db, "credit-planner")
    customer = _customer(db, creator, "赊账下单客户")
    customer.settle_mode = "credit"
    db.commit()

    created = _create_order(db, creator, customer, qty=2, price="10.00")

    db.refresh(customer)
    order = db.query(DomesticOrder).get(created["id"])
    assert order.status == C.ORDER_PRODUCING
    assert customer.balance == Decimal("-20.00")
    charge = db.query(DomesticCustomerLedger).filter_by(
        customer_id=customer.id, transaction_type="order_charge",
    ).one()
    assert charge.amount == Decimal("-20.00")

    balance_service.recharge_customer(
        db, customer_id=customer.id, amount=Decimal("50.00"), user_id=creator.id,
        remark="欠款冲抵", request_id="credit-order-recharge",
    )
    db.refresh(customer)
    assert customer.balance == Decimal("30.00")


def test_credit_customer_draft_submit_without_balance(db):
    _route_and_workers(db)
    creator = _user(db, "credit-draft-planner")
    customer = _customer(db, creator, "赊账草稿客户")
    customer.settle_mode = "credit"
    db.commit()

    created = _create_order(db, creator, customer, qty=3, price="15.00", is_draft=True)
    db.refresh(customer)
    order = db.query(DomesticOrder).get(created["id"])
    assert order.status == C.ORDER_DRAFT
    assert customer.balance == Decimal("0.00")

    item = db.query(DomesticOrderItem).filter_by(order_id=order.id).one()
    quote = {
        "item_id": item.id,
        "original_price": item.original_price,
        "base_price_version": item.base_price_version_snapshot,
        "discount_price": item.unit_price,
        "membership_level": item.membership_level_snapshot,
        "pricing_rule": item.pricing_rule,
        "pricing_version": item.pricing_version,
    }
    payload = DraftSubmitRequest(
        request_id="credit-draft-submit",
        expected_quotes=[quote],
    )
    order_service.submit_draft(db, order.id, payload, creator.id)

    db.refresh(customer)
    db.refresh(order)
    assert order.status == C.ORDER_PRODUCING
    assert customer.balance == Decimal("-45.00")


def test_prepay_customer_negative_adjust_rejected(db):
    operator = _user(db, "settle-adjust-operator")
    customer = _customer(db, operator, "负调整客户")
    balance_service.recharge_customer(
        db, customer_id=customer.id, amount=Decimal("10.00"), user_id=operator.id,
        request_id="neg-adjust-recharge",
    )

    with pytest.raises(ValueError, match="余额不足"):
        customer_service.adjust_customer(
            db,
            customer.id,
            CustomerAdjust(
                amount=Decimal("-20.00"), remark="超额调减", request_id="neg-adjust-prepay",
            ),
            operator.id,
        )
    db.refresh(customer)
    assert customer.balance == Decimal("10.00")

    customer_service.update_customer(db, customer.id, CustomerUpdate(settle_mode="credit"))
    snapshot = customer_service.adjust_customer(
        db,
        customer.id,
        CustomerAdjust(
            amount=Decimal("-20.00"), remark="赊账调减", request_id="neg-adjust-credit",
        ),
        operator.id,
    )
    db.refresh(customer)
    assert customer.balance == Decimal("-10.00")
    assert snapshot["settle_mode"] == "credit"


def test_required_ship_date_required_and_returned(db):
    _route_and_workers(db)
    creator = _user(db, "ship-date-planner")
    customer = _customer(db, creator, "发货日期客户")

    with pytest.raises(ValidationError, match="required_ship_date"):
        OrderCreate(
            request_id="ship-date-missing",
            order_no="SHIP-DATE-001",
            order_date=date(2026, 8, 17),
            customer_id=customer.id,
            order_category="normal",
            order_type="first_order",
            order_channel="wechat",
            items=[_priced_item(db, customer, qty=1, price="0")],
        )

    created = _create_order(db, creator, customer, qty=1, price="0")
    detail = order_service.get_order_detail(db, created["id"])
    assert detail["required_ship_date"] == date(2026, 8, 24)
    rows, _ = order_service.list_orders(db)
    row = next(r for r in rows if r["id"] == created["id"])
    assert row["required_ship_date"] == date(2026, 8, 24)


def test_update_customer_settle_mode(db):
    operator = _user(db, "settle-mode-admin")
    customer = _customer(db, operator, "结算方式客户")
    assert customer.settle_mode == "prepay"

    updated = customer_service.update_customer(
        db, customer.id, CustomerUpdate(settle_mode="credit")
    )
    assert updated.settle_mode == "credit"

    rows, total = customer_service.list_customers(db, keyword="结算方式客户")
    assert total == 1
    assert rows[0]["settle_mode"] == "credit"
    assert rows[0]["settle_mode_label"] == "先下单后付款"


def test_order_list_shows_owner_and_repurchase_fields(db):
    """列表补台账字段：归属销售、上次下单日期、复购周期、实际交付日期。"""
    _route_and_workers(db)
    owner = _user(db, "owner-sales")
    creator = _user(db, "order-list-creator")
    customer = _customer(db, creator, "台账客户")
    customer.owner_user_id = owner.id
    db.flush()

    _create_order(db, creator, customer, qty=1, price="0")

    # 第二张单：同一客户的复购
    second = order_service.create_order(
        db,
        OrderCreate(
            request_id=str(uuid4()),
            order_no="OPT-002",
            order_date=date(2026, 8, 25),
            required_ship_date=date(2026, 8, 30),
            customer_id=customer.id,
            order_category="normal",
            order_type="first_order",
            order_channel="wechat",
            items=[_priced_item(db, customer, qty=2, price="0")],
        ),
        creator.id,
    )

    rows, _ = order_service.list_orders(db)
    by_no = {r["order_no"]: r for r in rows}
    first_row = by_no["OPT-001"]
    second_row = by_no["OPT-002"]

    assert first_row["owner_name"] == "owner-sales"
    assert second_row["owner_name"] == "owner-sales"

    # 首张单没有上次下单；第二张单的上次下单是首张，复购周期 = 8 天
    assert first_row["last_order_date"] is None
    assert first_row["repurchase_cycle_days"] is None
    assert second_row["last_order_date"] == "2026-08-17"
    assert second_row["repurchase_cycle_days"] == 8

    # 未发货时实际交付日期为空
    assert second_row["actual_ship_date"] is None

    # 发货后实际交付日期出现
    item = _item(db, second["id"])
    item.status = C.ITEM_SHIPPED
    item.ship_time = datetime(2026, 8, 29, 10, 0, 0)
    db.flush()
    rows, _ = order_service.list_orders(db)
    second_row = next(r for r in rows if r["id"] == second["id"])
    assert second_row["actual_ship_date"] == "2026-08-29"


def _special_item(db, attrs, price):
    """特单明细：不走报价，直接给销售价。"""
    return OrderItemInput(
        client_key=f"special-{price}-{uuid4().hex[:8]}",
        attrs=attrs,
        order_qty=1,
        expected_quote=None,
        special_price=Decimal(price),
    )


def test_special_order_uses_manual_sales_price(db):
    """特单不调用原始价格，直接按录入的销售价成交。"""
    _route_and_workers(db)
    creator = _user(db, "special-creator")
    customer = _customer(db, creator, "特单客户")
    customer.settle_mode = "credit"
    db.flush()

    created = order_service.create_order(
        db,
        OrderCreate(
            request_id=str(uuid4()),
            order_no="SP-001",
            order_date=date(2026, 8, 17),
            required_ship_date=date(2026, 8, 24),
            customer_id=customer.id,
            order_category="special",
            order_type="first_order",
            order_channel="wechat",
            items=[_special_item(db, _attrs(), "88.00")],
        ),
        creator.id,
    )

    item = _item(db, created["id"])
    assert item.unit_price == Decimal("88.00")
    assert item.original_price == Decimal("88.00")
    assert item.discount_amount == Decimal("0.00")
    assert item.labor_fee == Decimal("0.00")
    assert item.pricing_rule == "manual_override"
    # 总价 = 销售价 × 数量
    assert created["total_amount"] == 88.00


def test_special_order_without_price_falls_back_to_quote(db):
    """特单未带销售价时回退报价路径（兼容旧数据/测试）。"""
    _route_and_workers(db)
    creator = _user(db, "special-fallback-creator")
    customer = _customer(db, creator, "特单回退客户")
    customer.settle_mode = "credit"
    db.flush()

    item = _priced_item(db, customer, qty=1, price="10.00")
    item.labor_fee = Decimal("0")
    created = order_service.create_order(
        db,
        OrderCreate(
            request_id=str(uuid4()),
            order_no="SP-FALLBACK-001",
            order_date=date(2026, 8, 17),
            required_ship_date=date(2026, 8, 24),
            customer_id=customer.id,
            order_category="special",
            order_type="first_order",
            order_channel="wechat",
            items=[item],
        ),
        creator.id,
    )
    db_item = _item(db, created["id"])
    assert db_item.unit_price == Decimal("10.00")


def test_normal_order_labor_fee_adds_to_unit_price(db):
    """普单明细单价 = 优惠价 + 手工费，总价含手工费。"""
    _route_and_workers(db)
    creator = _user(db, "labor-creator")
    customer = _customer(db, creator, "手工费客户")
    customer.settle_mode = "credit"
    db.flush()

    item = _priced_item(db, customer, qty=2, price="50.00")
    item.labor_fee = Decimal("5.00")
    created = order_service.create_order(
        db,
        OrderCreate(
            request_id=str(uuid4()),
            order_no="LABOR-001",
            order_date=date(2026, 8, 17),
            required_ship_date=date(2026, 8, 24),
            customer_id=customer.id,
            order_category="normal",
            order_type="first_order",
            order_channel="wechat",
            items=[item],
        ),
        creator.id,
    )

    db_item = _item(db, created["id"])
    # unit_price = 优惠价50 + 手工费5 = 55
    assert db_item.unit_price == Decimal("55.00")
    assert db_item.labor_fee == Decimal("5.00")
    # 总价 = 55 × 2 = 110
    assert created["total_amount"] == 110.00
