"""Local dispatch conserves cash components and requires current inspection."""
from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import select
from app.finance import service as finance_service
from app.finance.schemas import AllocationCreate
from app.invoice import commerce_service as commerce, local_fulfillment as service
from app.invoice.local_fulfillment_schemas import LocalShipmentQuote, LocalShipmentCreate, LocalShipmentAction
from app.invoice.settlement_models import Receivable, ShipmentOutbound, SettlementApplication
from app.inventory.service import post_document
from app.inventory.reservation_service import reserve_line
from app.shipping_inspection import service as inspection_service, outbound_service
from app.shipping_inspection.models import ShippingInspectionPhoto
from tests.test_finance_local import finance, payment, cmd
from tests.test_invoice_commerce import buyer, draft, action
from tests.test_inventory_local import stock, command, balance


def setup_order(db, stock, finance, *, presale=False, small=False, reserve_presale=True, day=date(2026, 10, 3), currency='USD'):
    customer, user, account = finance
    sku, (warehouse, _) = stock
    post_document(db, command("opening", "receipt", warehouse, sku, 10), actor_id=None)
    invoice = commerce.create_draft(db, draft(customer, user, sku, invoice_date=day, currency=currency, order_type="presale" if presale else "stock",
        shipping_fee=0 if presale else "1", surcharge_amount="0.01" if small else "3", internal_accessory=0,
        local_deposit_amount="0.02" if small else "21" if presale else 0,
        local_deposit_charge=0 if small else "1" if presale else 0,
        items=[dict(local_sku_id=sku.id, quantity=3, price_per_piece="0.02" if small else "30", discount_amount="-0.01" if small else 0)]), user)
    commerce.confirm(db, invoice.id, action("confirm-order", 1, warehouse.id), user)
    if presale and reserve_presale:
        reserve_line(db, invoice.items[0].id, warehouse.id, 3, "reserve", int(user["sub"]))
    batch = finance_service.register(db, payment(customer, account, currency=currency, gross_amount="100", actual_bank_fee=0, collection_date=day), user)
    finance_service.confirm(db, batch.id, cmd("confirm-payment", 1).model_copy(update={"business_date": day}), user)
    return invoice, batch, user, warehouse


def allocate(db, invoice, batch, user, target, amount, key, *, settlement=None, deposit=False, day=date(2026, 10, 3)):
    return finance_service.allocate(db, batch.id, AllocationCreate(request_key=key, expected_version=batch.version,
        invoice_id=invoice.id, receivable_id=target.id, amount=amount, business_date=day,
        settlement_id=settlement.id if settlement else None, purpose="presale_deposit" if deposit else "ordinary"), user)


def create_batch(db, invoice, user, warehouse, quantity, key, freight=0, day=date(2026, 10, 3)):
    from app.commerce_transition.models import InvoiceAuthority
    epoch = db.get(InvoiceAuthority, invoice.id).epoch
    body = LocalShipmentQuote(items=[dict(invoice_item_id=invoice.items[0].id, quantity=quantity)],
                              warehouse_id=warehouse.id, freight_amount=freight, business_date=day,
                              expected_authority_epoch=epoch)
    quote = service.quote(db, invoice.id, body, user)
    request = LocalShipmentCreate(**body.model_dump(), request_key=key, expected_version=invoice.commerce_version,
                                  quote_hash=quote["quote_hash"])
    row = service.create(db, invoice.id, request, user)
    assert service.create(db, invoice.id, request, user).id == row.id
    return row


def act(db, row, user, key, operation, **values):
    from app.commerce_transition.models import InvoiceAuthority
    values.setdefault('business_date', date(2026, 10, 3))
    values.setdefault('expected_authority_epoch', db.get(InvoiceAuthority, row.invoice_id).epoch)
    return service.act(db, row.id, LocalShipmentAction(request_key=key, expected_version=row.version,
                       reason="verified test", **values), user, operation)


def inspect(db, row, user):
    outbound = db.scalar(select(ShipmentOutbound).where(ShipmentOutbound.settlement_id == row.id))
    identity = service.record_id(outbound)
    inspection = inspection_service.get_or_create_draft(db, identity, int(user["sub"]))
    assert outbound_service.get_outbound_record(db, identity)["transaction_mode"] == "local"
    item = outbound_service.list_outbound_items(db, identity)[0]
    # Media storage is tested separately; this fixture is a registered image fact.
    db.add(ShippingInspectionPhoto(inspection_id=inspection.id, item_id=item["item_id"], file_path="test.jpg", media_type="image"))
    db.flush()
    inspection_service.submit(db, outbound_record_id=identity, user_id=int(user["sub"]), commit=False)
    return inspection


def test_normal_two_batches_use_one_freight_target_and_current_inspection(db, stock, finance):
    invoice, payment_row, user, warehouse = setup_order(db, stock, finance)
    targets = {target.kind: target for target in db.scalars(select(Receivable)).all()}
    allocate(db, invoice, payment_row, user, targets["goods"], 93, "goods")
    allocate(db, invoice, payment_row, user, targets["freight"], 1, "freight")
    first = create_batch(db, invoice, user, warehouse, 1, "first")
    assert first.quote["freight_amount"] == "0.33"
    act(db, first, user, "ready-first", "ready")
    with pytest.raises(ValueError, match="检验"):
        act(db, first, user, "missing-inspection", "ship", inspection_version=0)
    inspection = inspect(db, first, user)
    view = service.describe(db, first)
    assert view["inspection_current"] and view["inspection_version"] == inspection.edit_version
    assert view["inspection_status"] == "submitted"
    inspection.local_outbound_version += 1
    assert not service.describe(db, first)["inspection_current"]
    inspection.local_outbound_version -= 1
    act(db, first, user, "ship-first", "ship", inspection_version=inspection.edit_version)
    assert invoice.commerce_status == "partially_shipped"
    with pytest.raises(ValueError, match="完成或取消"):
        inspection_service.recall(db, inspection.id, int(user["sub"]), inspection.edit_version)
    second = create_batch(db, invoice, user, warehouse, 2, "second")
    assert second.quote["freight_amount"] == "0.67"
    act(db, second, user, "ready-second", "ready")
    inspection2 = inspect(db, second, user)
    body = LocalShipmentAction(request_key="ship-second", expected_version=second.version, reason="shipped", inspection_version=inspection2.edit_version)
    service.act(db, second.id, body, user, "ship")
    service.act(db, second.id, body, user, "ship")
    assert invoice.commerce_status == "shipped" and invoice.items[0].stock_shipped_quantity == 3
    assert balance(db, warehouse, stock[0]).on_hand == 7
    assert len(db.scalars(select(Receivable)).all()) == 2
    assert sum(app.amount for app in db.scalars(select(SettlementApplication))) == 94


def test_unreserved_presale_dispatch_reserves_available_stock_atomically_and_rolls_back_shortage(db, stock, finance):
    from app.inventory.models import StockDocument
    invoice, batch, user, warehouse = setup_order(db, stock, finance, presale=True, reserve_presale=False)
    assert invoice.items[0].stock_reserved_quantity == 0
    goods = db.scalar(select(Receivable).where(Receivable.kind == "goods"))
    allocate(db, invoice, batch, user, goods, 21, "deposit", deposit=True)
    row = create_batch(db, invoice, user, warehouse, 3, "final")
    allocate(db, invoice, batch, user, goods, 72, "balance", settlement=row)
    act(db, row, user, "ready", "ready")
    inspection = inspect(db, row, user)
    post_document(db, command("less-stock", "adjustment", warehouse, stock[0], -8), actor_id=None)
    documents_before = len(db.scalars(select(StockDocument)).all())
    with pytest.raises(ValueError, match="库存"):
        act(db, row, user, "ship", "ship", inspection_version=inspection.edit_version)
    assert invoice.items[0].stock_reserved_quantity == invoice.items[0].stock_shipped_quantity == 0
    assert row.state == "ready" and balance(db, warehouse, stock[0]).reserved == 0
    assert len(db.scalars(select(StockDocument)).all()) == documents_before
    post_document(db, command("arrived", "receipt", warehouse, stock[0], 1), actor_id=None)
    request = LocalShipmentAction(request_key="ship", expected_version=row.version, reason="verified test", inspection_version=inspection.edit_version)
    service.act(db, row.id, request, user, "ship")
    service.act(db, row.id, request, user, "ship")
    assert invoice.commerce_status == "shipped" and invoice.items[0].stock_shipped_quantity == 3
    assert invoice.items[0].stock_reserved_quantity == balance(db, warehouse, stock[0]).reserved == 0
    assert balance(db, warehouse, stock[0]).on_hand == 0


def test_presale_small_cents_use_quote_fee_plan_and_final_deposit_once(db, stock, finance):
    invoice, batch, user, warehouse = setup_order(db, stock, finance, presale=True, small=True)
    goods = db.scalar(select(Receivable).where(Receivable.kind == "goods"))
    for index in range(2):
        allocate(db, invoice, batch, user, goods, "0.01", f"deposit-{index}", deposit=True)
    first = create_batch(db, invoice, user, warehouse, 1, "first")
    assert first.quote["goods_payment_due"] == "0.02" and first.quote["goods_payment_charge"] == "0.00"
    receipt = allocate(db, invoice, batch, user, goods, "0.02", "batch-pay-1", settlement=first)
    assert receipt.bank_charge == 0
    act(db, first, user, "ready-first", "ready")
    inspection = inspect(db, first, user)
    act(db, first, user, "ship-first", "ship", inspection_version=inspection.edit_version)
    second = create_batch(db, invoice, user, warehouse, 2, "second")
    assert second.quote["deposit_applied"] == "0.02"
    receipt2 = allocate(db, invoice, batch, user, goods, "0.02", "batch-pay-2", settlement=second)
    assert receipt2.bank_charge == Decimal("0.01")
    act(db, second, user, "ready-second", "ready")
    inspection2 = inspect(db, second, user)
    act(db, second, user, "ship-second", "ship", inspection_version=inspection2.edit_version)
    assert goods.paid_amount == Decimal("0.06")
    apps = db.scalars(select(SettlementApplication)).all()
    assert sum(app.bank_charge for app in apps) == Decimal("0.01")
    assert sum(app.amount for app in apps if app.component == "deposit") == Decimal("0.02")
    with pytest.raises(ValueError, match="发货"):
        finance_service.reverse_allocation(db, receipt.id, cmd("reverse-used", receipt.version), user)


def test_unfunded_batch_and_stale_inspection_cannot_consume_stock(db, stock, finance):
    invoice, batch, user, warehouse = setup_order(db, stock, finance)
    row = create_batch(db, invoice, user, warehouse, 1, "batch")
    with pytest.raises(ValueError, match="不足"):
        act(db, row, user, "unfunded", "ready")
    assert row.state == "awaiting_payment" and not db.scalars(select(SettlementApplication)).all()
    targets = {target.kind: target for target in db.scalars(select(Receivable)).all()}
    allocate(db, invoice, batch, user, targets["goods"], 31, "goods", settlement=row)
    allocate(db, invoice, batch, user, targets["freight"], "0.33", "freight", settlement=row)
    act(db, row, user, "ready", "ready")
    inspection = inspect(db, row, user)
    with pytest.raises(ValueError, match="检验"):
        act(db, row, user, "stale", "ship", inspection_version=inspection.edit_version+1)
    assert balance(db, warehouse, stock[0]).on_hand == 10
    assert invoice.items[0].stock_shipped_quantity == 0


def test_cancelled_freight_has_finance_events_and_cannot_be_reactivated(db, stock, finance):
    from app.finance.schemas import AdjustmentCreate
    from app.finance.models import FinanceEvent
    invoice, batch, user, warehouse = setup_order(db, stock, finance, presale=True)
    goods = db.scalar(select(Receivable).where(Receivable.kind == "goods"))
    allocate(db, invoice, batch, user, goods, 21, "deposit", deposit=True)
    row = create_batch(db, invoice, user, warehouse, 1, "batch", freight=5)
    target = db.scalar(select(Receivable).where(Receivable.settlement_id == row.id))
    act(db, row, user, "cancel", "cancel")
    assert target.amount + target.adjustment_amount == 0
    events = db.scalars(select(FinanceEvent).where(FinanceEvent.receivable_id == target.id).order_by(FinanceEvent.id)).all()
    assert [(event.action, event.amount) for event in events] == [("create_freight", 5), ("adjust_receivable", -5)]
    with pytest.raises(ValueError, match="已取消"):
        finance_service.adjust_receivable(db, target.id, AdjustmentCreate(request_key="reactivate", expected_version=target.version,
            invoice_id=invoice.id, amount=1, reason="invalid", business_date=date(2026, 10, 3)), user)


def test_noncanonical_local_outbound_id_cannot_steal_inspection_identity(db, stock, finance):
    invoice, batch, user, warehouse = setup_order(db, stock, finance)
    row = create_batch(db, invoice, user, warehouse, 1, "batch")
    outbound = db.scalar(select(ShipmentOutbound).where(ShipmentOutbound.settlement_id == row.id))
    with pytest.raises(ValueError, match="完成或取消"):
        inspection_service.get_or_create_draft(db, f"local-0{outbound.id}", int(user["sub"]))
    assert inspect(db, row, user).local_outbound_id == outbound.id


def test_fulfillment_dates_cannot_go_back_and_unrelated_late_money_does_not_block(db, stock, finance):
    early, middle, late = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)
    invoice, batch, user, warehouse = setup_order(db, stock, finance, day=early)
    targets = {target.kind: target for target in db.scalars(select(Receivable)).all()}
    allocate(db, invoice, batch, user, targets["goods"], 31, "early-goods", day=early)
    allocate(db, invoice, batch, user, targets["freight"], "0.33", "early-freight", day=early)
    row = create_batch(db, invoice, user, warehouse, 1, "batch", day=early)
    allocate(db, invoice, batch, user, targets["goods"], 62, "unrelated-late", day=late)
    act(db, row, user, "ready", "ready", business_date=middle)
    assert row.state == "ready"
    with pytest.raises(ValueError, match="已有发货动作"):
        act(db, row, user, "earlier-release", "release_funding", business_date=early)
    act(db, row, user, "release", "release_funding", business_date=late)
    assert row.state == "awaiting_payment"


def test_local_notification_uses_current_customer_assignments_not_order_owner_or_mirror(db, stock, finance, monkeypatch):
    from app.auth.models import ArkUser
    from app.customer.models import CustomerAssignment
    from app.core.time import beijing_now
    from app.shipping_inspection import notification_service as notices
    invoice, batch, user, warehouse = setup_order(db, stock, finance)
    row = create_batch(db, invoice, user, warehouse, 1, "batch")
    current = ArkUser(username="current-notification-owner", real_name="Current Owner", password_hash="unused", dingtalk_id="ding-current")
    db.add(current)
    db.flush()
    assignment = CustomerAssignment(customer_id=invoice.local_customer_id, user_id=current.id, assignment_role="primary",
        assignment_status="active", assignment_source="manual", effective_from=beijing_now())
    db.add(assignment)
    db.flush()
    monkeypatch.setattr(outbound_service, "_record_columns", lambda _: pytest.fail("native notification read legacy mirror"))
    identity = service.describe(db, row)["outbound_record_id"]
    assert [person.id for person in notices.current_salespeople(db, identity)] == [current.id]
    assignment.assignment_status, assignment.effective_to = "ended", beijing_now()
    db.flush()
    assert notices.current_salespeople(db, identity) == []


def test_local_inspection_lists_and_detail_use_native_scope_without_mirrors(db, stock, finance):
    from app.shipping_inspection import local_outbound_service
    from app.shipping_inspection.router import _outbound_scope
    invoice, batch, user, warehouse = setup_order(db, stock, finance)
    row = create_batch(db, invoice, user, warehouse, 1, "batch")
    inspection = inspect(db, row, user)
    native_user = {"sub": user["sub"], "roles": [], "permissions": ["shipping_inspection:read"]}
    scope = _outbound_scope(db, native_user, local=True)
    rows, total = local_outbound_service.list_records(db, okki_user_id=scope)
    assert total == 1 and rows[0]["record_source"] == "ark_local"
    assert local_outbound_service.list_records(db, okki_user_id="ark-user:999")[1] == 0
    inspections, total = inspection_service.list_records(db, okki_user_id=scope, transaction_mode="local")
    assert total == 1 and inspections[0]["order_id"] == invoice.invoice_no
    detail = inspection_service.get_record_detail(db, inspection.id)
    assert detail["order_id"] == invoice.invoice_no and len(detail["items"]) == 1


def test_local_fulfillment_api_permission_and_native_print_contract(db, stock, finance):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.invoice.local_fulfillment_router import router
    from app.shipping_inspection.router import router as inspection_router
    from app.auth.models import ArkUser, ArkRole, ArkPermission
    invoice, batch, user, warehouse = setup_order(db, stock, finance)
    actor = db.get(ArkUser, int(user['sub']))
    role = db.scalar(select(ArkRole).where(ArkRole.name == 'super_admin'))
    if role is None:
        role = ArkRole(name='super_admin', label='Isolated native HTTP fixture')
        db.add(role)
    actor.roles.append(role)
    invoice_id, version = invoice.id, invoice.commerce_version
    body = dict(warehouse_id=warehouse.id, items=[dict(invoice_item_id=invoice.items[0].id, quantity=1)])
    db.commit()
    app = FastAPI()
    app.include_router(router, prefix="/local")
    app.include_router(inspection_router, prefix="/inspect")
    current = dict(user)
    app.dependency_overrides[get_current_user] = lambda: current
    def request_db():
        assert not (db.new or db.dirty or db.deleted)
        db.rollback()
        try:
            yield db
        finally:
            db.rollback()
    app.dependency_overrides[get_db] = request_db
    client = TestClient(app)
    quoted = client.post(f"/local/invoices/{invoice_id}/shipment-quotes", json=body)
    assert quoted.status_code == 200, quoted.text
    created = client.post(f"/local/invoices/{invoice_id}/shipments", json={**body, "request_key": "http-batch",
        "expected_version": version, "quote_hash": quoted.json()["data"]["quote_hash"]})
    assert created.status_code == 200, created.text
    row = created.json()["data"]
    response = client.get("/inspect/outbound-records", params={"transaction_mode": "local"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["total"] == 1
    permission = db.scalar(select(ArkPermission).where(ArkPermission.code == 'shipment:write'))
    if permission is None:
        permission = ArkPermission(code='shipment:write', module='shipment', action='write', label='Test shipment writer')
    restricted = ArkRole(name='native-shipment-only', label='No inventory or invoice write')
    restricted.permissions.append(permission)
    actor.roles = [restricted]
    db.commit()
    current["roles"], current["permissions"] = [], ["shipment:write"]
    denied = client.post(f"/local/shipments/{row['id']}/ship", json=dict(request_key="deny", expected_version=1, reason="test"))
    assert denied.status_code == 403
