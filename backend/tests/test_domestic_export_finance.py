from decimal import Decimal
import pytest

from app.domestic import balance_service, order_service
from app.domestic.models import DomesticCustomerLedger, DomesticOrder, DomesticOrderItem
from app.domestic.schemas import OrderItemUpdate
from tests.test_domestic_member_pricing import _order_pricing_context, _priced_order_payload


def create_order(db, suffix, is_draft=False):
    user, customer, _, _, quote, attrs = _order_pricing_context(db, suffix)
    payload = _priced_order_payload(customer, attrs, quote, request_id=f"export-{suffix}", is_draft=is_draft)
    result = order_service.create_order(db, payload, user.id)
    return user, customer, db.get(DomesticOrder, result["id"])


def test_export_balance_uses_order_ledger_even_after_later_recharge(db):
    user, customer, order = create_order(db, "history")
    charge = db.query(DomesticCustomerLedger).filter_by(order_id=order.id).one()
    balance_service.recharge_customer(db, customer_id=customer.id, amount=Decimal("5000"),
                                     user_id=user.id, request_id="later-recharge")
    snapshot = order_service.get_order_detail(db, order.id)["balance_snapshot"]
    assert snapshot["source"] == "ledger"
    assert snapshot["balance_before"] == float(charge.balance_before)
    assert snapshot["balance_after"] == float(charge.balance_after)
    assert snapshot["settlement_amount"] == float(-charge.amount)
    assert snapshot["balance_after"] != float(customer.balance)
    public = order_service.get_order_detail(db, order.id, include_finance=False)
    assert "balance_snapshot" not in public


def test_export_after_edit_shows_actual_adjustment_balance_and_current_order_amount(db):
    user, customer, order = create_order(db, "adjustment")
    balance_service.recharge_customer(db, customer_id=customer.id, amount=Decimal("5000"),
                                     user_id=user.id, request_id="adjustment-recharge")
    before = customer.balance
    item = db.query(DomesticOrderItem).filter_by(order_id=order.id).one()
    price = item.unit_price
    order_service.update_item(db, item.id, OrderItemUpdate(order_qty=2), user.id)
    snapshot = order_service.get_order_detail(db, order.id)["balance_snapshot"]
    assert snapshot["transaction_type"] == "order_adjustment"
    assert snapshot["balance_before"] == float(before)
    assert snapshot["balance_after"] == float(before - price)
    assert snapshot["settlement_amount"] == float(price)
    assert snapshot["order_amount"] == float(price * 2)


def test_draft_projection_and_missing_history_are_explicit(db):
    _, customer, order = create_order(db, "draft", is_draft=True)
    snapshot = order_service.get_order_detail(db, order.id)["balance_snapshot"]
    assert snapshot["source"] == "draft_preview"
    assert snapshot["balance_before"] == float(customer.balance)
    assert snapshot["balance_after"] == float(customer.balance - order.total_amount)
    order.status = 1
    db.commit()
    snapshot = order_service.get_order_detail(db, order.id)["balance_snapshot"]
    assert snapshot["source"] == "unavailable"
    assert snapshot["balance_before"] is None and snapshot["balance_after"] is None


def test_edit_total_unit_price_preserves_labor_and_correct_discount(db):
    user, customer, _, _, quote, attrs = _order_pricing_context(db, "labor-edit")
    payload = _priced_order_payload(customer, attrs, quote, request_id="labor-edit-order")
    payload.items[0].labor_fee = Decimal("30")
    result = order_service.create_order(db, payload, user.id)
    item = db.query(DomesticOrderItem).filter_by(order_id=result["id"]).one()
    order_service.update_item(db, item.id, OrderItemUpdate(unit_price=Decimal("980")), user.id)
    assert item.labor_fee == Decimal("30")
    assert item.discount_amount == Decimal("50")  # 1000 - (980 - 30)
    order_service.update_item(db, item.id, OrderItemUpdate(unit_price=Decimal("1030")), user.id)
    assert item.discount_amount == 0
    with pytest.raises(ValueError, match="手工费"):
        order_service.update_item(db, item.id, OrderItemUpdate(unit_price=Decimal("20")), user.id)
    db.rollback()
