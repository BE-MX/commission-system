"""Read-only credit for historical native outbounds missing a handoff snapshot.

Mirror IDs are discovery hints only. Credit requires a live detail AND active-list
membership. A missing candidate retains demand; partial evidence only credits the
verified subset. This never updates history or runs in inventory list rendering.
"""
from collections import defaultdict
from sqlalchemy import text

from app.core.config import get_settings
from app.invoice import okki_client
from app.shipping_inspection.outbound_presence import is_active


def reader(db):
    token = None

    def observe(invoice_id, order_id):
        nonlocal token
        from app.invoice.stock_reservations import WAREHOUSE_ID, quantities
        schema = get_settings().BUSINESS_DB_NAME
        if not schema or not schema.replace('_', '').isalnum():
            raise ValueError('Invalid business schema')
        ids = db.execute(text(f'SELECT DISTINCT outbound_invoice_id FROM `{schema}`.okki_outbound_record_items '
                              'WHERE order_id=:order_id'), {'order_id':order_id}).scalars().all()
        result = defaultdict(int)
        for identity in ids:
            if not str(identity).isdigit() or int(identity) <= 0:
                raise ValueError('Historical outbound identity unavailable')
            if token is None:
                token, _ = okki_client.fetch_token()
            detail = okki_client._get_json('/v1/invoices/outbound/info', token,
                context='历史出库库存占用核验', params={'outbound_invoice_id':str(identity)})
            if not isinstance(detail, dict) or str(detail.get('outbound_invoice_id')) != str(identity):
                raise ValueError('Historical outbound detail unavailable')
            # Only confirmed active pending outbounds are used by this recovery.
            # Unsupported states keep their reservation instead of assuming release.
            if (type(detail.get('status')) is not int or detail['status'] != 1
                    or not is_active(token, str(identity), detail.get('create_time'))):
                continue
            rows = detail.get('record_list')
            if (str(detail.get('invoice_warehouse_info', {}).get('id')) != WAREHOUSE_ID
                    or not isinstance(rows, list) or not rows
                    or any(str(row.get('order_id')) != str(order_id) for row in rows)):
                raise ValueError('Historical outbound warehouse/order differs')
            row_ids = [str(row.get('outbound_record_id')) for row in rows]
            if any(not key.isdigit() or int(key) <= 0 for key in row_ids) or len(set(row_ids)) != len(row_ids):
                raise ValueError('Historical outbound rows are ambiguous')
            amounts = quantities([{'product_id':r.get('product_id'), 'sku_id':r.get('sku_id'),
                                   'count':r.get('outbound_count')} for r in rows])
            for key, amount in amounts.items():
                result[key] += amount
        return dict(result)

    return observe
