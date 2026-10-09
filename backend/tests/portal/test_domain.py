from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.time import to_beijing_naive
from app.portal.domain import (amendment_transition, content_hash, decimal_value,
    line_amount, normalize_email, request_transition, require_capability,
    require_fresh, require_version, total_amount)
from app.portal.errors import PortalError
from app.portal.inventory import InventoryObservation, validate_observation


def test_invoice_rounding_and_unknown_fees():
    line = line_amount(3, "35.2750", "-5.00")
    assert line == Decimal("100.83")
    assert total_amount([line], "45.00", "0.00", "0.00")[1] == Decimal("145.83")
    assert total_amount([line], None, "0.00", "0.00")[1] is None
    assert total_amount([line], "0.00", "0.00", "0.00")[1] == line


@pytest.mark.parametrize("quantity", [True, 1.5, "2", 0, -1, 10001])
def test_quantity_is_strict_integer(quantity):
    with pytest.raises(PortalError):
        line_amount(quantity, "2.00")


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1.001", 0.1, True, "bad", "1000000000000"])
def test_invalid_decimal_is_rejected(value):
    with pytest.raises(PortalError):
        decimal_value(value)


def test_negative_line_and_price_overflow_are_rejected():
    with pytest.raises(PortalError):
        total_amount(["-10.00", "20.00"], "0.00", "0.00", "0.00")
    with pytest.raises(PortalError):
        total_amount(["10.00"], None, "-1.00", "0.00")
    with pytest.raises(PortalError):
        line_amount(1, "1", "-2")
    with pytest.raises(PortalError):
        line_amount(1, "100000000")
    with pytest.raises(PortalError):
        total_amount(["10"], "-1", "0", "0")
    with pytest.raises(PortalError):
        total_amount(["10"], "1", "0", "0", maximum=Decimal("10"))


def test_normalization_preserves_email_tags_and_dots():
    assert normalize_email(" A.B+buyer@EXAMPLE.COM ") == "a.b+buyer@example.com"
    assert normalize_email("buy@例子.公司") == "buy@xn--fsqu00a.xn--55qx5d"
    with pytest.raises(PortalError):
        normalize_email("a@b@c.com")


def test_hash_is_order_independent_and_content_sensitive():
    assert content_hash({"b": 2, "a": "x"}) == content_hash({"a": "x", "b": 2})
    assert content_hash({"quantity": 2}) != content_hash({"quantity": 3})


@pytest.mark.parametrize("action", ["quote", "submit", "accept", "reject", "cancel", "reorder"])
def test_readonly_account_cannot_mutate(action):
    with pytest.raises(PortalError) as error:
        require_capability(action, can_order=False, can_view_price=True)
    assert error.value.status == 403


@pytest.mark.parametrize("action", ["price", "quote_detail", "amount", "pi"])
def test_price_capability_applies_to_history_and_download(action):
    with pytest.raises(PortalError):
        require_capability(action, can_order=False, can_view_price=False)


def test_unknown_actions_fail_closed():
    with pytest.raises(PortalError):
        require_capability("approve", can_order=True, can_view_price=True)
    require_capability("order_status", can_order=False, can_view_price=False)


def test_order_confirmation_never_skips_customer_proposal():
    with pytest.raises(PortalError):
        request_transition("submitted", "approve")
    state = request_transition("submitted", "propose")
    state = request_transition(state, "accept")
    assert request_transition(state, "approve") == "invoice_created"
    with pytest.raises(PortalError):
        request_transition("cancelled", "approve")
    with pytest.raises(PortalError):
        request_transition("invoice_created", "cancel")


def test_later_invoice_flow_is_separate_and_expired_offer_can_be_replaced():
    state = amendment_transition("current", "edit")
    state = amendment_transition(state, "propose")
    state = amendment_transition(state, "accept")
    assert amendment_transition(state, "publish") == "current"
    assert amendment_transition(state, "propose", expired=True) == "pending_customer"
    with pytest.raises(PortalError):
        amendment_transition("withdrawn", "publish")


def test_version_and_expiry_boundaries():
    with pytest.raises(PortalError) as error:
        require_version(1, None)
    assert error.value.status == 428
    with pytest.raises(PortalError):
        require_version(2, 1)
    boundary = datetime(2026, 10, 1)
    with pytest.raises(PortalError):
        require_fresh(boundary, boundary)
    require_fresh(boundary, boundary - timedelta(microseconds=1))


def test_external_utc_crosses_beijing_business_day():
    assert to_beijing_naive(datetime(2026, 9, 30, 16, tzinfo=timezone.utc)) == datetime(2026, 10, 1)


def check_inventory(observation, **kwargs):
    params = dict(now=datetime(2026, 10, 1), max_age_seconds=120,
                  quantity=2, inventory_unit="g", conversion_factor=Decimal("20"),
                  safety_buffer=Decimal("5"))
    params.update(kwargs)
    return validate_observation(observation, **params)


def test_inventory_uses_decimal_and_standard_unit_conversion():
    observation = InventoryObservation(Decimal("45"), "g", datetime(2026, 9, 30, 23, 59), "mirror-run-1")
    check_inventory(observation)
    with pytest.raises(PortalError) as error:
        check_inventory(observation, quantity=3)
    assert error.value.code == "STOCK_CHANGED"


@pytest.mark.parametrize("change", ["stale", "future", "float", "negative", "unit", "source"])
def test_untrusted_stock_never_becomes_available(change):
    data = dict(quantity=Decimal("100"), unit="g", observed_at=datetime(2026, 9, 30, 23, 59), source="run-1")
    if change == "stale":
        data["observed_at"] -= timedelta(minutes=10)
    if change == "future":
        data["observed_at"] += timedelta(minutes=10)
    if change == "float":
        data["quantity"] = 100.0
    if change == "negative":
        data["quantity"] = Decimal("-1")
    if change == "unit":
        data["unit"] = "pieces"
    if change == "source":
        data["source"] = ""
    with pytest.raises(PortalError) as error:
        check_inventory(InventoryObservation(**data))
    assert error.value.code == "INVENTORY_UNAVAILABLE"
