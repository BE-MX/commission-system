"""Inventory comparisons are scoped, warehouse-specific and never write business state."""
from datetime import date

import pytest
from sqlalchemy import event, text

from app.invoice.models import Invoice, InvoiceItem, OkkiOutboundTask
from app.shipping_inspection import outbound_inventory_service as inventory, outbound_service
from tests.test_shipping_inspection import _user, _bind_okki, _pc_client, outbound_scope_seed, product_display_source


@pytest.fixture
def stock(db, outbound_scope_seed, product_display_source):
    db.execute(text('''CREATE TABLE lsordertest.okki_inventory (
        product_id INTEGER,sku_id INTEGER,warehouse_id TEXT,enable_count TEXT,
        real_count TEXT,unit TEXT,disable_flag INTEGER,synced_at TEXT)'''))
    db.execute(text('''INSERT INTO lsordertest.okki_inventory VALUES
        (101,321,'8193514242746','40','500','Piece',0,'2026-10-14 08:33:31'),
        (101,321,'OTHER','1000','1000','Piece',0,'2026-10-14 08:33:31')'''))
    owner = _user(db, 'inventory-owner')
    other = _user(db, 'inventory-other')
    _bind_okki(db, owner)
    _bind_okki(db, other, '9002')
    invoice = Invoice(invoice_no='STOCK-TEST', customer_id='C1', customer_name='Customer',
                      invoice_date=date(2026, 10, 14), sales_user_id=owner.id, xiaoman_order_id='123')
    db.add(invoice)
    db.flush()
    db.add_all([InvoiceItem(invoice_id=invoice.id, product_name='Keratin/18/#P2/8/1g',
        product_display='Keratin', color='P2/8', product_id=101, sku_id=321, quantity=q) for q in (60, 40)])
    task = OkkiOutboundTask(invoice_id=invoice.id, order_id='123', status='waiting_stock')
    db.add(task)
    db.commit()
    outbound_service._columns_cache.clear()
    return owner, other, task


def test_repeated_sku_demand_uses_target_warehouse_available_not_real_or_other_warehouse(db, stock):
    _, _, task = stock
    data = inventory.inventory_details(db, f'task:{task.id}')
    item = data['items'][0]
    assert item['required'] == 100 and item['available'] == 40
    assert item['real_count'] == 500 and item['unavailable_count'] == 460
    assert item['shortage'] == 60 and item['status'] == 'shortage'
    assert item['line_numbers'] == [1, 2] and len(item['warehouses']) == 2
    assert item['synced_at'] == '2026-10-14 08:33:31'
    assert data['source'] == 'okki_inventory_mirror'


def test_inventory_route_scope_permissions_no_store_and_no_writes(db, stock):
    owner, other, task = stock
    path = f'/api/shipping-inspection/outbound-records/task:{task.id}/inventory'
    with _pc_client(db, other, ['shipping_inspection:read']) as client:
        assert client.get(path).status_code == 404
    with _pc_client(db, owner, []) as client:
        assert client.get(path).status_code == 403
    writes = []
    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(statement)
    event.listen(db.get_bind(), 'before_cursor_execute', capture)
    try:
        with _pc_client(db, owner, ['shipping_inspection:read']) as client:
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers['Cache-Control'] == 'private, no-store'
            assert response.json()['data']['shortage_count'] == 1
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', capture)
    assert not writes
    with _pc_client(db, other, ['shipping_inspection:read', 'shipping_inspection:read_all']) as client:
        assert client.get(path).status_code == 200


@pytest.mark.parametrize('change', ["DELETE FROM lsordertest.okki_inventory WHERE warehouse_id='8193514242746'",
    "UPDATE lsordertest.okki_inventory SET enable_count='NaN'",
    "UPDATE lsordertest.okki_inventory SET synced_at=NULL",
    "UPDATE lsordertest.okki_inventory SET disable_flag=2"])
def test_missing_or_invalid_stock_is_unknown_instead_of_zero_or_sufficient(db, stock, change):
    db.execute(text(change))
    item = inventory.inventory_details(db, f'task:{stock[2].id}')['items'][0]
    assert item['status'] == 'unknown' and item['shortage'] is None


def test_disabled_stock_has_no_usable_quantity(db, stock):
    db.execute(text('UPDATE lsordertest.okki_inventory SET disable_flag=1'))
    item = inventory.inventory_details(db, f'task:{stock[2].id}')['items'][0]
    assert item['available'] == 0 and item['shortage'] == 100 and item['disabled']


def test_exact_available_satisfies_and_different_product_same_sku_not_combined(db, stock):
    db.execute(text('UPDATE lsordertest.okki_inventory SET enable_count=100'))
    item = inventory.inventory_details(db, f'task:{stock[2].id}')['items'][0]
    assert item['status'] == 'sufficient' and item['shortage'] == 0
    db.execute(text('UPDATE lsordertest.okki_inventory SET product_id=999'))
    assert inventory.inventory_details(db, f'task:{stock[2].id}')['items'][0]['status'] == 'unknown'


def test_mirrored_outbound_uses_own_warehouse_and_line_quantity(db, stock):
    db.execute(text('ALTER TABLE lsordertest.okki_outbound_records ADD COLUMN warehouse_id TEXT'))
    db.execute(text("UPDATE lsordertest.okki_outbound_records SET warehouse_id='OTHER' WHERE id='OB001'"))
    db.execute(text('ALTER TABLE lsordertest.okki_outbound_record_items ADD COLUMN sku_id INTEGER'))
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET sku_id=321 WHERE id='IT001'"))
    outbound_service._columns_cache.clear()
    data = inventory.inventory_details(db, 'OB001', okki_user_id='9001')
    item = next(r for r in data['items'] if r['product_id'] == '101')
    assert data['record']['record_source'] == 'okki' and data['warehouse_id'] == 'OTHER'
    assert item['required'] == 10 and item['available'] == 1000 and item['shortage'] == 0
    with _pc_client(db, stock[1], ['shipping_inspection:read']) as client:
        assert client.get('/api/shipping-inspection/outbound-records/OB001/inventory').status_code == 404


def test_broken_task_order_binding_not_visible(db, stock):
    stock[2].order_id = 'ANOTHER'
    db.flush()
    with _pc_client(db, stock[0], ['shipping_inspection:read']) as client:
        assert client.get(f'/api/shipping-inspection/outbound-records/task:{stock[2].id}/inventory').status_code == 404


def test_verified_outbound_overlay_uses_updated_details_before_mirror_catches_up(db, stock):
    from app.shipping_inspection.models import ShippingOperationEvent
    db.execute(text('ALTER TABLE lsordertest.okki_outbound_records ADD COLUMN warehouse_id TEXT'))
    db.execute(text("UPDATE lsordertest.okki_outbound_records SET warehouse_id='8193514242746' WHERE id='OB001'"))
    db.add(ShippingOperationEvent(scope='outbound-invoice-sync', request_id='OB001', source='pc',
        login_user_id=stock[0].id, operator_user_id=stock[0].id, operator_name='Review', login_name='Review',
        outbound_record_id='OB001', action='sync_verified', result={'verified': {
            'update_time': '2026-10-14 08:40:00', 'serial_id': 'UPDATED', 'items': [
                {'item_id': 'okki:123', 'product_id': 101, 'sku_id': 321,
                 'product_name': 'Updated product', 'qty': 100, 'unit': 'Piece'}]}}))
    db.flush()
    outbound_service._columns_cache.clear()
    data = inventory.inventory_details(db, 'OB001', okki_user_id='9001')
    assert data['record']['outbound_no'] == 'UPDATED'
    assert len(data['items']) == 1
    assert data['items'][0]['required'] == 100 and data['items'][0]['shortage'] == 60
