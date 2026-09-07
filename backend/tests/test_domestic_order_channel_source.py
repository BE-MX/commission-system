from decimal import Decimal
import pytest
from sqlalchemy import text
from pydantic import ValidationError

from app.domestic import attribute_service, order_service
from app.domestic.models import DomesticCustomer, DomesticOrder
from app.domestic.schemas import OrderCreate, OrderUpdate
from app.system.models import SysDict
from scripts.domestic_order_channel_cutover import snapshot, summarize, apply_conversion, CHANNELS
from tests.test_domestic_member_pricing import _order_pricing_context, _priced_order_payload


def context(db, suffix):
    user, customer, _, _, quote, attrs = _order_pricing_context(db, suffix)
    payload = _priced_order_payload(customer, attrs, quote, request_id=f"channel-{suffix}", is_draft=True)
    return user, customer, payload


@pytest.mark.parametrize("order_no", [None, "", "   ", "omitted"])
def test_business_order_can_omit_customer_number_and_clear_it_later(db, order_no):
    user, customer, payload = context(db, "optional")
    data = payload.model_dump()
    if order_no == "omitted":
        data.pop("order_no")
    else:
        data["order_no"] = order_no
    result = order_service.create_order(db, OrderCreate.model_validate(data), user.id)
    order = db.get(DomesticOrder, result["id"])
    assert order.order_no == "" and order.domestic_no.startswith("DO")
    order_service.update_order(db, order.id, OrderUpdate(order_no="  PO-1  "), user_id=user.id)
    assert order.order_no == "PO-1"
    order_service.update_order(db, order.id, OrderUpdate(order_no=None), user_id=user.id)
    assert order.order_no == ""


def test_optional_order_number_normalizes_idempotent_payload_and_rejects_nontext(db):
    user, customer, payload = context(db, "normalize")
    data = payload.model_dump()
    data.pop("order_no")
    omitted = OrderCreate.model_validate(data)
    empty = OrderCreate.model_validate({**data, "order_no": None})
    first = order_service.create_order(db, omitted, user.id)
    second = order_service.create_order(db, empty, user.id)
    assert first["id"] == second["id"]
    for value in (123, False, [], {}):
        with pytest.raises(ValidationError):
            OrderCreate.model_validate({**data, "order_no": value})
        with pytest.raises(ValidationError):
            OrderUpdate(order_no=value)


def test_source_column_filters_before_pagination_without_widening_creator_scope(db):
    user, customer, payload = context(db, "source")
    customer.customer_source = "referral"
    db.add(SysDict(type="domestic_customer_source", code="referral", label="老客转介绍", sort=1, is_active=True))
    result = order_service.create_order(db, payload, user.id)
    rows, total = order_service.list_orders(db, customer_source="referral", page_size=1, include_all=False, creator_id=user.id)
    assert total == 1 and rows[0]["id"] == result["id"]
    assert rows[0]["customer_source"] == "referral" and rows[0]["customer_source_label"] == "老客转介绍"
    assert order_service.list_orders(db, customer_source="missing")[1] == 0
    assert order_service.list_orders(db, customer_source="referral", include_all=False, creator_id=user.id+100)[1] == 0
    assert attribute_service.get_order_options(db)["customer_sources"] == [{"value":"referral", "label":"老客转介绍"}]


def test_channel_conversion_uses_settlement_mode_not_balance_and_keeps_finance(db):
    user, customer, payload = context(db, "convert")
    result = order_service.create_order(db, payload, user.id)
    original = db.get(DomesticOrder, result["id"])
    credit = DomesticCustomer(shop_name="cash-customer", settle_mode="credit", balance=Decimal("1000"), created_by=user.id)
    customer.balance = Decimal("0")
    db.add(credit)
    db.flush()
    cash = DomesticOrder(domestic_no="DO-CASH", order_no="", order_date=original.order_date, customer_id=credit.id,
                         order_category="special", order_kind="business", order_type="first_order", order_channel="other", created_by=user.id, status=4)
    production = DomesticOrder(domestic_no="DP-UNCHANGED", order_no="DP-UNCHANGED", order_date=original.order_date, customer_id=None,
                               order_category=None, order_kind="production", created_by=user.id)
    db.add_all([cash, production]); db.flush()
    connection = db.connection()
    before = snapshot(connection)
    protected = connection.execute(text("SELECT id,total_amount,charged_amount,status,order_category,order_no FROM ark_domestic_orders ORDER BY id")).all()
    balances = connection.execute(text("SELECT id,balance FROM ark_domestic_customers ORDER BY id")).all()
    after = apply_conversion(connection, before)
    assert summarize(after)["changed_orders"] == 0
    channels = dict(connection.execute(text("SELECT id,order_channel FROM ark_domestic_orders")).all())
    assert channels[original.id] == "recharge" and channels[cash.id] == "cash" and channels[production.id] is None
    assert connection.execute(text("SELECT id,total_amount,charged_amount,status,order_category,order_no FROM ark_domestic_orders ORDER BY id")).all() == protected
    assert connection.execute(text("SELECT id,balance FROM ark_domestic_customers ORDER BY id")).all() == balances
    assert attribute_service.get_order_options(db)["order_channels"] == [{"value":code,"label":label} for code,label in CHANNELS]
    assert summarize(apply_conversion(connection, after))["changed_orders"] == 0
