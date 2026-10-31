"""Real reviewed whole-order adoption on the full migration schema."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import date, datetime
from threading import Barrier
from unittest.mock import patch
from sqlalchemy import select, func, event
from sqlalchemy.orm import Session
from app.auth.models import ArkUser
from app.customer.models import CustomerAccount
from app.finance.models import BankAccount
from app.finance import service as finance
from app.finance.schemas import AllocationCreate
from app.commerce_migration import fulfillment_service, inventory_service, activation_service, production_service
from app.commerce_migration.activation_schemas import ActivationManifest, ActivationSelection
from app.commerce_migration.fulfillment_schemas import FulfillmentOpeningManifest
from app.commerce_migration.inventory_schemas import InventoryOpeningManifest
from app.commerce_migration.production_schemas import ProductionOpeningManifest
from app.commerce_migration.models import MigrationRecord
from app.inventory.models import Warehouse, StockBalance, StockLedger
from app.invoice.models import Invoice
from app.invoice.settlement_models import Receivable
from app.models.commission import SyncedPayment
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto
from app.shipping_inspection import service as inspections, outbound_service, local_outbound_service
from app.shipping_inspection.print_service import with_owner_chinese_name
from app.stock.models import ProductionOrder, ProductionOrderItem
from app.production import report_service, local_service
from app.production.local_schemas import ReceiptCreate
from app.trade.projection_service import project_invoice
from app.core.time import beijing_now
from tests.test_commerce_fulfillment_opening import inputs
from tests.test_finance_local import payment, cmd
from tests.test_local_fulfillment import create_batch, act, inspect

DAY = date(2026, 10, 3)


def verify_order_opening(engine):
    from tests.test_local_migration_chain_mysql import transaction_mirror_guard
    reject, attempts = transaction_mirror_guard('lsordertest')
    event.listen(engine, 'before_cursor_execute', reject)
    try:
        with patch('httpx.get', side_effect=AssertionError('Historical adoption attempted HTTP GET')) as http_get, \
             patch('httpx.post', side_effect=AssertionError('Historical adoption attempted HTTP POST')) as http_post:
            result = _verify_order_opening(engine)
        http_get.assert_not_called()
        http_post.assert_not_called()
        assert attempts == []
        return dict(result, transaction_mirror_queries=len(attempts), external_http_calls=http_get.call_count + http_post.call_count)
    finally:
        event.remove(engine, 'before_cursor_execute', reject)


def _verify_order_opening(engine):
    with Session(engine, expire_on_commit=False) as db:
        actor = db.scalar(select(ArkUser).where(ArkUser.username == 'chain-native-seller'))
        customer = CustomerAccount(customer_code='CHAIN-CWO', display_name='Synthetic whole-order buyer',
            entity_type='registered_company', identity_status='verified', relationship_stage='active_customer',
            relationship_stage_changed_at=beijing_now(), relationship_stage_reason='synthetic-whole-order',
            record_status='active', identity_confidence=1, profile_completeness=100, profile_input_seq=1)
        db.add(customer); db.flush()
        bank = BankAccount(code='CHAIN-CWO-USD', name='Original whole-order shared bank account', currency='USD')
        db.add(bank); db.flush()
        warehouses = list(db.scalars(select(Warehouse).where(Warehouse.code.in_(['CHAIN-MAIN', 'CHAIN-OTHER'])).order_by(Warehouse.id)))
        user = dict(sub=str(actor.id), roles=['super_admin'], permissions=['invoice:write'])
        raw, invoice, cash, mapping, user = inputs(db, (None, warehouses), (customer, user, bank), tag='CWO', tenant='tenant-CWO',
            reservations=[dict(warehouse_id=warehouses[0].id, quantity=4)], existing_order=True)
        old = ShippingInspection(outbound_record_id='original-mirror-record', outbound_no='ORIGINAL-OUT', status='submitted',
            submitted_at=datetime(2026, 10, 3, 11), submitted_by=actor.id, photo_count=1)
        db.add(old); db.flush()
        photo = ShippingInspectionPhoto(inspection_id=old.id, item_id='original-media-item', file_path='original-chain.jpg', media_type='image')
        db.add(photo); db.flush()
        raw['orders'][0]['shipments'][0]['inspection_id'] = old.id
        invoice_id, inspection_id, photo_id = invoice.id, old.id, photo.id
        db.commit()
    with ExitStack() as stack:
        stale_sessions = [stack.enter_context(Session(engine)) for _ in range(4)]
        for stale in stale_sessions:
            old_inspection = stale.get(ShippingInspection, inspection_id)
            assert old_inspection.local_outbound_id is None
            assert stale.get(ShippingInspectionPhoto, photo_id).file_path == 'original-chain.jpg'
        with Session(engine) as db:
            fulfillment_service.apply_manifest(db, FulfillmentOpeningManifest.model_validate(raw), user)
            opening = InventoryOpeningManifest(batch_key='chain-whole-stock', source='physical', tenant='warehouse', cutover_date=DAY,
                evidence_sha256='f'*64, review_reference='Synthetic whole physical closing', stocks=[dict(external_id='chain-whole-bucket',
                mode='initialize', warehouse_id=warehouses[0].id, local_sku_id=db.get(Invoice, invoice_id).items[0].local_sku_id,
                quality='sellable', on_hand=10, reserved=0)], materials=[])
            inventory_service.apply_manifest(db, opening, user); db.commit()
        mutations = [
            lambda db: inspections.recall(db, inspection_id, actor.id, old_inspection.edit_version),
            lambda db: inspections.submit(db, outbound_record_id='original-mirror-record', user_id=actor.id),
            lambda db: inspections.add_photo(db, outbound_record_id='original-mirror-record', item_id=None,
                file_path='must-not-be-created.jpg', user_id=actor.id),
            lambda db: inspections.delete_photo(db, photo_id, actor.id),
        ]
        for stale, mutate in zip(stale_sessions, mutations):
            try:
                mutate(stale)
            except ValueError as exc:
                assert '完成' in str(exc)
                stale.rollback()
            else:
                raise AssertionError('Old RR inspection mutation bypassed adopted parent')
    with Session(engine) as db:
        prepared = activation_service.prepare(db, ActivationSelection(request_key='chain-enable-whole',
            record_ids=[mapping['record_id']]))
        assert prepared['report']['can_activate'], prepared['report']
        body = ActivationManifest.model_validate(prepared['command'])
    barrier = Barrier(2)
    def enable(_):
        with Session(engine) as db:
            db.scalar(select(func.count()).select_from(StockLedger))
            barrier.wait(timeout=15)
            result = activation_service.activate(db, body, user); db.commit()
            return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(enable, range(2)))
    assert results[0] == results[1]
    with Session(engine) as db:
        invoice = db.get(Invoice, invoice_id)
        sku_id = invoice.items[0].local_sku_id
        bucket = db.scalar(select(StockBalance).where(StockBalance.sku_id == sku_id, StockBalance.warehouse_id == warehouses[0].id))
        assert bucket.on_hand == 10 and bucket.reserved == invoice.items[0].stock_reserved_quantity == 4
        old = db.get(ShippingInspection, inspection_id)
        assert old.status == 'submitted' and db.get(ShippingInspectionPhoto, photo_id).file_path == 'original-chain.jpg'
        for identity in ['original-mirror-record', 'original-api-outbound', f'local-{old.local_outbound_id}']:
            header = outbound_service.get_outbound_record(db, identity)
            assert header['transaction_mode'] == 'local' and with_owner_chinese_name(db, header)['owner_name']
        batch = finance.register(db, payment(customer, bank, request_key='chain-whole-future-cash', bank_reference='chain-whole-future-bank',
            gross_amount='400', actual_bank_fee=0, collection_date=DAY), user)
        finance.confirm(db, batch.id, cmd('chain-whole-future-confirm', batch.version).model_copy(update={'business_date': DAY}), user)
        target = db.get(Receivable, mapping['receivables'][0]['receivable_id'])
        finance.allocate(db, batch.id, AllocationCreate(request_key='chain-whole-future-allocate', expected_version=batch.version,
            invoice_id=invoice.id, receivable_id=target.id, amount='400', business_date=DAY), user)
        row = create_batch(db, invoice, user, warehouses[0], 4, 'chain-whole-future-final')
        assert row.quote['goods_payment_due'] == '400.00'
        act(db, row, user, 'chain-whole-future-ready', 'ready')
        inspected = inspect(db, row, user)
        act(db, row, user, 'chain-whole-future-ship', 'ship', inspection_version=inspected.edit_version)
        db.commit()
        assert invoice.items[0].quantity == invoice.items[0].stock_shipped_quantity == 10 and invoice.total_amount == 1000
        assert invoice.internal_received == 1000 and invoice.internal_balance == 0 and bucket.on_hand == 6 and bucket.reserved == 0
        original = db.scalar(select(SyncedPayment).where(SyncedPayment.payment_id == 'CWO-PAYMENT'))
        assert original.payment_amount == 600 and original.exchange_rate == 650 and original.real_amount_rmb == 3900
        assert activation_service.activate(db, body, user) == results[0]
        db.commit()
        record = db.get(MigrationRecord, mapping['record_id'])
        assert record.snapshot['existing_invoice_id'] == invoice.id
        assert record.snapshot['existing_customer_order_id'] == mapping['customer_order_id']
        assert record.snapshot['items'][0]['existing_invoice_item_id'] == invoice.items[0].id
        assert record.snapshot['items'][0]['existing_customer_order_item_id'] == mapping['items'][0]['customer_order_item_id']
        catalog_record_id = record.snapshot['items'][0]['catalog_record_id']
        factory = ProductionOrder(order_no='CHAIN-OLD-STOCK-FACTORY', batch_no='CHAIN-OLD-STOCK-BATCH', status=2, created_by=actor.id)
        db.add(factory); db.flush()
        item = ProductionOrderItem(order_id=factory.id, product_name='Original factory product', order_qty=10, received_qty=6, status=2)
        db.add(item); db.flush()
        factory_id, factory_item_id = factory.id, item.id
        production = ProductionOpeningManifest(batch_key='chain-original-stock-factory', source='okki', tenant='tenant-CWO', cutover_date=DAY,
            evidence_sha256='e'*64, review_reference='Synthetic original stock factory', productions=[dict(source_production_id='CWO-FACTORY',
            existing_order_id=factory.id, order_no=factory.order_no, batch_no=factory.batch_no, source_status=2, remark=None,
            items=[dict(source_item_id='CWO-FACTORY-ITEM', existing_item_id=item.id, catalog_record_id=catalog_record_id,
            local_sku_id=sku_id, product_name=item.product_name, model=None, spec_info=None, process_route_id=None,
            order_quantity=10, completed_quantity=10, received_quantity=6, source_status=2, terminated=False,
            is_urgent=False, expected_delivery_date=None, remark=None, supplies=[], materials=[])])])
        db.commit()
    with Session(engine) as stale:
        stale_item = stale.get(ProductionOrderItem, factory_item_id)
        assert stale_item.local_sku_id is None
        with Session(engine) as db:
            production_mapping = production_service.apply_manifest(db, production, user)['productions'][0]
            db.commit()
        scanned = report_service.handle_production_report(stale, report_service.generate_qr_data(factory_item_id), 'old-wx')
        assert not scanned['success'] and '本地生产' in scanned['message']
        stale.rollback()
    with Session(engine) as db:
        item = db.get(ProductionOrderItem, factory_item_id)
        factory_command = ActivationManifest(request_key='chain-enable-original-stock-factory', business_date=DAY,
            productions=[dict(production_opening_record_id=production_mapping['record_id'], items=[dict(production_item_id=item.id, expected_version=item.local_version)])])
        activation_service.activate(db, factory_command, user)
        local_service.receive(db, item.id, ReceiptCreate(request_key='chain-stock-factory-future-receive', expected_version=item.local_version,
            warehouse_id=warehouses[0].id, quality='sellable', quantity=4, reason='New physical acceptance', allocations=[]), user)
        db.commit()
        assert item.received_qty == 10 and db.get(ProductionOrder, factory_id).transaction_mode == 'local'
        assert db.scalar(select(StockBalance.on_hand).where(StockBalance.sku_id == sku_id, StockBalance.warehouse_id == warehouses[0].id)) == 10
    with Session(engine.execution_options(isolation_level='READ COMMITTED')) as db:
        projected = project_invoice(db, invoice_id); db.commit()
        assert projected.id == mapping['customer_order_id'] and projected.external_order_id == 'CWO-ORDER' and projected.amount_usd == 1000
    return dict(original_contract='1000.00', original_quantity=10, historical_shipped=6, future_shipped=4,
        historical_media_ids_preserved=True, stale_rr_recall_rejected=True, stale_rr_inspection_mutations_rejected=4,
        stale_rr_legacy_scanner_rejected=True,
        concurrent_activation_identical=True, original_scaled_payment_preserved=True,
        same_customer_order_id= mapping['customer_order_id'], final_paid='1000.00', final_balance='0.00',
        factory_historical_received=6, factory_new_received=4, factory_final_stock=10)
