"""Scoped, read-only warehouse inventory comparison for tasks and outbound records."""
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import bindparam, text

from app.core.time import beijing_now
from app.invoice.outbound_followup_service import DESTINATION_WAREHOUSE_ID
from app.shipping_inspection import outbound_service as records


def _amount(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _number(value):
    return float(value) if value is not None else None


def _source(db, record_id, scope):
    if record_id.startswith('task:'):
        identity = record_id[5:]
        if not identity.isdigit():
            raise HTTPException(404, '出库单不存在')
        clause = """AND EXISTS (SELECT 1 FROM ark_user_external_bindings b
            WHERE b.ark_user_id=f.sales_user_id AND b.provider='okki'
              AND b.binding_status='active' AND b.deleted_at IS NULL
              AND b.external_account_id=:owner)""" if scope is not None else ''
        row = db.execute(text(f"""SELECT f.id AS invoice_id, f.invoice_no, f.customer_name,
            t.order_id, t.status FROM ark_okki_outbound_tasks t
            JOIN ark_invoices f ON f.id=t.invoice_id AND f.xiaoman_order_id=t.order_id
            WHERE t.id=:id {clause}"""), {'id': identity, 'owner': scope}).mappings().first()
        if row is None:
            raise HTTPException(404, '出库单不存在')
        items = db.execute(text("""SELECT product_id, sku_id, product_name, quantity AS required,
            NULL AS unit FROM ark_invoice_items WHERE invoice_id=:id
            AND presale_archived=0 ORDER BY sort_order,id"""), {'id': row['invoice_id']}).mappings().all()
        return {'outbound_no': row['invoice_no'], 'customer_name': row['customer_name'],
                'order_id': str(row['order_id']), 'record_source': 'ark_task',
                'outbound_state': row['status']}, items, DESTINATION_WAREHOUSE_ID, None

    record = records.get_outbound_record(db, record_id, okki_user_id=scope)
    if record is None:
        raise HTTPException(404, '出库单不存在')
    from app.shipping_inspection.outbound_sync_state import overlay
    snapshot = overlay(db, record)
    link, rm, im = records._link(db)
    columns = records._table_columns(db, records.ITEMS_TABLE)
    if not snapshot and (link is None or not {'sku_id', 'product_id'} <= columns or not im['quantity']):
        raise HTTPException(409, '出库明细缺少产品或 SKU 标识，无法核对库存')
    if snapshot:
        items = [{'product_id': r.get('product_id'), 'sku_id': r.get('sku_id'),
                  'product_name': r.get('product_name'), 'required': r.get('qty'),
                  'unit': r.get('unit')} for r in snapshot['items']]
    else:
        ik = im['invoice_id'] if link == 'invoice' else im['record_id']
        rk = rm['invoice_id'] if link == 'invoice' else rm['id']
        items = db.execute(text(f"""SELECT i.product_id, i.sku_id,
            {records._col(im, 'product_name', 'i')} AS product_name,
            {records._col(im, 'quantity', 'i')} AS required,
            {records._col(im, 'unit', 'i')} AS unit
            FROM `{records._schema()}`.`{records.ITEMS_TABLE}` i
            JOIN `{records._schema()}`.`{records.RECORDS_TABLE}` r ON i.`{ik}`=r.`{rk}`
            WHERE r.`{rm['id']}`=:id ORDER BY i.`{im['id']}`"""), {'id': record_id}).mappings().all()
    header_columns = records._table_columns(db, records.RECORDS_TABLE)
    warehouse = warehouse_name = None
    if 'warehouse_id' in header_columns:
        name = 'warehouse_name' if 'warehouse_name' in header_columns else 'NULL'
        header = db.execute(text(f"""SELECT warehouse_id, {name} AS warehouse_name
            FROM `{records._schema()}`.`{records.RECORDS_TABLE}` WHERE `{rm['id']}`=:id"""),
            {'id': record_id}).mappings().first()
        warehouse, warehouse_name = header['warehouse_id'], header['warehouse_name']
    return {**record, 'record_source': 'okki'}, items, str(warehouse) if warehouse else None, warehouse_name


def inventory_details(db, record_id, *, okki_user_id=None):
    record, source, warehouse, warehouse_name = _source(db, record_id, okki_user_id)
    groups = {}
    for index, item in enumerate(source, 1):
        product, sku = str(item['product_id'] or ''), str(item['sku_id'] or '')
        # Unmapped lines stay separate; repeated exact SKU rows share one demand.
        key = (product, sku) if product and sku else ('unmapped', str(index))
        group = groups.setdefault(key, {'product_id': product, 'sku_id': sku,
            'product_name': item['product_name'] or '商品信息待同步', 'unit': item['unit'],
            'line_numbers': [], 'required': Decimal(0), 'valid': True})
        quantity = _amount(item['required'])
        group['valid'] = group['valid'] and quantity is not None and quantity > 0
        group['required'] += quantity or Decimal(0)
        group['line_numbers'].append(index)
    keys = [(int(g['product_id']), int(g['sku_id'])) for g in groups.values()
            if g['product_id'].isdigit() and g['sku_id'].isdigit()]
    inventory = {}
    columns = records._table_columns(db, 'okki_inventory')
    if keys and {'product_id', 'sku_id', 'warehouse_id', 'enable_count', 'disable_flag'} <= columns:
        optional = ', '.join(f'{c} AS {c}' if c in columns else f'NULL AS {c}'
                             for c in ('real_count', 'unit', 'synced_at'))
        query = text(f"""SELECT product_id,sku_id,warehouse_id,enable_count,disable_flag,{optional}
            FROM `{records._schema()}`.okki_inventory WHERE (product_id,sku_id) IN :pairs""").bindparams(
                bindparam('pairs', expanding=True))
        for row in db.execute(query, {'pairs': keys}).mappings():
            inventory.setdefault((str(row['product_id']), str(row['sku_id'])), []).append(row)
    result = []
    for g in groups.values():
        stocks = inventory.get((g['product_id'], g['sku_id']), [])
        target = [r for r in stocks if str(r['warehouse_id']) == warehouse]
        stock = target[0] if len(target) == 1 else None
        available = _amount(stock['enable_count']) if stock else None
        disabled = stock is not None and str(stock['disable_flag']) == '1'
        if disabled:
            available = Decimal(0)
        if stock and str(stock['disable_flag']) not in ('0', '1'):
            available = None
        known = bool(g['valid'] and warehouse and available is not None and stock['synced_at'])
        shortage = max(g['required'] - available, Decimal(0)) if known else None
        real = _amount(stock['real_count']) if stock else None
        result.append({**{k: v for k, v in g.items() if k not in ('required', 'valid')},
            'required': _number(g['required']) if g['valid'] else None,
            'available': _number(available), 'real_count': _number(real),
            'unavailable_count': _number(real - available) if real is not None and available is not None and real >= available else None,
            'shortage': _number(shortage), 'unit': g['unit'] or (stock['unit'] if stock else None),
            'status': 'unknown' if not known else 'shortage' if shortage else 'sufficient',
            'disabled': disabled, 'synced_at': str(stock['synced_at']) if stock and stock['synced_at'] else None,
            'warehouses': [{'warehouse_id': str(r['warehouse_id']),
                'available': _number(_amount(r['enable_count'])) if str(r['disable_flag']) == '0' else 0 if str(r['disable_flag']) == '1' else None,
                'real_count': _number(_amount(r['real_count'])), 'unit': r['unit'],
                'synced_at': str(r['synced_at']) if r['synced_at'] else None} for r in stocks]})
    result.sort(key=lambda r: {'shortage': 0, 'unknown': 1, 'sufficient': 2}[r['status']])
    return {'record': record, 'warehouse_id': warehouse, 'warehouse_name': warehouse_name,
            'source': 'okki_inventory_mirror', 'queried_at': str(beijing_now()), 'items': result,
            'shortage_count': sum(r['status'] == 'shortage' for r in result),
            'unknown_count': sum(r['status'] == 'unknown' for r in result)}
