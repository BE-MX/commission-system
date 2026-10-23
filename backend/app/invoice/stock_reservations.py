"""Whole-order stock claims derived from durable successful outbound generations.

No mirror writes. Live native availability is used while local claims exist or
the inventory mirror predates a completed task, so native occupation is never
subtracted twice. Task IDs define the stable allocation order.
"""
import json
import logging
from functools import wraps
from threading import Lock
from weakref import WeakKeyDictionary
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select, func
from app.invoice.models import Invoice, InvoiceItem, CustomProduct, InvoiceSyncLog, OkkiOutboundTask
from app.shipping_inspection.models import ShippingOperationEvent

logger = logging.getLogger(__name__)
WAREHOUSE_ID = '8193514242746'
SCOPE = 'outbound-stock-reservation'
NATIVE_SCOPE = 'outbound-stock-native'
ACTIVE = ('pending', 'waiting_stock', 'running', 'failed', 'uncertain')
_sqlite_fences = WeakKeyDictionary()


def quantities(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError('待出库产品快照不完整')
    result = defaultdict(Decimal)
    for row in rows:
        if row.get('remove'):
            continue
        product, sku = str(row.get('product_id')), str(row.get('sku_id'))
        amount = Decimal(str(row.get('count')))
        if (not product.isdigit() or not sku.isdigit() or int(product) <= 0 or int(sku) <= 0
                or not amount.is_finite() or amount <= 0 or amount != amount.to_integral_value()
                or amount > 9007199254740991):
            raise ValueError('待出库产品映射或数量无效')
        result[(int(product), int(sku))] += amount
    if not result:
        raise ValueError('待出库产品快照为空')
    return dict(result)


def remember(db, invoice):
    """Capture only a fully synced generation, before edits or with queue commit."""
    if invoice.sync_status != 'synced' or invoice.order_type == 'presale':
        return
    task = db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id == invoice.id))
    if task is None or (task.status not in (*ACTIVE, 'done') and not
            (task.status == 'skipped' and ((task.reason or '').startswith('existing:') or
             task.reason == 'Existing outbound requires manual handling'))):
        return
    from app.invoice.models import CustomProduct
    rows = []
    for item in invoice.items:
        if item.presale_archived:
            continue
        custom = db.get(CustomProduct, item.custom_product_id) if item.custom_product_id else None
        rows.append({'product_id': item.product_id or (custom.okki_product_id if custom else None),
            'sku_id': item.sku_id or (custom.okki_sku_id if custom else None), 'count': item.quantity})
    try:
        quantities(rows)
    except (ValueError, ArithmeticError):
        logger.warning('Unmapped outbound stock snapshot invoice=%s', invoice.id)
        print('[stock-reservation] unmapped order requires manual stock review', flush=True)
        return
    latest = db.execute(select(InvoiceSyncLog.id, InvoiceSyncLog.created_at).where(
        InvoiceSyncLog.invoice_id == invoice.id, InvoiceSyncLog.success == 1,
        InvoiceSyncLog.action.in_(('create', 'update'))).order_by(InvoiceSyncLog.id.desc()).limit(1)).first()
    key = f'{task.id}:{latest.id if latest else 0}'
    # Old completed tasks prove their complete original generation only while
    # no later successful order edit exists. Preserve that baseline before editing.
    if task.status == 'done' and latest and task.processed_at and latest.created_at <= task.processed_at:
        native = db.scalar(select(ShippingOperationEvent.id).where(
            ShippingOperationEvent.scope == NATIVE_SCOPE,
            ShippingOperationEvent.outbound_record_id == 'create:'+str(invoice.id)).limit(1))
        if native is None:
            _native_event(db, invoice.id, task.order_id, quantities(rows), evidence='completed_generation')
    previous = db.scalar(select(ShippingOperationEvent).where(
        ShippingOperationEvent.scope == SCOPE, ShippingOperationEvent.request_id == key))
    payload = {'order_id': str(task.order_id), 'warehouse_id': WAREHOUSE_ID,
        'product_list': [{k: row[k] for k in ('product_id', 'sku_id', 'count')} for row in rows if not row.get('remove')]}
    if previous:
        if previous.payload != payload:
            raise ValueError('原待出库代次的产品快照已变化')
        return
    db.add(ShippingOperationEvent(scope=SCOPE, request_id=key, action='stock_reserved',
        outbound_record_id='create:'+str(invoice.id), source='invoice',
        operator_user_id=0, login_user_id=0, operator_name='系统库存保留',
        login_name='系统库存保留', payload=payload, result={}))
    db.flush()


@dataclass(frozen=True)
class Claim:
    task_id: int
    invoice_id: int
    status: str
    processed_at: object
    amounts: dict


def _native_event(db, invoice_id, order_id, native, *, evidence='verified_readback'):
    db.add(ShippingOperationEvent(scope=NATIVE_SCOPE,request_id=uuid4().hex,action='stock_observed',
        outbound_record_id='create:'+str(invoice_id),source='invoice',operator_user_id=0,
        login_user_id=0,operator_name='系统库存核验',login_name='系统库存核验',
        payload={'order_id':str(order_id),'warehouse_id':WAREHOUSE_ID,'evidence':evidence,'product_list':[
            {'product_id':p,'sku_id':s,'count':str(q)} for (p,s),q in native.items()]},result={}))
    db.flush()


def remember_native(db, invoice_id, order_id, details):
    """Record exact live associations before marking an existing order skipped."""
    native = defaultdict(Decimal)
    for detail in details:
        if str(detail.get('invoice_warehouse_info', {}).get('id')) != WAREHOUSE_ID:
            raise ValueError('已有出库单的目标仓库无法确认，请核对原单')
        rows = detail.get('record_list')
        if not isinstance(rows, list) or not rows:
            raise ValueError('已有出库单明细无法确认')
        if any(str(row.get('order_id')) != str(order_id) for row in rows):
            raise ValueError('已有出库单包含其他订单')
        amounts = quantities([{'product_id':r.get('product_id'), 'sku_id':r.get('sku_id'),
                              'count':r.get('outbound_count')} for r in rows])
        for key, amount in amounts.items():
            native[key] += amount
    _native_event(db, invoice_id, order_id, native)


def claims(db, *, native_reader=None, native_keys=None, before_task_id=None, invoice_id=None):
    tasks = db.execute(select(OkkiOutboundTask.id.label('task_id'), OkkiOutboundTask.invoice_id,
        OkkiOutboundTask.order_id, OkkiOutboundTask.status.label('task_status'), OkkiOutboundTask.reason, OkkiOutboundTask.processed_at,
        Invoice.sync_status, Invoice.status.label('invoice_status')).join(Invoice, Invoice.id == OkkiOutboundTask.invoice_id)
        .where(Invoice.order_type != 'presale', Invoice.xiaoman_order_id == OkkiOutboundTask.order_id)
        .order_by(OkkiOutboundTask.id)).mappings().all()
    if not tasks:
        return []
    ids = [task['invoice_id'] for task in tasks]
    logs = db.execute(select(InvoiceSyncLog.id, InvoiceSyncLog.invoice_id, InvoiceSyncLog.created_at, InvoiceSyncLog.request_digest,
        InvoiceSyncLog.response_body).where(InvoiceSyncLog.invoice_id.in_(ids),
        InvoiceSyncLog.success == 1, InvoiceSyncLog.action.in_(('create', 'update')))
        .order_by(InvoiceSyncLog.id.desc())).mappings().all()
    latest = {}
    for log in logs:
        latest.setdefault(log['invoice_id'], log)
    snapshots = db.execute(select(ShippingOperationEvent.outbound_record_id, ShippingOperationEvent.payload,
        ShippingOperationEvent.request_id, ShippingOperationEvent.scope, ShippingOperationEvent.created_at).where(ShippingOperationEvent.scope.in_((SCOPE,NATIVE_SCOPE)),
        ShippingOperationEvent.outbound_record_id.in_(['create:'+str(identity) for identity in ids]))
        .order_by(ShippingOperationEvent.id.desc())).mappings().all()
    saved = {}
    for snapshot in snapshots:
        saved.setdefault((snapshot['scope'],snapshot['outbound_record_id']), snapshot)
    unresolved = db.execute(select(ShippingOperationEvent.payload).where(
        ShippingOperationEvent.scope == 'outbound-invoice-sync',
        ShippingOperationEvent.action.in_(('sync_pending','sync_sending','sync_uncertain')))).scalars().all()
    changing = {int(row['invoice_id']) for row in unresolved if row and row.get('invoice_id')}
    result = []
    for task in tasks:
        status, identity = task['task_status'], task['invoice_id']
        existing = status == 'skipped' and ((task['reason'] or '').startswith('existing:') or
                                           task['reason'] == 'Existing outbound requires manual handling')
        if status not in (*ACTIVE, 'done') and not existing:
            continue
        # An ambiguous send must not be freed by an unrelated lifecycle flag.
        if task['invoice_status'] == 'cancelled' and status not in ('running', 'uncertain'):
            continue
        log = latest.get(identity)
        original = saved.get((SCOPE,'create:'+str(identity)))
        payload = None
        if original and (task['sync_status'] != 'synced' or
                         original['request_id'] == f"{task['task_id']}:{log['id'] if log else 0}"):
            payload = original['payload']
            if str(payload.get('order_id')) != str(task['order_id']) or payload.get('warehouse_id') != WAREHOUSE_ID:
                raise ValueError('待出库保留的订单或仓库身份不一致')
        elif log and log['request_digest']:
            try:
                candidate = json.loads(log['request_digest'])
                if isinstance(candidate, dict) and 'product_list' in candidate:
                    response = json.loads(log['response_body'] or '{}')
                    if str(response.get('order_id')) != str(task['order_id']):
                        raise ValueError('待出库快照订单身份不一致')
                    payload = candidate
            except (TypeError, json.JSONDecodeError) as error:
                raise ValueError('待出库快照不可读取') from error
        if payload is None:
            if task['sync_status'] != 'synced':
                raise ValueError('历史待出库订单缺少已同步产品快照，请核对后重新同步')
            # Historical synced orders predate stock snapshots. A future edit
            # first persists remember(); never use a changed unsynced draft.
            rows = db.execute(select(func.coalesce(InvoiceItem.product_id, CustomProduct.okki_product_id).label('product_id'),
                func.coalesce(InvoiceItem.sku_id, CustomProduct.okki_sku_id).label('sku_id'), InvoiceItem.quantity.label('count'))
                .outerjoin(CustomProduct, CustomProduct.id == InvoiceItem.custom_product_id)
                .where(InvoiceItem.invoice_id == identity, InvoiceItem.presale_archived == 0)).mappings().all()
            payload = {'product_list': rows}
        amounts = quantities(payload.get('product_list'))
        observed_at = task['processed_at']
        if existing or status == 'done':
            native = saved.get((NATIVE_SCOPE,'create:'+str(identity)))
            if identity in changing:
                status = 'native_unknown'
            elif native and str(native['payload'].get('order_id')) == str(task['order_id']):
                if native['payload'].get('warehouse_id') != WAREHOUSE_ID:
                    raise ValueError('原生占库快照仓库不一致')
                transferred = quantities(native['payload']['product_list'])
                amounts = {key:max(Decimal(0),amount-transferred.get(key,0)) for key,amount in amounts.items()}
                status = 'done' if task['task_status'] == 'done' and not any(amounts.values()) else 'native_partial'
                observed_at = native['created_at']
            elif status == 'done' and log and task['processed_at'] and log['created_at'] <= task['processed_at']:
                pass  # Historical strict create succeeded after this complete generation.
            else:
                status = 'native_unknown'
                # A legacy task can be done before its last metadata/order edit,
                # with no native handoff snapshot. Do not reserve its whole
                # already-native quantity again when execution has live proof.
                if (native_reader is not None and identity != invoice_id
                        and (before_task_id is None or task['task_id'] < before_task_id)
                        and (native_keys is None or native_keys.intersection(amounts))):
                    transferred = native_reader(identity, str(task['order_id']))
                    amounts = {key:max(Decimal(0), amount-transferred.get(key, 0)) for key,amount in amounts.items()}
                    status = 'done' if task['task_status'] == 'done' and not any(amounts.values()) else 'native_partial'
        result.append(Claim(task['task_id'], identity, status, observed_at, amounts))
    return result


def fenced(function):
    """Serialize other stock-increasing outbound paths with both task executors."""
    @wraps(function)
    def execute(db, *args, **kwargs):
        if db.info.get('stock_executor_fence'):
            return function(db, *args, **kwargs)
        if db.get_bind().dialect.name == 'sqlite':
            # Isolated SQLite fixtures have no MySQL named-lock primitive.
            gate = _sqlite_fences.setdefault(db.get_bind(), Lock())
            if not gate.acquire(blocking=False):
                from fastapi import HTTPException
                raise HTTPException(409, '库存出库正在处理中，请稍后重新核对')
            try:
                db.info['stock_executor_fence'] = True
                return function(db, *args, **kwargs)
            finally:
                db.info.pop('stock_executor_fence', None)
                gate.release()
        from app.invoice.outbound_mode import executor_fence
        with executor_fence(db, require_fresh=False) as acquired:
            if not acquired:
                from fastapi import HTTPException
                raise HTTPException(409, '库存出库正在处理中，请稍后重新核对')
            return function(db, *args, **kwargs)
    return execute


def require_additional(db, payload, *, before=None, invoice_id=None):
    """Native already-held rows may be reused; only increased SKU totals need stock."""
    warehouse = str(payload.get('invoice_warehouse_id') or
                    (before or {}).get('invoice_warehouse_info', {}).get('id') or '')
    if warehouse != WAREHOUSE_ID:
        return
    merged = {(str(row.get('order_id')),str(row.get('order_record_id'))):row
              for row in (before or {}).get('record_list', [])}
    for row in payload.get('record_list', []):
        key = (str(row.get('order_id')),str(row.get('order_record_id')))
        if row.get('remove'):
            merged.pop(key,None)
        else:
            merged[key] = row
    wanted = quantities([{'product_id':row.get('product_id'), 'sku_id':row.get('sku_id'),
        'count':row.get('outbound_count')} for row in merged.values()]) if merged else {}
    previous = quantities([{'product_id':row.get('product_id'), 'sku_id':row.get('sku_id'),
        'count':row.get('outbound_count')} for row in (before or {}).get('record_list', [])]) if before else {}
    extra = {key:amount-previous.get(key,0) for key,amount in wanted.items() if amount>previous.get(key,0)}
    if not extra:
        return
    from app.invoice import shipment_inventory_service as live
    from app.invoice.native_stock_observation import reader as native_reader
    # Independent Core connection observes current committed queue generations,
    # even when the legacy caller already holds a RR invoice transaction.
    if db.get_bind().dialect.name == 'sqlite':
        held = protected(db, invoice_id=invoice_id, native_reader=native_reader(db), native_keys=set(extra))
    else:
        with db.get_bind().connect() as connection:
            held = protected(connection, invoice_id=invoice_id,
                             native_reader=native_reader(connection), native_keys=set(extra))
    target = live.StockTarget(invoice_id or 0, warehouse,
        tuple((index,str(p),str(s)) for index,(p,s) in enumerate(extra)))
    observed = live.observe(target)
    raw = {(int(row['product_id']),int(row['sku_id'])):row.get('available_stock')
           for row in observed.get('items', [])}
    for key, amount in extra.items():
        if raw.get(key) is None:
            raise ValueError('实时自由可用库存待核对，未发送出库')
        available = Decimal(str(raw[key]))
        if not available.is_finite() or available-held.get(key,0)<amount:
            raise ValueError('新增出库数量超过自由可用库存，其他待出库订单已保留')


def protected(db, *, invoice_id=None, before_task_id=None, native_reader=None, native_keys=None):
    result = defaultdict(Decimal)
    for claim in claims(db, native_reader=native_reader, native_keys=native_keys,
                       before_task_id=before_task_id, invoice_id=invoice_id):
        if claim.status == 'done' or claim.invoice_id == invoice_id:
            continue
        if before_task_id is not None and claim.task_id >= before_task_id:
            continue
        for key, amount in claim.amounts.items():
            result[key] += amount
    return dict(result)


def read_inventory(db, product_ids, *, invoice_id=None):
    from app.invoice import product_service as products, shipment_inventory_service as live
    raw = products._load_mirror_stocks(db, product_ids)
    capacity, free = {}, {}
    try:
        reservations = claims(db)
    except (ValueError, ArithmeticError, TypeError, KeyError) as error:
        logger.warning('Outbound stock reservation unavailable (%s)', type(error).__name__)
        print('[stock-reservation] reservation evidence unavailable', flush=True)
        return {}, {}
    keys = set(raw)
    amounts, own, earlier = defaultdict(Decimal), defaultdict(Decimal), defaultdict(Decimal)
    own_id = next((row.task_id for row in reservations if row.invoice_id == invoice_id), None)
    live_keys, unknown_keys = set(), set()
    for claim in reservations:
        for key, amount in claim.amounts.items():
            if key[0] not in product_ids:
                continue
            keys.add(key)
            if claim.status == 'native_unknown':
                unknown_keys.add(key)
            # Native completed tasks are not deducted again. A live read is
            # required until a strictly newer mirror observation is available.
            mirror_at = raw.get(key, (None, None))[1]
            if claim.status != 'done' or not mirror_at or not claim.processed_at or mirror_at <= claim.processed_at:
                live_keys.add(key)
            if claim.status != 'done':
                amounts[key] += amount
                if claim.invoice_id == invoice_id:
                    own[key] += amount
                elif own_id is not None and claim.task_id < own_id:
                    earlier[key] += amount
    if live_keys:
        target = live.StockTarget(invoice_id or 0, WAREHOUSE_ID,
            tuple((index, str(p), str(s)) for index, (p, s) in enumerate(sorted(live_keys))))
        observation = live.observe(target)
        for key in live_keys:
            raw.pop(key, None)  # Unknown live evidence never falls back to old mirror.
        for row in observation.get('items', []):
            key = (int(row['product_id']), int(row['sku_id']))
            if key not in live_keys or row.get('available_stock') is None:
                continue
            amount = Decimal(str(row['available_stock']))
            if amount.is_finite() and amount >= 0:
                raw[key] = (amount, None)
    for key in keys:
        if key in unknown_keys or key not in raw or raw[key][0] is None:
            continue
        amount = Decimal(str(raw[key][0]))
        free[key] = float(max(Decimal(0), amount-amounts[key]))
        # A retained demand is not proof of physical availability for this order.
        allocated = min(own[key], max(Decimal(0), amount-earlier[key]))
        capacity[key] = float(min(amount, Decimal(str(free[key]))+allocated))
    return free, capacity
