"""Live presale warehouse stock. No mirror fallback or business writes."""
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from app.core.config import get_settings
from app.core.time import beijing_now
from app.invoice import okki_client
from app.invoice.presale_lines import current_items


def identifier(value):
    return str(value) if not isinstance(value, bool) and re.fullmatch(r'[1-9][0-9]*', str(value)) else None


@dataclass(frozen=True)
class StockTarget:
    invoice_id: int
    warehouse_id: str | None
    lines: tuple


def capture(invoice):
    return StockTarget(invoice.id, identifier(get_settings().OKKI_PRESALE_WAREHOUSE_ID),
        tuple((row.id, identifier(row.product_id), identifier(row.sku_id)) for row in current_items(invoice)))


def _available(data, product, sku, warehouse):
    if not isinstance(data, dict) or not isinstance(data.get('list'), list):
        raise ValueError('库存列表不完整')
    rows, count = data['list'], data.get('count')
    if isinstance(count, bool) or not re.fullmatch(r'[0-9]+', str(count)) or int(count) != len(rows):
        raise ValueError('库存列表不完整')
    if any(not isinstance(row, dict) or identifier(row.get('sku_id')) != sku
            or identifier(row.get('product_id')) != product or not identifier(row.get('warehouse_id')) for row in rows):
        raise ValueError('库存产品映射不一致')
    matches = [row for row in rows if identifier(row['warehouse_id']) == warehouse]
    if len(matches) != 1:
        raise ValueError('未查到唯一的目标仓库库存')
    row = matches[0]
    value = row.get('enable_count')
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('库存数量无效') from None
    if (not amount.is_finite() or amount < 0 or amount > 9007199254740991
            or isinstance(row.get('disable_flag'), bool) or str(row.get('disable_flag')) not in {'0', '1'}):
        raise ValueError('库存数量或启用状态无效')
    return format(amount if str(row['disable_flag']) == '0' else Decimal(0), 'f')


def observe(target, item_ids=None):
    """Use a separate ephemeral product-scoped token, outside business locks."""
    quantities, reasons = {}, {}
    pairs = {(product, sku) for identity, product, sku in target.lines
        if product and sku and (item_ids is None or identity in item_ids)}
    if target.warehouse_id and pairs:
        try:
            # Existing cached invoice tokens lack product scope. Never overwrite
            # the shared token or mislabel the mirror as a successful live read.
            token, _ = okki_client.fetch_token(scope=f'{okki_client.TOKEN_SCOPE} product')
            for product, sku in sorted(pairs):
                data = okki_client._get_json('/v1/product/inventory-list', token,
                    context='预售库存查询', params={'sku_id':sku, 'count':100, 'start_index':1})
                if data is None:
                    raise okki_client.OkkiApiError('库存查询鉴权失效')
                try:
                    quantities[(product, sku)] = _available(data, product, sku, target.warehouse_id)
                except ValueError as error:
                    reasons[(product, sku)] = str(error)
        except (okki_client.OkkiApiError, OSError):
            # A denied scope/network error is systemic: don't repeat it per SKU.
            reasons.update({pair:'实时库存暂不可用，请刷新重试或联系管理员检查小满权限' for pair in pairs if pair not in quantities})
    queried_at = beijing_now().isoformat(timespec='seconds')
    return {'invoice_id':target.invoice_id, 'warehouse_id':target.warehouse_id,
        'source':'okki_live', 'queried_at':queried_at, 'items':[
            {'invoice_item_id':identity, 'product_id':product, 'sku_id':sku,
             'available_stock':quantities.get((product, sku)),
             'reason':('预售出库仓库尚未配置' if not target.warehouse_id else
                 '产品/SKU尚未映射' if not product or not sku else reasons.get((product, sku), ''))}
            for identity, product, sku in target.lines]}


def require_stock(invoice, body, target, snapshot):
    if capture(invoice) != target:
        raise ValueError('订单产品或出库仓库在库存核验期间已变化，请刷新重新核算')
    rows = {row['invoice_item_id']:row for row in snapshot['items']}
    requested, available = defaultdict(int), {}
    for item in body.items:
        row = rows.get(item.invoice_item_id)
        if row is None or row['available_stock'] is None:
            raise ValueError('所选产品可用库存待核对，请刷新库存后重新核算')
        key = row['sku_id']
        value = Decimal(row['available_stock'])
        if key in available and available[key] != value:
            raise ValueError('同一SKU库存不一致，请刷新库存后重新核算')
        available[key] = value
        requested[key] += item.quantity
    if any(Decimal(quantity) > available[sku] for sku, quantity in requested.items()):
        raise ValueError('本批数量合计超过产品当前可用库存，请刷新库存并调整数量')


def read(db, identity, user):
    from app.invoice import shipment_quote_service as quotes, settlement_service as shipments
    from app.receipt import authority
    authority.fresh_boundary(db)
    try:
        invoice, current = quotes._authorize(db, identity, user)
        shipments.get_order(db, identity, current, writable=False)
        expected = capture(invoice)
        db.commit()
        result = observe(expected)
        quotes._release(db)
        invoice, current = quotes._authorize(db, identity, user)
        shipments.get_order(db, identity, current, writable=False)
        if capture(invoice) != expected:
            raise ValueError('订单产品或出库仓库已变化，请刷新重新查询库存')
        return result
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    except SQLAlchemyError as error:
        authority.unavailable(error)
    finally:
        quotes._release(db)
