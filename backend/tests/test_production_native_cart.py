"""Native cart identity, material plans and atomic idempotent order creation."""
from decimal import Decimal
import pytest
from sqlalchemy import select
from app.core.config import get_settings
from app.semifinished.models import CartPlan, SemifinishedOrder
from app.stock.models import ProductionCart, ProductionOrder, ProductionOrderItem
from app.stock import production_cart_service as cart
from app.stock.local_cart_service import create_order
from app.stock.schemas import OrderCreateRequest
from tests.test_inventory_local import stock
from tests.test_invoice_commerce import buyer
from tests.test_semifinished import _material


def test_cart_uses_native_snapshot_and_replays_after_consumption(db, stock, buyer, monkeypatch):
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "local")
    sku, _ = stock
    customer, user = buyer
    user_id = int(user["sub"])
    material = _material(db)
    db.add(ProductionCart(user_id=user_id, product_id=999, product_name="Old", order_qty=99))
    db.flush()
    item = cart.add_or_update_cart(db, user_id, f"ark:sku:{sku.id}", "Forged", "Forged", "Forged", 6,
        "native", [{"material_id": material.id, "quantity_grams": "60"}])
    assert cart.get_cart_count(db, user_id) == 1
    assert cart.get_cart_list(db, user_id)[0]["product_name"] == "Hair"
    assert cart.update_cart_item(db, user_id, item["id"], 3, "updated")
    assert db.scalar(select(CartPlan.quantity_grams).where(CartPlan.production_cart_id == item["id"])) == Decimal("30")
    body = OrderCreateRequest(cart_ids=[item["id"]], batch_no="NATIVE-CART", request_key="cart-order", is_urgent=True)
    result = create_order(db, body, user)
    db.commit()
    assert result["transaction_mode"] == "local" and "semifinished_order_id" in result
    assert cart.get_cart_count(db, user_id) == 0
    assert create_order(db, body, user) == result
    with pytest.raises(ValueError, match="幂等键"):
        create_order(db, body.model_copy(update={"remark": "changed"}), user)
    line = db.scalar(select(ProductionOrderItem).where(ProductionOrderItem.order_id == result["order_id"]))
    assert line.local_sku_id == sku.id and line.order_qty == 3 and line.is_urgent == 1
    assert db.scalar(select(SemifinishedOrder).where(SemifinishedOrder.production_order_id == result["order_id"])) is not None
    assert db.scalar(select(ProductionCart.id).where(ProductionCart.product_id == 999)) is not None


def test_failed_material_order_restores_cart_and_production(db, stock, buyer, monkeypatch):
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "local")
    sku, _ = stock
    _, user = buyer
    material = _material(db)
    item = cart.add_or_update_cart(db, int(user["sub"]), f"ark:sku:{sku.id}", "", None, None, 1, None,
        [{"material_id": material.id, "quantity_grams": "10"}])
    material.status = "inactive"
    db.flush()
    with pytest.raises(ValueError, match="半成品"):
        create_order(db, OrderCreateRequest(cart_ids=[item["id"]], batch_no="FAIL", request_key="failed-order"), user)
    assert db.get(ProductionCart, item["id"]) is not None
    assert db.scalar(select(ProductionOrder.id)) is None
