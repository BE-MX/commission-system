"""Real MySQL exact material resolution and collapsed custom-order continuity."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
from sqlalchemy import select, func, event
from sqlalchemy.orm import Session
from app.auth.models import ArkUser
from app.customer.models import CustomerAccount, CustomerOrderItem
from app.core.time import beijing_now
from app.finance.models import BankAccount
from app.finance import service as finance
from app.finance.schemas import AllocationCreate
from app.commerce_migration import material_pending_service, order_service, fulfillment_service, inventory_service, activation_service
from app.commerce_migration.activation_schemas import ActivationManifest, ActivationSelection
from app.commerce_migration.fulfillment_schemas import FulfillmentOpeningManifest
from app.commerce_migration.inventory_schemas import InventoryOpeningManifest
from app.commerce_transition.models import InvoiceAuthority
from app.invoice import local_fulfillment
from app.invoice.models import Invoice
from app.invoice.local_fulfillment_schemas import LocalShipmentQuote, LocalShipmentCreate
from app.invoice.settlement_models import Receivable, ShipmentOutbound
from app.inventory.models import Warehouse, StockBalance
from app.semifinished.models import InventoryLedger, InvoiceAllocation, InventoryBalance
from app.shipping_inspection import service as inspections, outbound_service
from app.shipping_inspection.models import ShippingInspectionPhoto
from app.trade.projection_service import project_invoice
from tests.test_commerce_material_pending import inputs as material_inputs
from tests.test_commerce_order_aliases import alias_inputs
from tests.test_commerce_fulfillment_opening import inputs as fulfillment_inputs
from tests.test_finance_local import payment, cmd
from tests.test_local_fulfillment import act

DAY = date(2026, 10, 3)


def verify_responsibilities(engine):
    from tests.test_local_migration_chain_mysql import transaction_mirror_guard
    reject, attempts = transaction_mirror_guard('lsordertest')
    event.listen(engine, 'before_cursor_execute', reject)
    try:
        with patch('httpx.get', side_effect=AssertionError('Responsibility opening attempted GET')) as http_get, \
             patch('httpx.post', side_effect=AssertionError('Responsibility opening attempted POST')) as http_post:
            result = _verify_responsibilities(engine)
        http_get.assert_not_called()
        http_post.assert_not_called()
        assert attempts == []
        return dict(result, transaction_mirror_queries=len(attempts), external_http_calls=http_get.call_count + http_post.call_count)
    finally:
        event.remove(engine, 'before_cursor_execute', reject)


def _verify_responsibilities(engine):
    with Session(engine, expire_on_commit=False) as db:
        actor = db.scalar(select(ArkUser).where(ArkUser.username == 'chain-native-seller'))
        user = dict(sub=str(actor.id), roles=['super_admin'], permissions=['invoice:write'])
        customer = CustomerAccount(customer_code='CHAIN-CWA', display_name='Synthetic custom buyer',
            entity_type='registered_company', identity_status='verified', relationship_stage='active_customer',
            relationship_stage_changed_at=beijing_now(), relationship_stage_reason='synthetic-custom',
            record_status='active', identity_confidence=1, profile_completeness=100, profile_input_seq=1)
        db.add(customer); db.commit()
        # This historical account is shared by both routes. The unrelated
        # native-only account used earlier in the chain retains its exclusivity.
        bank = BankAccount(code='CHAIN-CWA-USD', name='Original custom and presale bank', currency='USD')
        db.add(bank); db.flush()
        warehouse = db.scalar(select(Warehouse).where(Warehouse.code == 'CHAIN-MAIN'))
        body, old_invoice, allocation, balance, material = material_inputs(db, (customer, user), tag='MYSQL-A')
        allocation_id, balance_id = allocation.id, balance.id
        before_count = db.scalar(select(func.count()).select_from(InventoryLedger))
    barrier = Barrier(2)
    def resolve(_):
        with Session(engine) as db:
            # Establish a real repeatable-read snapshot before the competing write.
            db.scalar(select(func.count()).select_from(InventoryLedger))
            barrier.wait(timeout=15)
            result = material_pending_service.apply_manifest(db, body, user)
            db.commit()
            return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(resolve, range(2)))
    assert results[0] == results[1]
    with Session(engine) as db:
        balance = db.get(InventoryBalance, balance_id)
        allocation = db.get(InvoiceAllocation, allocation_id)
        assert balance.on_hand_grams == Decimal('899.875') and balance.reserved_grams == 0
        assert allocation.allocated_qty_grams == Decimal('300.125') and allocation.status == 'allocated'
        assert db.scalar(select(func.count()).select_from(InventoryLedger)) == before_count + 1
        balance.on_hand_grams += Decimal('5.125'); balance.version += 1
        db.commit()
        repeated = material_pending_service.apply_manifest(db, body.model_copy(update={'batch_key': 'mysql-pending-replay'}), user)
        db.commit()
        assert repeated['resolutions'] == results[0]['resolutions'] and balance.on_hand_grams == 905
        for tag, delta, outcome, hand, allocated in [
            ('MYSQL-B', '100.125', 'not_accepted', '1000', '200'),
            ('MYSQL-C', '-100.125', 'accepted', '1100.125', '99.875'),
            ('MYSQL-D', '-100.125', 'not_accepted', '1000', '200')]:
            known, _, line, bucket, _ = material_inputs(db, (customer, user), tag=tag, delta=delta, outcome=outcome)
            material_pending_service.apply_manifest(db, known, user); db.commit()
            assert bucket.on_hand_grams == Decimal(hand) and bucket.reserved_grams == 0
            assert line.allocated_qty_grams == Decimal(allocated) and line.status == 'allocated'
        raw_order, invoice, order, alias, original = alias_inputs(db, (customer, user), tag='CWA', tenant='tenant-CWA')
        raw_order['orders'][0]['source_order_no'] = 'N'*100
        order.order_no = 'N'*100
        for source, line in zip(raw_order['orders'][0]['items'], invoice.items, strict=True):
            source['product_display'], source['product_family'] = 'P'*200, 'Reviewed custom family'
            line.product_display = source['product_display']
        # Persist and read actual MySQL DATETIME precision before freezing its hash.
        db.commit(); db.refresh(alias)
        original = order_service.alias_snapshot(alias)
        raw_order['orders'][0]['customer_item_aliases'][0]['original_snapshot_sha256'] = order_service.digest(original)
        for item in raw_order['orders'][0]['items']:
            item['reservations'] = [dict(warehouse_id=warehouse.id, quantity=2)]
        raw, invoice, cash, mapping, _ = fulfillment_inputs(db, (None, [warehouse]), (customer, user, bank),
            tag='CWA', tenant='tenant-CWA', raw_order=raw_order, shipment_items=[
                dict(source_item_id='CWA-REAL-A', outbound_item_id='cwa-original-A', quantity=2, line_amount='200'),
                dict(source_item_id='CWA-REAL-B', outbound_item_id='cwa-original-B', quantity=4, line_amount='400')])
        # Distinct original source aliases from the earlier whole-order scenario.
        shipment = raw['orders'][0]['shipments'][0]
        shipment.update(outbound_record_id='CWA-original-record', outbound_invoice_id='CWA-original-api',
            outbound_no='CWA-ORIGINAL-OUT', settlement_no='CWA-ORIGINAL-SHIP')
        fulfillment_service.apply_manifest(db, FulfillmentOpeningManifest.model_validate(raw), user)
        sku_id = invoice.items[0].local_sku_id
        inventory_service.apply_manifest(db, InventoryOpeningManifest(batch_key='CWA-physical', source='physical',
            tenant='warehouse', cutover_date=DAY, evidence_sha256='f'*64, review_reference='Synthetic custom closing',
            stocks=[dict(external_id='CWA-bucket', mode='initialize', warehouse_id=warehouse.id,
                local_sku_id=sku_id, quality='sellable', on_hand=10, reserved=0)], materials=[]), user)
        command = activation_service.prepare(db, ActivationSelection(request_key='CWA-enable', record_ids=[mapping['record_id']]))
        assert command['report']['can_activate'], command['report']
        activation_service.activate(db, ActivationManifest.model_validate(command['command']), user)
        db.commit()
        assert order_service.alias_snapshot(alias) == original and alias.projection_role == 'historical_alias'
        assert [line.stock_reserved_quantity for line in invoice.items] == [2, 2]
        batch = finance.register(db, payment(customer, bank, request_key='CWA-future-cash', bank_reference='CWA-bank',
            gross_amount='400', actual_bank_fee=0, collection_date=DAY), user)
        finance.confirm(db, batch.id, cmd('CWA-confirm', batch.version).model_copy(update={'business_date': DAY}), user)
        target = db.get(Receivable, mapping['receivables'][0]['receivable_id'])
        finance.allocate(db, batch.id, AllocationCreate(request_key='CWA-allocate', expected_version=batch.version,
            invoice_id=invoice.id, receivable_id=target.id, amount='400', business_date=DAY), user)
        quote_body = LocalShipmentQuote(items=[dict(invoice_item_id=line.id, quantity=2) for line in invoice.items],
            warehouse_id=warehouse.id, business_date=DAY,
            expected_authority_epoch=db.get(InvoiceAuthority, invoice.id).epoch)
        quote = local_fulfillment.quote(db, invoice.id, quote_body, user)
        row = local_fulfillment.create(db, invoice.id, LocalShipmentCreate(**quote_body.model_dump(), request_key='CWA-final',
            expected_version=invoice.commerce_version, quote_hash=quote['quote_hash']), user)
        assert row.quote['goods_payment_due'] == '400.00'
        act(db, row, user, 'CWA-ready', 'ready')
        outbound = db.scalar(select(ShipmentOutbound).where(ShipmentOutbound.settlement_id == row.id))
        identity = local_fulfillment.record_id(outbound)
        inspection = inspections.get_or_create_draft(db, identity, actor.id)
        for item in outbound_service.list_outbound_items(db, identity):
            db.add(ShippingInspectionPhoto(inspection_id=inspection.id, item_id=item['item_id'],
                file_path=f"synthetic-cwa-{item['item_id']}.jpg", media_type='image'))
        db.flush()
        inspections.submit(db, outbound_record_id=identity, user_id=actor.id, commit=False)
        act(db, row, user, 'CWA-ship', 'ship', inspection_version=inspection.edit_version)
        db.commit()
        assert [line.stock_shipped_quantity for line in invoice.items] == [4, 6]
        assert invoice.internal_received == 1000 and invoice.internal_balance == 0 and invoice.total_amount == 1000
        bucket = db.scalar(select(StockBalance).where(StockBalance.sku_id == sku_id,
            StockBalance.warehouse_id == warehouse.id, StockBalance.quality == 'sellable'))
        assert bucket.on_hand == 6 and bucket.reserved == 0
        invoice_id, order_id, alias_id = invoice.id, order.id, alias.id
    with Session(engine.execution_options(isolation_level='READ COMMITTED')) as db:
        projected = project_invoice(db, invoice_id); db.commit()
        assert projected.id == order_id and projected.amount_usd == 1000
        alias = db.get(CustomerOrderItem, alias_id)
        active = db.scalars(select(CustomerOrderItem).where(CustomerOrderItem.order_id == order_id,
            CustomerOrderItem.projection_role == 'active')).all()
        assert order_service.alias_snapshot(alias) == original
        assert len(active) == 2 and sum(item.quantity for item in active) == 10
        assert sum(item.line_amount for item in active) == 1000
        assert {item.product_family for item in active} == {'Reviewed custom family'} and projected.order_no == 'N'*100
    with Session(engine, expire_on_commit=False) as db:
        from app.catalog.models import CatalogProduct, CatalogSku
        from app.invoice.commerce_service import create_draft, confirm
        from tests.test_invoice_commerce import draft, action
        sku = db.get(CatalogSku, sku_id)
        db.get(CatalogProduct, sku.product_id).display_name = 'P'*256
        native = create_draft(db, draft(customer, user, sku, request_key='CWA-native-long', order_type='production'), user)
        confirm(db, native.id, action('CWA-native-confirm', 1, warehouse.id), user)
        db.commit()
        native_id = native.id
    with Session(engine.execution_options(isolation_level='READ COMMITTED')) as db:
        native_projection = project_invoice(db, native_id); db.commit()
        assert db.scalar(select(CustomerOrderItem.product_family).where(CustomerOrderItem.order_id == native_projection.id)) == 'P'*256
    with Session(engine, expire_on_commit=False) as db:
        from tests.test_commerce_presale_continuity import verify_presale_continuity
        presale_customer = CustomerAccount(customer_code='CHAIN-PS', display_name='Synthetic historical presale buyer',
            entity_type='registered_company', identity_status='verified', relationship_stage='active_customer',
            relationship_stage_changed_at=beijing_now(), relationship_stage_reason='synthetic-presale',
            record_status='active', identity_confidence=1, profile_completeness=100, profile_input_seq=1)
        db.add(presale_customer); db.commit()
        presale = verify_presale_continuity(db, (None, [warehouse]), (presale_customer, user, bank), tag='CHAIN-PS', tenant='tenant-CHAIN-PS')
        db.commit()
    return dict(material_concurrent_exact_once=True, positive_negative_accepted_rejected=True,
        material_replay_preserves_new_stock=True, custom_alias_id=alias_id, original_alias_unchanged=True,
        true_line_quantities=[4, 6], full_amount=1000, future_received=400, final_balance=0,
        physical_stock=6, active_projection_quantity=10, native_family_length=256,
        preserved_original_display_length=200, full_source_number_length=100, presale_continuity=presale)
