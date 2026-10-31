"""Historical acceptance is acknowledged; only future acceptance adds stock."""
from datetime import date, datetime
from sqlalchemy import select, func
import pytest
from app.commerce_migration import order_service, production_service as service
from app.commerce_migration.order_schemas import OrderOpeningManifest
from app.commerce_migration.production_schemas import ProductionOpeningManifest
from app.invoice.models import Invoice
from app.stock.models import ProductionOrder, ProductionOrderItem
from app.production.local_models import ProductionSupply, ProductionEvent
from app.production import local_service
from app.production.local_schemas import ReceiptCreate
from app.inventory.models import StockLedger, StockBalance
from tests.test_commerce_order_opening import inputs as order_inputs
from tests.test_invoice_commerce import buyer
from tests.test_inventory_local import stock


def inputs(db, stock, buyer):
    raw = order_inputs(db, buyer)
    raw['orders'][0]['production_ids'] = ['OLD-PROD']
    raw['orders'][0]['items'][0]['production_pending_quantity'] = 4
    body = OrderOpeningManifest.model_validate(raw)
    order_mapping = order_service.apply_manifest(db, body, buyer[1])['orders'][0]
    invoice = db.get(Invoice, order_mapping['invoice_id'])
    old_order = ProductionOrder(order_no='ORIGINAL-PROD', batch_no='ORIGINAL-BATCH', status=2, created_by=int(buyer[1]['sub']))
    db.add(old_order); db.flush()
    old_item = ProductionOrderItem(order_id=old_order.id, product_name='Original production name', model='Original model',
        order_qty=10, received_qty=6, status=2)
    db.add(old_item); db.flush()
    source = body.orders[0].items[0]
    raw = dict(batch_key='production-opening', source='okki', tenant='tenant-A', cutover_date=date(2026, 10, 3),
        evidence_sha256='e'*64, review_reference='Synthetic complete factory closing', productions=[dict(
            source_production_id='OLD-PROD', existing_order_id=old_order.id, order_no=old_order.order_no,
            batch_no=old_order.batch_no, source_status=2, remark=None, items=[dict(source_item_id='OLD-PROD-LINE',
                existing_item_id=old_item.id, catalog_record_id=source.catalog_record_id, local_sku_id=source.local_sku_id,
                product_name=old_item.product_name, model=old_item.model, spec_info=None, process_route_id=None,
                order_quantity=10, completed_quantity=10, received_quantity=6, source_status=2, terminated=False,
                is_urgent=False, expected_delivery_date=None, remark=None, materials=[], supplies=[dict(
                    order_binding_record_id=order_mapping['record_id'], source_item_id='OLD-ITEM', quantity=10,
                    received_quantity=6, released_quantity=0)])])])
    return raw, invoice, old_order, old_item


def test_factory_opening_keeps_original_full_quantity_and_future_receive_is_only_new_stock(db, stock, buyer):
    raw, invoice, old_order, old_item = inputs(db, stock, buyer)
    body = ProductionOpeningManifest.model_validate(raw)
    assert service.preview(db, body)['can_apply']
    result = service.apply_manifest(db, body, buyer[1]); db.commit()
    assert result['productions'][0]['production_order_id'] == old_order.id
    assert result['productions'][0]['items'][0]['production_item_id'] == old_item.id
    assert old_order.transaction_mode == 'opening' and old_item.received_qty == 6 and old_item.order_qty == 10
    assert old_item.completed_qty == 10 and old_item.supplied_qty == 10 and old_item.supplied_received_qty == 6
    assert invoice.items[0].production_pending_quantity == 4 and db.scalar(select(func.count()).select_from(StockLedger)) == 0
    assert service.apply_manifest(db, body, buyer[1]) == result
    assert service.apply_manifest(db, body.model_copy(update={'batch_key': 'factory-repeat'}), buyer[1])['productions'] == result['productions']
    assert invoice.items[0].production_pending_quantity == 4
    with pytest.raises(Exception) as exc:
        local_service.get_item(db, old_item.id)
    assert getattr(exc.value, 'status_code', None) == 404
    # Gate manipulation isolates the factory acceptance primitive. It is not
    # evidence for the still-separate complete activation checks.
    old_order.transaction_mode, invoice.commerce_status = 'local', 'partially_shipped'
    invoice.items[0].stock_shipped_quantity = 6
    supply = db.scalars(select(ProductionSupply)).one()
    command = ReceiptCreate(request_key='new-receive', expected_version=old_item.local_version, quantity=4,
        warehouse_id=stock[1][0].id, quality='sellable', reason='New acceptance after opening',
        allocations=[dict(supply_id=supply.id, quantity=4)])
    local_service.receive(db, old_item.id, command, buyer[1]); db.commit()
    assert old_item.received_qty == old_item.supplied_received_qty == supply.received_quantity == 10
    assert invoice.items[0].production_pending_quantity == 0 and invoice.items[0].stock_reserved_quantity == 4
    balance = db.scalars(select(StockBalance)).one()
    assert balance.on_hand == balance.reserved == 4
    assert db.scalar(select(func.count()).select_from(StockLedger)) == 2


def test_cross_factory_supply_cap_rejects_before_any_counter_changes(db, stock, buyer):
    from copy import deepcopy
    raw, invoice, old_order, old_item = inputs(db, stock, buyer)
    second = deepcopy(raw['productions'][0])
    second.update(source_production_id='OTHER-PROD', existing_order_id=None, order_no='OTHER-PROD', batch_no='OTHER-BATCH')
    second['items'][0].update(existing_item_id=None)
    # The source whole-order manifest does not declare this second factory.
    raw['productions'].append(second)
    body = ProductionOpeningManifest.model_validate(raw)
    assert not service.preview(db, body)['can_apply']
    with pytest.raises(ValueError):
        service.apply_manifest(db, body, buyer[1])
    db.commit()
    assert old_order.transaction_mode == 'legacy' and invoice.items[0].production_pending_quantity == 0
    assert db.scalar(select(func.count()).select_from(ProductionSupply)) == 0


def test_factory_opening_preserves_completed_worker_progress_ids_and_timestamps(db, stock, buyer):
    from app.production.models import Process, ProcessRoute, ProcessRouteStep, OrderProductProcessProgress
    raw, _, old_order, old_item = inputs(db, stock, buyer)
    process = Process(name='Original process')
    route = ProcessRoute(name='Original route')
    db.add_all([process, route]); db.flush()
    db.add(ProcessRouteStep(route_id=route.id, process_id=process.id, step_order=1))
    old_item.process_route_id = route.id
    old = OrderProductProcessProgress(order_product_id=old_item.id, process_id=process.id, route_id=route.id,
        step_order=1, status=1, completed_at=datetime(2026, 10, 2, 15), completed_by_user_id=int(buyer[1]['sub']),
        completed_by_wx_id='original-worker-wx')
    db.add(old); db.flush()
    raw['productions'][0]['items'][0].update(process_route_id=route.id, progress=[dict(existing_progress_id=old.id,
        process_id=process.id, step_order=1, status=1, completed_at=old.completed_at,
        completed_by_user_id=old.completed_by_user_id, completed_by_wx_id=old.completed_by_wx_id)])
    source = ProductionOpeningManifest.model_validate(raw)
    assert service.preview(db, source)['can_apply']
    identity, timestamp = old.id, old.completed_at
    service.apply_manifest(db, source, buyer[1]); db.commit()
    assert db.scalars(select(OrderProductProcessProgress)).one().id == identity
    assert old.completed_at == timestamp and old.completed_by_wx_id == 'original-worker-wx' and old.status == 1
    from app.production.report_service import init_order_product_progress
    with pytest.raises(ValueError, match='不可重建'):
        init_order_product_progress(db, old_item.id, force=True)
    assert old.id == identity and old.completed_at == timestamp


def test_new_historical_factory_route_cannot_invent_pending_progress_for_completed_goods(db, stock, buyer):
    from app.production.models import Process, ProcessRoute, ProcessRouteStep
    raw, _, old_order, old_item = inputs(db, stock, buyer)
    process, route = Process(name='Reviewed process'), ProcessRoute(name='Reviewed route')
    db.add_all([process, route]); db.flush()
    db.add(ProcessRouteStep(route_id=route.id, process_id=process.id, step_order=1)); db.flush()
    raw['productions'][0].update(existing_order_id=None, order_no='NEW-ARCHIVE', batch_no='NEW-ARCHIVE')
    raw['productions'][0]['items'][0].update(existing_item_id=None, process_route_id=route.id)
    body = ProductionOpeningManifest.model_validate(raw)
    assert not service.preview(db, body)['can_apply']
    with pytest.raises(ValueError, match='完整核验路线'):
        service.apply_manifest(db, body, buyer[1])
    db.commit()
    assert old_order.transaction_mode == 'legacy'


def test_legacy_scanner_rechecks_current_native_owner_after_stale_item_discovery(db, stock, buyer, monkeypatch):
    from sqlalchemy import update
    from sqlalchemy.orm import Query
    from app.production import report_service
    raw, _, old_order, old_item = inputs(db, stock, buyer)
    old_order.status, old_item.status = 0, 0
    db.flush()
    sku_id = raw['productions'][0]['items'][0]['local_sku_id']
    original = Query.get
    def transition(query, identity):
        item = original(query, identity)
        if item is old_item:
            assert item.local_sku_id is None
            # Preserve the discovered old identity-map object. The locked
            # current read must see the ownership installed after discovery.
            db.execute(update(ProductionOrderItem).where(ProductionOrderItem.id == old_item.id).values(local_sku_id=sku_id)
                .execution_options(synchronize_session=False))
            db.execute(update(ProductionOrder).where(ProductionOrder.id == old_order.id).values(transaction_mode='opening')
                .execution_options(synchronize_session=False))
        return item
    monkeypatch.setattr(Query, 'get', transition)
    result = report_service.handle_production_report(db, report_service.generate_qr_data(old_item.id), 'old-wx')
    assert not result['success'] and '本地生产' in result['message']
    assert old_item.local_sku_id == sku_id and old_order.transaction_mode == 'opening'


def test_pure_stock_factory_has_explicit_activation_and_only_future_acceptance_adds_inventory(db, stock, buyer):
    from app.commerce_migration import activation_service, inventory_service
    from app.commerce_migration.activation_schemas import ActivationManifest
    from app.commerce_migration.inventory_schemas import InventoryOpeningManifest
    raw, invoice, old_order, old_item = inputs(db, stock, buyer)
    raw['productions'][0]['items'][0]['supplies'] = []
    result = service.apply_manifest(db, ProductionOpeningManifest.model_validate(raw), buyer[1])['productions'][0]
    command = ActivationManifest(request_key='enable-original-stock-factory', business_date=date(2026, 10, 3),
        productions=[dict(production_opening_record_id=result['record_id'], items=[dict(production_item_id=old_item.id,
            expected_version=old_item.local_version)])])
    assert not activation_service.preview(db, command)['can_activate']
    inventory_service.apply_manifest(db, InventoryOpeningManifest(batch_key='factory-physical-closing', source='physical', tenant='warehouse',
        cutover_date=date(2026, 10, 3), evidence_sha256='f'*64, review_reference='Synthetic goods closing after historical movements',
        stocks=[dict(external_id='factory-closing', mode='initialize', warehouse_id=stock[1][0].id, local_sku_id=old_item.local_sku_id,
            quality='sellable', on_hand=0, reserved=0)], materials=[]), buyer[1])
    assert activation_service.preview(db, command)['can_activate']
    activated = activation_service.activate(db, command, buyer[1]); db.commit()
    assert activated['invoices'] == [] and old_order.transaction_mode == 'local' and invoice.commerce_status == 'opening'
    assert db.scalars(select(StockBalance)).one().on_hand == 0
    local_service.receive(db, old_item.id, ReceiptCreate(request_key='factory-only-future-receive', expected_version=old_item.local_version,
        warehouse_id=stock[1][0].id, quantity=4, quality='sellable', reason='New verified acceptance', allocations=[]), buyer[1]); db.commit()
    assert old_item.received_qty == 10 and db.scalars(select(StockBalance)).one().on_hand == 4
    assert activation_service.activate(db, command, buyer[1]) == activated


def test_terminated_original_factory_cannot_hide_completed_unaccepted_goods(db, stock, buyer):
    from pydantic import ValidationError
    raw, _, _, _ = inputs(db, stock, buyer)
    raw['productions'][0]['items'][0].update(source_status=1, terminated=True, supplies=[])
    with pytest.raises(ValidationError, match='已完工未验收'):
        ProductionOpeningManifest.model_validate(raw)
