"""Specification edits refresh the price baseline without changing the agreed price."""
from decimal import Decimal as D

import pytest

from app.domestic import balance_service, constants as C, order_service, pricing_service
from app.domestic.models import DomesticBasePrice, DomesticCustomerLedger, DomesticItemUnit, DomesticOrder, DomesticOrderItem, DomesticProduct
from app.domestic.product_service import find_or_create_product
from app.domestic.schemas import DraftSubmitRequest, OrderItemUpdate, ProductAttrs
from tests.test_domestic_review_flow import _cap_attrs, _customer, _order_payload, _seed_order_dicts, _user


def _context(db, *, labor=D("0"), draft=True):
    user = _user(db, "spec-price-owner")
    customer = _customer(db, user, "spec-price-customer", membership_level="black", balance=D("20000"))
    attrs_by_length = {}
    quotes = {}
    for length, original in [("30厘米", D("2498")), ("35厘米", D("2650")), ("40厘米", D("3300"))]:
        attrs = _cap_attrs(craft="递顶", size="M", length=length)
        _seed_order_dicts(db, attrs)
        product = find_or_create_product(db, ProductAttrs.model_validate(attrs))
        db.add(DomesticBasePrice(product_type="cap", craft="递顶", length=length,
                                 original_price=original, version=2 if length == "30厘米" else 1))
        discount = pricing_service.resolve_discount(product_type="cap", craft="递顶", length=length,
                                                   original_price=original, membership_level="black")
        attrs_by_length[length] = attrs
        quotes[length] = dict(original_price=original, base_price_version=2 if length == "30厘米" else 1,
                              discount_price=discount.final_price, membership_level="black",
                              pricing_rule=discount.pricing_rule, pricing_version=pricing_service.PRICING_VERSION)
    db.commit()
    payload = _order_payload(customer, attrs_by_length["35厘米"], quotes["35厘米"], "spec-price-order", is_draft=draft)
    payload.items[0].labor_fee = labor
    second = payload.items[0].model_copy(deep=True)
    second.client_key = "line-2"
    payload.items.append(second)
    created = order_service.create_order(db, payload, user.id)
    order = db.get(DomesticOrder, created["id"])
    items = db.query(DomesticOrderItem).filter_by(order_id=order.id).order_by(DomesticOrderItem.line_no).all()
    return user, customer, order, items, attrs_by_length


def _snapshot(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("labor", [D("0"), D("25")])
def test_spec_and_price_edit_uses_new_default_and_submits_without_false_review(db, autoflush, labor):
    db.autoflush = autoflush
    user, customer, order, (item, other), attrs = _context(db, labor=labor)
    other_before = _snapshot(other)
    order_service.update_item(db, item.id, OrderItemUpdate(attrs=attrs["30厘米"], unit_price=D("2498") + labor, order_qty=2), user.id)
    db.refresh(item)
    db.refresh(other)
    assert _snapshot(other) == other_before
    assert item.unit_price == D("2498") + labor
    assert item.original_price == item.default_discount_price == D("2498")
    assert item.discount_amount == 0
    assert item.base_price_version_snapshot == 2
    detail = order_service.get_order_detail(db, order.id)
    assert not detail["items"][0]["price_changed"]
    assert customer.balance == D("20000")
    assert db.query(DomesticCustomerLedger).count() == 0
    submitted = order_service.submit_draft(db, order.id, DraftSubmitRequest(
        request_id="spec-submit", expected_quotes=detail["current_expected_quotes"]), user.id)
    assert submitted["status"] == C.ORDER_PRODUCING
    assert submitted["charged_amount"] == 2498 * 2 + 2530 + 3 * float(labor)


def test_spec_only_edit_preserves_manual_price_but_refreshes_default(db):
    user, customer, order, (item, _other), attrs = _context(db)
    order_service.update_item(db, item.id, OrderItemUpdate(unit_price=D("2498")), user.id)
    order_service.update_item(db, item.id, OrderItemUpdate(attrs=attrs["30厘米"]), user.id)
    db.refresh(item)
    assert item.unit_price == item.default_discount_price == item.original_price == D("2498")
    detail = order_service.get_order_detail(db, order.id)
    assert not detail["items"][0]["price_changed"]
    submitted = order_service.submit_draft(db, order.id, DraftSubmitRequest(
        request_id="spec-only-submit", expected_quotes=detail["current_expected_quotes"]), user.id)
    assert submitted["status"] == C.ORDER_PRODUCING


def test_new_spec_real_discount_still_requires_review_and_keeps_agreed_price(db):
    user, customer, order, (item, _other), attrs = _context(db)
    order_service.update_item(db, item.id, OrderItemUpdate(attrs=attrs["40厘米"]), user.id)
    db.refresh(item)
    assert item.unit_price == D("2530")
    assert item.original_price == D("3300")
    assert item.default_discount_price == D("3180")
    assert item.discount_amount == D("770")
    detail = order_service.get_order_detail(db, order.id)
    assert detail["items"][0]["price_changed"]
    submitted = order_service.submit_draft(db, order.id, DraftSubmitRequest(
        request_id="spec-real-discount", expected_quotes=detail["current_expected_quotes"]), user.id)
    assert submitted["status"] == C.ORDER_PENDING_REVIEW
    assert submitted["charged_amount"] == 0
    assert customer.balance == D("20000")


def test_combined_edit_validates_price_against_new_original(db):
    user, customer, order, (item, _other), attrs = _context(db)
    order_service.update_item(db, item.id, OrderItemUpdate(attrs=attrs["40厘米"], unit_price=D("3180")), user.id)
    db.refresh(item)
    assert item.unit_price == item.default_discount_price == D("3180")


def test_nonpricing_attribute_edit_keeps_existing_price_baseline(db):
    user, customer, order, (item, _other), attrs = _context(db)
    base = db.query(DomesticBasePrice).filter_by(length="35厘米").one()
    base.original_price = D("2800")
    base.version += 1
    changed = {**attrs["35厘米"], "size": "S"}
    _seed_order_dicts(db, changed)
    db.commit()
    order_service.update_item(db, item.id, OrderItemUpdate(attrs=changed), user.id)
    db.refresh(item)
    assert item.original_price == D("2650")
    assert item.unit_price == item.default_discount_price == D("2530")
    assert item.base_price_version_snapshot == 1


def test_spec_edit_on_submitted_order_preserves_charge_and_ledger(db):
    user, customer, order, (item, _other), attrs = _context(db, draft=False)
    balance_before = customer.balance
    charged_before = order.charged_amount
    ledger_before = db.query(DomesticCustomerLedger).count()
    order_service.update_item(db, item.id, OrderItemUpdate(attrs=attrs["40厘米"]), user.id)
    db.refresh(item)
    db.refresh(customer)
    db.refresh(order)
    assert item.unit_price == D("2530")
    assert item.default_discount_price == D("3180")
    assert customer.balance == balance_before
    assert order.charged_amount == charged_before
    assert db.query(DomesticCustomerLedger).count() == ledger_before


@pytest.mark.parametrize("missing", [False, True])
def test_invalid_new_spec_price_rolls_back_whole_edit(db, missing):
    user, customer, order, (item, other), attrs = _context(db)
    if missing:
        db.query(DomesticBasePrice).filter_by(length="30厘米").delete()
        db.commit()
    before = _snapshot(item)
    with pytest.raises(ValueError, match="原始价|原价|价格"):
        order_service.update_item(db, item.id, OrderItemUpdate(attrs=attrs["30厘米"], order_qty=2), user.id)
    # Even a caller reusing this Session cannot accidentally commit the rejected edit.
    db.commit()
    db.refresh(item)
    assert _snapshot(item) == before
    assert customer.balance == D("20000")
    assert db.query(DomesticCustomerLedger).count() == 0


def test_failure_after_spec_and_quantity_changes_rolls_back_products_and_units(db, monkeypatch):
    user, customer, order, (item, other), attrs = _context(db)
    before = _snapshot(item)
    order_before = _snapshot(order)
    products_before = [_snapshot(row) for row in db.query(DomesticProduct).order_by(DomesticProduct.id)]
    units_before = [_snapshot(row) for row in db.query(DomesticItemUnit).order_by(DomesticItemUnit.id)]
    changed = {**attrs["30厘米"], "size": "S"}
    _seed_order_dicts(db, changed)
    db.commit()

    def fail_settlement(*args, **kwargs):
        raise RuntimeError("settlement unavailable")

    monkeypatch.setattr(balance_service, "sync_order_finance", fail_settlement)
    with pytest.raises(RuntimeError, match="settlement unavailable"):
        order_service.update_item(db, item.id, OrderItemUpdate(
            attrs=changed, unit_price=D("2498"), order_qty=2), user.id)
    db.commit()
    db.refresh(item)
    db.refresh(order)
    assert _snapshot(item) == before
    assert _snapshot(order) == order_before
    assert [_snapshot(row) for row in db.query(DomesticProduct).order_by(DomesticProduct.id)] == products_before
    assert [_snapshot(row) for row in db.query(DomesticItemUnit).order_by(DomesticItemUnit.id)] == units_before
    assert customer.balance == D("20000")
    assert db.query(DomesticCustomerLedger).count() == 0


def test_piece_size_embedded_in_craft_refreshes_default_price(db):
    user = _user(db, "piece-spec-owner")
    customer = _customer(db, user, "piece-spec-customer", membership_level="black", balance=D("20000"))
    old = {"product_type": "piece", "craft": "全递针12*14", "length": "30厘米"}
    new = {**old, "craft": "全递针14*16"}
    for attrs, price in [(old, D("1140")), (new, D("1260"))]:
        _seed_order_dicts(db, attrs)
        find_or_create_product(db, ProductAttrs.model_validate(attrs))
        db.add(DomesticBasePrice(product_type="piece", craft=attrs["craft"], length=attrs["length"],
                                 original_price=price, version=1))
    db.commit()
    expected = dict(original_price=D("1140"), base_price_version=1, discount_price=D("1020"),
                    membership_level="black", pricing_rule="member_reduction", pricing_version=pricing_service.PRICING_VERSION)
    created = order_service.create_order(db, _order_payload(customer, old, expected, "piece-spec-order", is_draft=True), user.id)
    item = db.query(DomesticOrderItem).filter_by(order_id=created["id"]).one()
    order_service.update_item(db, item.id, OrderItemUpdate(attrs=new, unit_price=D("1140")), user.id)
    db.refresh(item)
    assert item.original_price == D("1260")
    assert item.unit_price == item.default_discount_price == D("1140")
    assert item.pricing_rule == "member_reduction"
