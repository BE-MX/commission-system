from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.domestic import constants as C, shipment_service as ships, receipt_service
from app.domestic.models import DomesticCustomer, DomesticCustomerLedger, DomesticOrder
from app.domestic.shipment_models import DomesticShipment, DomesticShipmentUnit
from app.domestic.shipment_schemas import ShipmentReceive
from tests.test_domestic_delivery import context, complete, ship, receipt
from tests.test_domestic_conditional_routing import conditional_route, conditional_order


@pytest.mark.parametrize('quantity', [3, 20])
def test_cancel_restores_units_preserves_history_and_balance(db, context, quantity):
    ctx = context
    complete(db, ctx, 20)
    batch, payload = ship(db, ctx, quantity)
    order = db.get(DomesticOrder, ctx.item.order_id)
    customer = db.get(DomesticCustomer, order.customer_id)
    before = (customer.balance, order.charged_amount, db.query(DomesticCustomerLedger).count())
    result = ships.cancel_shipment(db, batch['id'], ctx.worker.id)
    assert result['cancelled_at'] and result['cancelled_by'] == ctx.worker.id
    assert result['items'] == batch['items']
    assert result['unpaid_amount'] == 0
    assert db.query(DomesticShipmentUnit).count() == 0
    assert ctx.item.status == C.ITEM_DONE and order.status == C.ORDER_DONE
    assert ctx.item.ship_time is None and ctx.item.ship_weight is None
    assert ships.candidate_rows(db, customer.id, ctx.worker.id)[0]['available_qty'] == 20
    assert ships.customer_summary(db, customer.id)['transit_unpaid_amount'] == 0
    assert ships.customer_summary(db, customer.id)['unshipped_amount'] == 2000
    assert (customer.balance, order.charged_amount, db.query(DomesticCustomerLedger).count()) == before
    assert ships.cancel_shipment(db, batch['id'], ctx.worker.id)['cancelled_at'] == result['cancelled_at']
    assert ships.create_shipment(db, payload, ctx.worker.id)['cancelled_at']
    resent, _ = ship(db, ctx, quantity, key='reship-cancelled')
    assert resent['items'][0]['unit_codes'] == batch['items'][0]['unit_codes']
    assert db.query(DomesticShipment).count() == 2


@pytest.mark.parametrize('blocker', ['received', 'allocation', 'other_user', 'terminated'])
def test_cancel_rejects_unsafe_batches(db, context, blocker):
    ctx = context
    complete(db, ctx, 3)
    batch, _ = ship(db, ctx)
    uid = ctx.worker.id
    if blocker == 'received':
        ships.confirm_received(db, batch['id'], ShipmentReceive(received_date=date(2026, 10, 1)), uid)
    elif blocker == 'allocation':
        receipt(db, ctx, 100, [{'shipment_id': batch['id'], 'amount': 100}], 'cancel-linked-receipt')
    elif blocker == 'other_user':
        uid += 9999
    else:
        db.get(DomesticOrder, ctx.item.order_id).status = C.ORDER_TERMINATED
        db.commit()
    with pytest.raises(ValueError):
        ships.cancel_shipment(db, batch['id'], uid)
    db.rollback()
    assert db.get(DomesticShipment, batch['id']).cancelled_at is None
    assert db.query(DomesticShipmentUnit).count() == 3


def test_cancelled_batch_cannot_receive_or_allocate(db, context):
    ctx = context
    complete(db, ctx, 3)
    batch, _ = ship(db, ctx)
    ships.cancel_shipment(db, batch['id'], ctx.worker.id)
    with pytest.raises(ValueError, match='已取消'):
        ships.confirm_received(db, batch['id'], ShipmentReceive(received_date=date(2026, 10, 1)), ctx.worker.id)
    db.rollback()
    with pytest.raises(ValueError, match='已取消'):
        receipt(db, ctx, 100, [{'shipment_id': batch['id'], 'amount': 100}], 'cancelled-receipt')


def test_confirm_receive_does_not_deduct_again(db, context):
    ctx = context
    complete(db, ctx, 3)
    batch, _ = ship(db, ctx)
    customer = db.get(DomesticCustomer, batch['customer_id'])
    before = (customer.balance, db.query(DomesticCustomerLedger).count())
    for _ in range(2):
        ships.confirm_received(db, batch['id'], ShipmentReceive(received_date=date(2026, 10, 1)), ctx.worker.id)
    db.refresh(customer)
    assert (customer.balance, db.query(DomesticCustomerLedger).count()) == before


def test_cancel_keeps_other_batch_and_recomputes_delivery_fields(db, context):
    from app.domestic.shipment_schemas import ShipmentCreate
    ctx = context
    complete(db, ctx, 6)
    customer_id = db.get(DomesticOrder, ctx.item.order_id).customer_id
    batches = []
    for key, day, weight in [('first', 1, 50), ('second', 2, 80)]:
        batches.append(ships.create_shipment(db, ShipmentCreate(customer_id=customer_id,
            request_id=f'cancel-{key}', ship_time=datetime(2026, 10, day, 10),
            items=[{'item_id': ctx.item.id, 'quantity': 3, 'ship_weight': weight}]), ctx.worker.id))
    ships.cancel_shipment(db, batches[1]['id'], ctx.worker.id)
    assert ctx.item.ship_time == datetime(2026, 10, 1, 10)
    assert ctx.item.ship_weight == Decimal(50)
    assert db.query(DomesticShipmentUnit).count() == 3
    assert ships.customer_summary(db, customer_id)['transit_unpaid_amount'] == 300
    assert ships.shipped_item_amount(db, ctx.item) == 300
    assert ships.candidate_rows(db, customer_id, ctx.worker.id)[0]['available_qty'] == 3


@pytest.mark.parametrize('utc_hour,minute,expected_day', [(15, 59, 26), (16, 1, 27)])
def test_cancel_timestamp_is_beijing_across_midnight(db, context, monkeypatch, utc_hour, minute, expected_day):
    from app.core import time as clock
    ctx = context
    complete(db, ctx, 3)
    batch, _ = ship(db, ctx)
    instant = datetime(2026, 10, 26, utc_hour, minute, tzinfo=timezone.utc)
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            # Simulate a UTC host; callers must explicitly request Beijing.
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
    monkeypatch.setattr(clock, 'datetime', FrozenDateTime)
    result = ships.cancel_shipment(db, batch['id'], ctx.worker.id)
    assert result['cancelled_at'] == datetime(2026, 10, expected_day, (utc_hour + 8) % 24, minute)
    assert result['cancelled_at'].tzinfo is None


def test_cancel_api_permissions_and_rollback(db, context, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.domestic.shipment_router import router
    from app.domestic import progress_service
    ctx = context
    complete(db, ctx, 3)
    batch, _ = ship(db, ctx)
    identity = {'sub': str(ctx.worker.id), 'roles': [], 'permissions': ['domestic:read']}
    app = FastAPI()
    app.include_router(router, prefix='/api/domestic')
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: identity
    client = TestClient(app, raise_server_exceptions=False)
    url = f"/api/domestic/shipments/{batch['id']}/cancel"
    assert client.post(url).status_code == 403
    identity['permissions'] = ['domestic:admin']
    identity['sub'] = str(ctx.worker.id + 9999)
    assert client.post(url).status_code == 400
    identity['sub'] = str(ctx.worker.id)
    original = progress_service.sync_order_status
    def fail(*args):
        raise RuntimeError('simulated transaction failure')
    monkeypatch.setattr(progress_service, 'sync_order_status', fail)
    assert client.post(url).status_code == 500
    assert db.get(DomesticShipment, batch['id']).cancelled_at is None
    assert db.query(DomesticShipmentUnit).count() == 3
    monkeypatch.setattr(progress_service, 'sync_order_status', original)
    result = client.post(url)
    assert result.status_code == 200 and result.json()['data']['cancelled_at']


def test_original_item_ship_action_can_reship_after_cancellation(db, context):
    from app.domestic import order_service
    from app.domestic.schemas import ItemShipRequest
    ctx = context
    complete(db, ctx, 20)
    for day in [1, 2, 3]:
        order_service.ship_item(db, ctx.item.id,
            ItemShipRequest(ship_time=datetime(2026, 10, day, 10), ship_weight=50), ctx.worker.id)
        assert ctx.item.status == C.ITEM_SHIPPED
        assert db.query(DomesticShipmentUnit).count() == 20
        batch = db.query(DomesticShipment).order_by(DomesticShipment.id.desc()).first()
        assert batch.cancelled_at is None and batch.ship_time.day == day
        assert db.query(DomesticShipment).count() == day
        ships.cancel_shipment(db, batch.id, ctx.worker.id)
    assert len({s.request_id for s in db.query(DomesticShipment).all()}) == 3


def test_original_item_ship_cycles_advance_when_older_batch_cancelled_last(db, context):
    from app.domestic import order_service
    from app.domestic.schemas import ItemShipRequest
    ctx = context
    complete(db, ctx, 20)
    older, _ = ship(db, ctx, 5, key='cancel-older-first')
    newer, _ = ship(db, ctx, 5, key='cancel-newer-second')
    for batch in [newer, older]:
        ships.cancel_shipment(db, batch['id'], ctx.worker.id)
        order_service.ship_item(db, ctx.item.id,
            ItemShipRequest(ship_time=datetime(2026, 10, 3, 10), ship_weight=50), ctx.worker.id)
        assert ctx.item.status == C.ITEM_SHIPPED
        assert db.query(DomesticShipmentUnit).count() == 20
    assert db.query(DomesticShipment).count() == 4
