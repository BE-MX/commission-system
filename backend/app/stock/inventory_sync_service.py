"""Explicit, audited single-product refresh of the OKKI inventory mirror."""
import logging
from decimal import Decimal, InvalidOperation
from time import monotonic

import httpx
from fastapi import HTTPException
from sqlalchemy import DateTime, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.time import beijing_now
from app.invoice import okki_client
from app.invoice.shipment_inventory_service import identifier
from app.portal.access_policy import employee_principal
from app.portal.errors import PortalError
from app.stock.inventory_sync_models import InventorySyncLog
from app.stock.local_query_service import legacy_excluded_products

logger = logging.getLogger(__name__)
FIELDS = ('sku_id', 'warehouse_id', 'product_id', 'enable_count', 'real_count', 'disable_flag', 'synced_at')


def _authorize(db, user):
    try:
        actor = int(user.get('sub') or 0)
        return employee_principal(db, actor, 'stock:read', 'stock:write')['id']
    except (ValueError, TypeError, PortalError):
        raise HTTPException(403, '当前账号无权同步库存') from None


def _capture(db, product_id, *, lock=False):
    if get_settings().TRANSACTION_MODE == 'local' or str(product_id) in legacy_excluded_products(db):
        raise HTTPException(409, '本地库存产品不能同步小满库存')
    schema = get_settings().BUSINESS_DB_NAME
    suffix = ' FOR UPDATE' if lock and db.bind.dialect.name == 'mysql' else ''
    product = db.execute(text(f'SELECT product_id FROM `{schema}`.okki_products '
        'WHERE product_id=:pid AND disable_flag=0' + suffix), {'pid': product_id}).first()
    if not product:
        raise HTTPException(404, '产品不存在或已停用')
    rows = [dict(r) for r in db.execute(text(f'SELECT {", ".join(FIELDS)} FROM `{schema}`.okki_inventory '
        'WHERE product_id=:pid ORDER BY sku_id, warehouse_id' + suffix).columns(synced_at=DateTime()),
        {'pid': product_id}).mappings()]
    skus = {int(r[0]) for r in db.execute(text(f'SELECT sku_id FROM `{schema}`.okki_product_skus '
        'WHERE product_id=:pid' + suffix), {'pid': product_id})}
    skus.update(int(r['sku_id']) for r in rows)
    if not skus:
        raise HTTPException(409, '产品尚无小满 SKU 映射，请先同步产品资料')
    return sorted(skus), rows


def _quantity(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or abs(number) >= Decimal('100000000000') or number != number.quantize(Decimal('.0001')):
            raise ValueError('库存数量无效')
        return number
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('小满库存数量缺失或格式无效') from None


def _parse(data, product_id, sku_id):
    if not isinstance(data, dict) or not isinstance(data.get('list'), list):
        raise ValueError('小满库存列表不完整')
    rows = data['list']
    count = data.get('count')
    if isinstance(count, bool) or not str(count).isdigit() or int(count) != len(rows) or not rows:
        raise ValueError('小满库存列表不完整，请检查产品库存记录')
    result, warehouses = [], set()
    for row in rows:
        if (not isinstance(row, dict) or identifier(row.get('product_id')) != str(product_id)
                or identifier(row.get('sku_id')) != str(sku_id) or not identifier(row.get('warehouse_id'))):
            raise ValueError('小满库存产品或 SKU 映射不一致')
        warehouse = int(row['warehouse_id'])
        if warehouse in warehouses or isinstance(row.get('disable_flag'), bool) or str(row.get('disable_flag')) not in ('0', '1'):
            raise ValueError('小满库存仓库重复或启用状态无效')
        warehouses.add(warehouse)
        result.append(dict(product_id=product_id, sku_id=sku_id, warehouse_id=warehouse,
            enable_count=_quantity(row.get('enable_count')), real_count=_quantity(row.get('real_count')),
            disable_flag=int(row['disable_flag'])))
    return result


def _fetch(product_id, skus):
    token, _ = okki_client.fetch_token(scope=f'{okki_client.TOKEN_SCOPE} product')
    rows = []
    deadline = monotonic() + 90
    # Start time is conservative evidence for reservation handoff; completion
    # time would incorrectly certify stock read before a concurrent outbound.
    observed_at = beijing_now().replace(microsecond=0)
    with httpx.Client() as client:
        for sku in skus:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise ValueError('产品库存查询超时，请稍后重试')
            data = okki_client._get_json('/v1/product/inventory-list', token, context='库存同步',
                params={'sku_id': str(sku), 'count': 100, 'start_index': 1},
                client=client, timeout=min(15, remaining))
            if data is None:
                raise ValueError('小满库存鉴权失效，请重新同步')
            rows.extend(_parse(data, product_id, sku))
    return rows, observed_at


def _snapshot(rows):
    return [{key: value.isoformat() if hasattr(value, 'isoformat') else str(value) if isinstance(value, Decimal) else value
             for key, value in row.items()} for row in rows]


def _apply(db, product_id, old_rows, new_rows, observed_at):
    schema = get_settings().BUSINESS_DB_NAME
    old_keys = {(r['sku_id'], r['warehouse_id']) for r in old_rows}
    new_keys = {(r['sku_id'], r['warehouse_id']) for r in new_rows}
    if not old_keys.issubset(new_keys):
        raise HTTPException(409, '小满返回缺少已有仓库记录，未修改库存，请核对后重试')
    if any(r['synced_at'] and r['synced_at'] >= observed_at for r in old_rows):
        raise HTTPException(409, '已有更新的库存同步，请刷新列表后重试')
    for row in new_rows:
        params = {**row, 'enable_count': str(row['enable_count']), 'real_count': str(row['real_count']),
                  'synced_at': observed_at}
        if (row['sku_id'], row['warehouse_id']) in old_keys:
            db.execute(text(f'UPDATE `{schema}`.okki_inventory SET enable_count=:enable_count, '
                'real_count=:real_count, disable_flag=:disable_flag, synced_at=:synced_at '
                'WHERE product_id=:product_id AND sku_id=:sku_id AND warehouse_id=:warehouse_id'), params)
        else:
            # A foreign product claiming the same SKU/warehouse fails the PK;
            # never use upsert to reassign another product's inventory.
            db.execute(text(f'INSERT INTO `{schema}`.okki_inventory ({", ".join(FIELDS)}) '
                f'VALUES ({", ".join(":" + field for field in FIELDS)})'), params)


def sync_product_inventory(db, product_id, user):
    try:
        actor = _authorize(db, user)
        expected = _capture(db, product_id)
        db.rollback()  # No transaction or row locks across the provider request.
        rows, observed_at = _fetch(product_id, expected[0])
        _authorize(db, user)
        current = _capture(db, product_id, lock=True)
        if current != expected:
            raise HTTPException(409, '产品映射或库存已被其他同步更新，请刷新后重试')
        _apply(db, product_id, current[1], rows, observed_at)
        db.add(InventorySyncLog(product_id=product_id, created_by=actor,
            observed_at=observed_at, before_data=_snapshot(current[1]), after_data=_snapshot(rows)))
        db.commit()
        return {'product_id': product_id, 'inventory_rows': len(rows), 'synced_at': observed_at.isoformat()}
    except HTTPException:
        db.rollback()
        raise
    except (ValueError, OSError) as error:
        db.rollback()
        logger.warning('Product inventory sync rejected product=%s error=%s', product_id, type(error).__name__)
        print(f'[stock-sync] product={product_id} rejected ({type(error).__name__})', flush=True)
        message = '小满库存暂不可用，请稍后重试或联系管理员检查权限' if isinstance(error, okki_client.OkkiApiError) else str(error)
        raise HTTPException(502, message) from None
    except SQLAlchemyError as error:
        db.rollback()
        logger.warning('Product inventory sync persistence failed product=%s error=%s', product_id, type(error).__name__)
        print(f'[stock-sync] product={product_id} persistence failed ({type(error).__name__})', flush=True)
        raise HTTPException(503, '库存同步保存失败，请刷新列表核对结果后重试') from None
