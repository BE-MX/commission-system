"""Manufacturing, warehouse acceptance and material issue are distinct facts."""
from decimal import Decimal
import pytest
from sqlalchemy import select
from app.production import local_service as service
from app.production.local_schemas import ProductionCreate, ProductionLine, QuantityCommand, SupplyCreate, ReceiptCreate, ReceiptAllocation, MaterialCommand
from app.production.local_models import ProductionEvent
from app.stock.models import ProductionOrderItem
from app.inventory.models import StockBalance
from app.semifinished.models import SemifinishedMaterial, InventoryBalance, InventoryLedger
from app.invoice.commerce_service import create_draft, confirm
from tests.test_invoice_commerce import buyer, draft, action
from tests.test_inventory_local import stock


def create(db, stock, buyer, quantity=5):
    sku, _ = stock
    _, user = buyer
    row = service.create(db, ProductionCreate(request_key="create-production", batch_no="P-01",
        items=[ProductionLine(local_sku_id=sku.id, quantity=quantity)]), user)
    return row, db.scalar(select(ProductionOrderItem).where(ProductionOrderItem.order_id == row.id))


def quantity(key, version, count):
    return QuantityCommand(request_key=key, expected_version=version, quantity=count, reason="test")


def test_partial_completion_does_not_create_stock_and_partial_receipt_is_atomic(db, stock, buyer):
    _, user = buyer
    _, (wh, _) = stock
    order, item = create(db, stock, buyer)
    service.complete(db, item.id, quantity("complete-3", 1, 3), user)
    assert item.completed_qty == 3 and item.received_qty == 0
    assert not db.scalars(select(StockBalance)).all()
    body = ReceiptCreate(request_key="receive-2", expected_version=2, quantity=2, reason="QC accepted", warehouse_id=wh.id)
    service.receive(db, item.id, body, user)
    service.receive(db, item.id, body, user)
    assert item.received_qty == 2 and db.scalar(select(StockBalance.on_hand)) == 2
    assert service.in_transit(db)[0]["in_transit_quantity"] == 3
    with pytest.raises(ValueError, match="完工"):
        service.receive(db, item.id, body.model_copy(update={"request_key": "too-many", "expected_version": 3, "quantity": 2}), user)
    service.complete(db, item.id, quantity("complete-2", 3, 2), user)
    assert order.status == 2 and item.received_qty == 2
    assert service.in_transit(db)[0]["in_transit_quantity"] == 3
    service.receive(db, item.id, body.model_copy(update={"request_key": "receive-3", "expected_version": 4, "quantity": 3}), user)
    assert item.received_qty == 5 and service.in_transit(db) == []
    assert db.scalar(select(StockBalance.on_hand)) == 5


def test_production_supply_two_orders_receipt_reserves_only_allocated_quantity(db, stock, buyer):
    customer, user = buyer
    sku, (wh, _) = stock
    _, item = create(db, stock, buyer)
    invoices = []
    for index, count in enumerate([3, 2]):
        invoice = create_draft(db, draft(customer, user, sku, request_key=f"order-{index}", order_type="production",
            items=[dict(local_sku_id=sku.id, quantity=count, price_per_piece=10)]), user)
        confirm(db, invoice.id, action(f"confirm-{index}", 1), user)
        invoices.append(invoice)
    supplies = []
    for index, invoice in enumerate(invoices):
        supplies.append(service.link_supply(db, item.id, SupplyCreate(request_key=f"supply-{index}", expected_version=item.local_version,
            invoice_item_id=invoice.items[0].id, quantity=invoice.items[0].quantity, reason="Supply order"), user))
    assert [invoice.items[0].production_pending_quantity for invoice in invoices] == [3, 2]
    service.complete(db, item.id, quantity("done", item.local_version, 5), user)
    service.receive(db, item.id, ReceiptCreate(request_key="receive", expected_version=item.local_version,
        warehouse_id=wh.id, quantity=5, reason="accepted", allocations=[
            ReceiptAllocation(supply_id=supplies[0].id, quantity=3), ReceiptAllocation(supply_id=supplies[1].id, quantity=2)]), user)
    assert [invoice.items[0].production_pending_quantity for invoice in invoices] == [0, 0]
    assert [invoice.items[0].stock_reserved_quantity for invoice in invoices] == [3, 2]
    balance = db.scalar(select(StockBalance))
    assert balance.on_hand == balance.reserved == 5


def test_material_issue_return_loss_preserves_stock_and_retry(db, stock, buyer):
    _, user = buyer
    _, item = create(db, stock, buyer)
    material = SemifinishedMaterial(material_code="M1", size="20", color_code="Black", color_key="black")
    db.add(material)
    db.flush()
    balance = InventoryBalance(material_id=material.id, on_hand_grams=100, reserved_grams=0)
    db.add(balance)
    db.flush()
    def body(key, grams):
        return MaterialCommand(request_key=key, expected_version=item.local_version, material_id=material.id,
                               quantity_grams=grams, reason="Actual warehouse movement")
    issue = body("issue", 20)
    service.material(db, item.id, "issue", issue, user)
    service.material(db, item.id, "issue", issue, user)
    service.material(db, item.id, "return", body("return", 5), user)
    service.material(db, item.id, "loss", body("loss", 2), user)
    assert balance.on_hand_grams == Decimal("85")
    assert sum(db.scalars(select(InventoryLedger.quantity_grams))) == Decimal("-15")
    with pytest.raises(ValueError, match="领料"):
        service.material(db, item.id, "return", body("excess-return", 14), user)
    assert balance.on_hand_grams == Decimal("85")
    assert len(db.scalars(select(ProductionEvent)).all()) == 4


def test_scanned_final_step_completes_manufacturing_but_never_receives_stock(db, stock, buyer):
    from app.auth.models import ArkUser
    from app.production.models import Process, ProcessRoute, ProcessRouteStep, UserProcessBinding, OrderProductProcessProgress
    from app.production.report_service import generate_qr_data, handle_production_report
    from app.mini import service as mini
    sku, _ = stock
    _, user = buyer
    worker = db.get(ArkUser, int(user["sub"]))
    worker.wx_id = "factory-worker"
    process = Process(name="Final QC")
    route = ProcessRoute(name="Local route")
    db.add_all([process, route])
    db.flush()
    db.add_all([ProcessRouteStep(route_id=route.id, process_id=process.id, step_order=1),
                UserProcessBinding(user_id=worker.id, process_id=process.id)])
    db.flush()
    order = service.create(db, ProductionCreate(request_key="routed", batch_no="ROUTED",
        items=[ProductionLine(local_sku_id=sku.id, quantity=5, process_route_id=route.id)]), user)
    item = db.scalar(select(ProductionOrderItem).where(ProductionOrderItem.order_id == order.id))
    assert not handle_production_report(db, generate_qr_data(item.id), worker.wx_id)["success"]
    progress = db.scalar(select(OrderProductProcessProgress).where(OrderProductProcessProgress.order_product_id == item.id))
    result = mini.submit_report(db, progress.id, item.id, worker)
    assert result["success"] and result["all_done"]
    assert item.completed_qty == 5 and item.received_qty == 0 and order.status == 2
    assert not db.scalars(select(StockBalance)).all()
    assert mini.submit_report(db, progress.id, item.id, worker)["success"]
    assert mini.get_today_history(db, worker.id)["today_count"] == 1
    assert mini.revoke_report(db, progress.id, worker)["success"]
    assert item.completed_qty == 0 and order.status == 0
    assert mini.submit_report(db, progress.id, item.id, worker)["success"]
    _, (wh, _) = stock
    service.receive(db, item.id, ReceiptCreate(request_key="accept-scanned", expected_version=item.local_version,
        quantity=5, warehouse_id=wh.id, reason="accepted"), user)
    assert not mini.revoke_report(db, progress.id, worker)["success"]
    assert item.completed_qty == item.received_qty == 5


def test_legacy_setters_cannot_bypass_local_production_ledger(db, stock, buyer):
    from app.stock import production_order_service as legacy
    order, item = create(db, stock, buyer)
    operations = [lambda: legacy.update_item_received(db, item.id, 5),
                  lambda: legacy.update_item_status(db, item.id, 2),
                  lambda: legacy.update_order_item(db, item.id, order_qty=1),
                  lambda: legacy.delete_order_item(db, item.id),
                  lambda: legacy.update_order(db, order.id, status=2),
                  lambda: legacy.delete_order(db, order.id)]
    for operation in operations:
        with pytest.raises(ValueError, match="本地生产"):
            operation()
    assert item.received_qty == item.completed_qty == 0


def test_pending_supply_blocks_double_reservation_and_order_cancel(db, stock, buyer):
    from app.inventory.reservation_service import reserve_line
    from app.inventory.service import post_document
    from app.invoice.commerce_service import cancel
    from tests.test_inventory_local import command
    customer, user = buyer
    sku, (wh, _) = stock
    _, item = create(db, stock, buyer)
    invoice = create_draft(db, draft(customer, user, sku, order_type="production",
        items=[dict(local_sku_id=sku.id, quantity=5, price_per_piece=10)]), user)
    confirm(db, invoice.id, action("confirmed", 1), user)
    link = service.link_supply(db, item.id, SupplyCreate(request_key="link", expected_version=1,
        invoice_item_id=invoice.items[0].id, quantity=5, reason="planned"), user)
    post_document(db, command("opening", "receipt", wh, sku, 5), actor_id=None)
    with pytest.raises(ValueError, match="生产供货"):
        reserve_line(db, invoice.items[0].id, wh.id, 1, "reserve", int(user["sub"]))
    with pytest.raises(ValueError, match="生产供货"):
        cancel(db, invoice.id, action("cancel", 2), user)
    service.release_supply(db, link.id, quantity("release", item.local_version, 5), user)
    cancel(db, invoice.id, action("cancel", 2), user)
    assert invoice.commerce_status == "cancelled" and item.supplied_qty == 0


def test_terminated_production_can_return_unused_material(db, stock, buyer):
    from app.production.local_schemas import Action
    _, user = buyer
    _, item = create(db, stock, buyer)
    material = SemifinishedMaterial(material_code="RETURN", size="20", color_code="B", color_key="b")
    db.add(material)
    db.flush()
    balance = InventoryBalance(material_id=material.id, on_hand_grams=100, reserved_grams=0)
    db.add(balance)
    db.flush()
    issue = MaterialCommand(request_key="issue", expected_version=1, material_id=material.id, quantity_grams=20, reason="issued")
    service.material(db, item.id, "issue", issue, user)
    service.terminate(db, item.id, Action(request_key="terminate", expected_version=2, reason="Stopped"), user)
    service.material(db, item.id, "return", issue.model_copy(update={"request_key": "return", "expected_version": 3}), user)
    assert balance.on_hand_grams == 100 and item.status == 1
    with pytest.raises(ValueError, match="终止"):
        service.material(db, item.id, "issue", issue.model_copy(update={"request_key": "new-issue", "expected_version": 4}), user)


def test_receipt_reversal_rolls_back_if_stock_has_been_consumed(db, stock, buyer):
    from app.production.local_schemas import Action
    from app.production.local_receipt_service import reverse_receipt
    from app.inventory.service import post_document
    from tests.test_inventory_local import command
    _, user = buyer
    sku, (wh, _) = stock
    _, item = create(db, stock, buyer)
    service.complete(db, item.id, quantity("done", 1, 5), user)
    service.receive(db, item.id, ReceiptCreate(request_key="accepted", expected_version=2, quantity=5, warehouse_id=wh.id, reason="received"), user)
    event = db.scalar(select(ProductionEvent).where(ProductionEvent.action == "receive"))
    post_document(db, command("consumed", "adjustment", wh, sku, -1), actor_id=None)
    body = Action(request_key="reverse", expected_version=3, reason="Wrong acceptance")
    with pytest.raises(ValueError, match="库存"):
        reverse_receipt(db, event.id, body, user)
    assert item.received_qty == 5 and item.local_version == 3
    post_document(db, command("returned", "receipt", wh, sku, 1), actor_id=None)
    reverse_receipt(db, event.id, body, user)
    reverse_receipt(db, event.id, body, user)
    assert item.received_qty == 0 and item.completed_qty == 5
    assert db.scalar(select(StockBalance.on_hand)) == 0
