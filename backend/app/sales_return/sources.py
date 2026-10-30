"""Read-only, exact original-order facts used by the sales return ledger.

Missing mirror identities or finance evidence are conflicts, never estimated facts.
No remote requests, mirror writes, token refreshes or local commits occur here.
"""
import hashlib
import json
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps

from fastapi import HTTPException
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from app.auth.models import ArkUserExternalBinding
from app.core.config import get_settings
from app.invoice.models import Invoice
from app.invoice.detail_outbounds import inspection_integrity
from app.invoice import presale_lines
from app.invoice.order_role import goods_order_sql
from app.order_intelligence.service import is_valid_business_order, NEW_DEAL_FIELD
from app.shipping_inspection import outbound_service as outbound, outbound_sync_state
from app.shipping_inspection.models import ShippingInspection, ShippingOperationEvent
from app.shipping_inspection.constants import LEGACY_OUTBOUND_BEFORE

logger = logging.getLogger(__name__)
CENT = Decimal('0.01')


def _conflict(message):
    raise HTTPException(409, message)


def _guard(function):
    @wraps(function)
    def read(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (SQLAlchemyError, outbound.OutboundTableError, ValueError) as exc:
            logger.warning('Sales return source unavailable: %s', type(exc).__name__)
            print('[sales-return] Source verification unavailable: ' + type(exc).__name__, flush=True)
            message = str(exc) if isinstance(exc, (ValueError, outbound.OutboundTableError)) else '原单镜像暂不可核验，请联系管理员检查同步与字段映射'
            raise HTTPException(409, message) from exc
    return read


def _schema():
    return get_settings().BUSINESS_DB_NAME


def _columns(db, table):
    # Inspect this request's connection: a second Engine checkout can roll back
    # an in-memory SQLite session and cannot share its transaction snapshot.
    return {row['name'] for row in inspect(db.connection()).get_columns(table, schema=_schema())}


def _require(db, table, columns):
    actual = _columns(db, table)
    missing = set(columns) - actual
    if missing:
        _conflict(f'原单镜像 {table} 缺少核验字段：{", ".join(sorted(missing))}，请先完善同步')
    return actual


def _rows(db, table, where, params):
    return [dict(row) for row in db.execute(text(f'SELECT * FROM `{_schema()}`.`{table}` WHERE {where}'), params).mappings()]


def _decimal(value, label, *, positive=False):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        _conflict(label + '缺失或无效，请核对原单')
    if not number.is_finite() or number < 0 or (positive and number <= 0):
        _conflict(label + '缺失或无效，请核对原单')
    return number


def _money(value):
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def source_role(snapshot, decisions):
    """Resolve one report's ruling using the original order identity and date.

    ``decisions`` is the validated index from order_decisions.decision_index.
    A return's effective date must never stand in for its original account date.
    """
    from app.battle_report.order_decisions import resolve_order_role
    source = snapshot.get('source', snapshot)
    day = source.get('account_date')
    try:
        day = day.date() if isinstance(day, datetime) else day if isinstance(day, date) else date.fromisoformat(str(day))
    except (TypeError, ValueError):
        return 'pending', '退货原订单核算日期缺少冻结证据；GMV保留，新签复购指标待核对'
    return resolve_order_role({'order_id': source.get('order_id'), 'order_no': source.get('order_no'),
        'company_id': source.get('customer_id'), 'user_id': source.get('owner_okki_user_id'),
        'account_date': day}, source.get('raw_new_deal'), decisions)


def _goods_order(db, order_id):
    return bool(db.scalar(text(f'''SELECT {goods_order_sql('o')}
        FROM `{_schema()}`.okki_orders o WHERE o.order_id=:oid'''), {'oid': str(order_id)}))


def _identity(value, label):
    if value is None or not str(value).strip():
        _conflict(label + '缺失，请核对原单精确关联')
    return str(value)


def _scope(db, user):
    if 'super_admin' in (user.get('roles') or []) or 'sales_return:read_all' in (user.get('permissions') or []):
        return None
    from app.sales_return.access import owner_id
    return owner_id(db, user)


def _documents(db, order):
    """Use the proven invoice bridge, retaining remote outbound line identities."""
    _require(db, outbound.ITEMS_TABLE, {'outbound_invoice_id', 'outbound_record_id', 'order_id', 'order_record_id', 'product_id', 'sku_id', 'outbound_count'})
    _require(db, outbound.RECORDS_TABLE, {'id', 'outbound_invoice_id', 'company_id'})
    rm = outbound._record_columns(db)
    header_columns = _columns(db, outbound.RECORDS_TABLE)
    item_columns = _columns(db, outbound.ITEMS_TABLE)
    extra = ', '.join((f"r.`{key}` AS `{key}`" if key in header_columns else f"NULL AS `{key}`")
        for key in ('currency', 'product_total_amount', 'product_total_amount_usd', 'exchange_rate_usd'))
    item_extra = ', '.join((f"i.`{key}` AS `{key}`" if key in item_columns else f"NULL AS `{key}`")
        for key in ('sale_count', 'sale_price', 'product_amount'))
    rows = db.execute(text(f'''SELECT {outbound._record_select(rm)},
        i.outbound_record_id AS remote_line_id, i.order_record_id, i.product_id,
        i.sku_id, i.outbound_count, {extra}, {item_extra}
        FROM `{_schema()}`.`{outbound.RECORDS_TABLE}` r
        JOIN `{_schema()}`.`{outbound.ITEMS_TABLE}` i ON i.outbound_invoice_id=r.outbound_invoice_id
        WHERE i.order_id=:oid AND {outbound.deleted_clause(db, rm)}
        ORDER BY r.id, i.outbound_record_id'''), {'oid': str(order['order_id'])}).mappings().all()
    documents = {}
    for row in rows:
        identity = _identity(row['outbound_invoice_id'], '原出库单 ID')
        if str(row['company_id']) != str(order['company_id']):
            _conflict('出库单与原订单客户不一致，请核对精确关联')
        document = documents.setdefault(identity, dict(row, record_id=str(row['outbound_record_id']), lines=[]))
        if document['record_id'] != str(row['outbound_record_id']):
            _conflict('同一出库单存在重复镜像，请先核对')
        document['lines'].append(dict(row))
    result = []
    for doc in documents.values():
        inspection = db.query(ShippingInspection).filter_by(outbound_record_id=doc['record_id']).one_or_none()
        event = db.query(ShippingOperationEvent).filter_by(scope=outbound_sync_state.SCOPE, request_id=doc['record_id']).one_or_none()
        doc['mirror_updated_at'] = doc.get('mirror_updated_at')
        integrity = inspection_integrity(db, doc, event)
        if integrity['inspection_blocked'] or integrity['quantity_unverified']:
            _conflict('原出库单同步或检验待复核，请先完成出库核对')
        # Same legacy cutoff as shipping inspection; date alone never marks modern generated outbounds shipped.
        if (inspection and inspection.status == 'submitted') or (not inspection and outbound.is_legacy_outbound(doc.get('outbound_date'))):
            result.append(doc)
    return result


def _original_lines(db, order, invoice, currency, documents):
    result = {}
    if invoice:
        projected = presale_lines.remote_items(invoice) if invoice.order_type == 'presale' else invoice.items
        for item in projected:
            identity = _identity(item.xiaoman_unique_id, '原订单明细 ID')
            if identity in result:
                _conflict('原订单明细 ID 重复，请核对原单')
            quantity = _decimal(presale_lines.remote_quantity(item), '原订单数量', positive=True)
            amount = _decimal(presale_lines.remote_amount(item), '原商品净额')
            result[identity] = {'product_id': _identity(item.product_id, '原产品 ID'), 'sku_id': _identity(item.sku_id, '原 SKU ID'),
                'quantity': quantity, 'amount': amount, 'amount_usd': amount if currency == 'USD' else None,
                'product_name': item.product_name, 'specification': '/'.join(str(x) for x in (item.model, item.color, item.length) if x)}
    else:
        columns = _require(db, 'okki_order_items', {'order_id', 'product_id', 'sku_id', 'quantity', 'amount', 'product_name'})
        # The real order-item mirror has a local id/item_index, not the remote
        # unique_id. Outbound rows themselves preserve the authoritative remote
        # order_record_id; do not join mirror rows by SKU/name or invent that ID.
        for document in documents:
            raw = outbound.inspection_item_links(db, document['record_id'])
            by_remote = {str(row.get('outbound_record_id')): row for row in raw}
            for shipped in document['lines']:
                row = by_remote[str(shipped['remote_line_id'])]
                identity = _identity(row.get('order_record_id'), '原订单明细 ID')
                candidate = {'product_id': _identity(row.get('product_id'), '原产品 ID'), 'sku_id': _identity(row.get('sku_id'), '原 SKU ID'),
                    'quantity': _decimal(row.get('sale_count'), '原订单销售数量', positive=True),
                    'amount': _decimal(row.get('sale_price'), '原销售单价') * _decimal(row.get('sale_count'), '原订单销售数量', positive=True),
                    'amount_usd': Decimal(0), 'product_name': _identity(row.get('product_name'), '原产品名称'),
                    'specification': str(row.get('product_model') or '')}
                if identity in result and result[identity] != candidate:
                    _conflict('同一历史订单行的原始销售数量或价格证据不一致')
                result[identity] = candidate
    if not result:
        _conflict('原订单商品明细尚未同步，请先核对原单')
    return result


def _payments(db, order, currency):
    _require(db, 'okki_receipts', {'cash_collection_id', 'order_id', 'company_id', 'amount', 'real_amount',
        'amount_usd', 'real_amount_usd', 'bank_charge', 'bank_charge_usd', 'service_fee_amount_usd', 'collection_date'})
    rows = _rows(db, 'okki_receipts', 'order_id=:oid', {'oid': order['order_id']})
    result, seen = [], set()
    for row in rows:
        identity = _identity(row.get('cash_collection_id'), '原回款 ID')
        if identity in seen or str(row.get('company_id')) != str(order['company_id']):
            _conflict('原回款重复或客户关联不一致')
        seen.add(identity)
        if str(row.get('collect_status')) not in ('0', '1'):
            _conflict('原回款财务生效状态缺失，请先补齐 collect_status 同步并核对原单')
        if str(row['collect_status']) == '0':
            continue
        if row.get('currency') != currency:
            _conflict('原回款币种缺失或与订单不一致，请核对原单')
        amount_usd = _decimal(row.get('amount_usd'), '原回款美元金额')
        fee_usd = _decimal(row.get('service_fee_amount_usd'), '原回款美元手续费')
        amount = _decimal(row.get('amount'), '原币回款金额', positive=True)
        actual = _decimal(row.get('real_amount'), '原币实际到账金额')
        actual_usd = _decimal(row.get('real_amount_usd'), '美元实际到账金额')
        bank_charge = _decimal(row.get('bank_charge'), '原币银行手续费')
        bank_charge_usd = _decimal(row.get('bank_charge_usd'), '美元银行手续费')
        if abs(amount - actual - bank_charge) > CENT or abs(amount_usd - actual_usd - bank_charge_usd) > CENT:
            _conflict('原回款到账金额与银行手续费不一致，请核对费用口径')
        principal_usd = actual_usd - fee_usd
        if principal_usd < 0:
            _conflict('原回款手续费超过本金，请核对原单')
        if currency == 'USD':
            if abs(amount - amount_usd) > CENT or abs(actual - actual_usd) > CENT:
                _conflict('美元回款原币与美元金额不一致，请核对原单')
            principal = principal_usd
        else:
            if amount_usd <= 0:
                _conflict('非美元原回款缺少有效美元折算，请核对原单')
            # amount_usd/amount is verified by the same original receipt, unlike
            # exchange_rate which can represent an unrelated RMB conversion.
            rate = amount_usd / amount
            if abs(actual * rate - actual_usd) > CENT:
                _conflict('原回款到账金额的美元折算不一致，请核对原单')
            principal = actual - fee_usd / rate
            if principal < 0:
                _conflict('原回款手续费超过本金，请核对原单')
        collection_date = str(row.get('collection_date') or '')[:10]
        from datetime import date
        try:
            date.fromisoformat(collection_date)
        except ValueError:
            _conflict('原回款业务日期无效，请核对原单')
        result.append({'payment_id': identity, 'principal': _money(principal), 'principal_usd': _money(principal_usd),
            'collection_date': collection_date, 'currency': currency,
            'commission_basis_usd': _money(amount_usd - fee_usd),
            'bank_charge': _money(bank_charge), 'bank_charge_usd': _money(bank_charge_usd),
            'service_fee_usd': _money(fee_usd)})
    return sorted(result, key=lambda row: (row['collection_date'], row['payment_id']))


@_guard
def snapshot(db, order_id, user):
    scope = _scope(db, user)
    _require(db, 'okki_orders', {'order_id', 'company_id', 'user_id', 'order_no', 'name', 'account_date', 'status', 'status_name', 'trail', 'custom_fields', 'departments'})
    matches = _rows(db, 'okki_orders', 'order_id=:oid', {'oid': str(order_id)})
    if not matches or (scope is not None and str(matches[0].get('user_id')) != scope):
        raise HTTPException(404, '原订单不存在或无权查看')
    order = matches[0]
    owner = _identity(order.get('user_id'), '原业务员 ID')
    if '个人' in str(order.get('trail') or ''):
        _conflict('个人订单不属于外贸退货范围')
    if not _goods_order(db, order_id):
        _conflict('独立运费或费用订单不属于商品退货范围，请核对原商品订单')
    invoice = db.query(Invoice).options(selectinload(Invoice.items)).filter_by(xiaoman_order_id=str(order_id)).one_or_none()
    if invoice and str(invoice.customer_id) != str(order['company_id']):
        _conflict('方舟 PI 与原订单客户不一致')
    documents = _documents(db, order)
    if not documents:
        _conflict('原订单尚无已实际发货证据；生成待出库单不能退货')
    currencies = {str(doc.get('currency') or '').strip().upper() for doc in documents}
    if len(currencies) != 1 or '' in currencies:
        _conflict('原出库币种缺失或不一致，请先核对原单')
    currency = str(order.get('currency') or (invoice.currency if invoice else next(iter(currencies)))).strip().upper()
    if not currency or len(currency) != 3 or not currency.isalpha():
        _conflict('原订单币种尚未核验，请先补齐原币字段')
    if invoice and invoice.currency != currency:
        _conflict('方舟 PI 与原订单币种不一致')
    if currencies != {currency}:
        _conflict('原出库单与订单币种不一致')
    original = _original_lines(db, order, invoice, currency, documents)
    lines, seen, quantities = [], set(), {}
    for doc in documents:
        for row in doc['lines']:
            outbound_id = _identity(doc['outbound_invoice_id'], '原出库单 ID')
            line_id = _identity(row['remote_line_id'], '原出库明细 ID')
            key = outbound_id + ':' + line_id
            order_line_id = _identity(row['order_record_id'], '原订单明细 ID')
            source = original.get(order_line_id)
            if key in seen or not source or (str(row['product_id']), str(row['sku_id'])) != (source['product_id'], source['sku_id']):
                _conflict('原出库行无法精确匹配订单明细，请核对原行 ID、产品和 SKU')
            seen.add(key)
            quantity = _decimal(row['outbound_count'], '实际发货数量', positive=True)
            if quantity != quantity.to_integral_value():
                _conflict('原出库数量不是整件，请核对单位')
            quantities[order_line_id] = quantities.get(order_line_id, Decimal(0)) + quantity
            if quantities[order_line_id] > source['quantity']:
                _conflict('实际发货数量超过原订单数量，请核对原单')
            net = _decimal(row.get('product_amount'), '原出库商品净额')
            if currency == 'USD':
                net_usd = net
            else:
                original_total = _decimal(doc.get('product_total_amount'), '原出库商品总额', positive=True)
                usd_total = _decimal(doc.get('product_total_amount_usd'), '原出库商品美元总额', positive=True)
                net_usd = net * usd_total / original_total
            lines.append({'source_key': key, 'outbound_id': outbound_id, 'outbound_line_id': line_id, 'order_line_id': order_line_id,
                'product_id': source['product_id'], 'sku_id': source['sku_id'], 'product_name': source['product_name'],
                'specification': source['specification'], 'quantity': int(quantity),
                'net_amount': _money(net), 'net_amount_usd': _money(net_usd)})
    if invoice:
        goods = sum((line['amount'] for line in original.values()), Decimal(0))
    else:
        goods_rows = _rows(db, 'okki_order_items', 'order_id=:oid', {'oid': order['order_id']})
        if not goods_rows:
            _conflict('历史订单商品净额明细缺失，请先同步原单')
        goods = sum((_decimal(row.get('amount'), '原订单商品净额') for row in goods_rows), Decimal(0))
        if currency != 'USD':
            original_quantity = sum((_decimal(row.get('quantity'), '原订单数量', positive=True) for row in goods_rows), Decimal(0))
            shipped_quantity = sum((Decimal(line['quantity']) for line in lines), Decimal(0))
            shipped_amount = sum((Decimal(line['net_amount']) for line in lines), Decimal(0))
            if original_quantity != shipped_quantity or abs(goods - shipped_amount) > CENT:
                _conflict('历史非美元订单须完整实际出库且数量、原币货款与订单镜像一致，部分出库尚不能证明原应收币种口径')
    if currency == 'USD':
        goods_usd = goods
    else:
        rates = {_decimal(doc.get('product_total_amount_usd'), '原商品美元总额', positive=True) /
                 _decimal(doc.get('product_total_amount'), '原商品总额', positive=True) for doc in documents}
        if len(rates) != 1:
            _conflict('分批原商品美元折算不一致，原应收美元净额待核对')
        goods_usd = goods * next(iter(rates))
    departments = order.get('departments')
    departments = json.loads(departments) if isinstance(departments, str) else departments
    if isinstance(departments, dict) and departments:
        departments = [departments]
    if not isinstance(departments, list) or not departments or any(not isinstance(item, dict) for item in departments):
        _conflict('原订单部门拆分缺失或无效，请先核对原单')
    if any(not str(item.get('department_id', item.get('id'))).isdigit()
           or int(item.get('department_id', item.get('id'))) <= 0 for item in departments):
        _conflict('原订单部门拆分的部门 ID 必须为正整数，请先核对原单')
    from app.dingtalk.gmv_daily_service import _parse_allocations
    allocations, _, fatal = _parse_allocations(goods_usd, departments, str(order.get('order_no') or order_id))
    if fatal or not allocations:
        _conflict('原订单部门拆分无法用于原归属业绩核算：' + '；'.join(fatal))
    fields = order.get('custom_fields')
    fields = json.loads(fields) if isinstance(fields, str) else fields
    raw_new_deal = fields.get(NEW_DEAL_FIELD) if isinstance(fields, dict) else None
    original_day = order.get('account_date')
    try:
        original_day = original_day.date() if isinstance(original_day, datetime) else original_day if isinstance(original_day, date) else date.fromisoformat(str(original_day))
    except (TypeError, ValueError):
        _conflict('原订单核算日期缺失或无效，无法冻结原单身份与业绩依据')
    customer = _rows(db, 'customer_info', 'company_id=:cid', {'cid': order['company_id']})
    if not customer or not customer[0].get('company_name'):
        _conflict('原订单客户名称尚未同步')
    result = {'order_id': str(order_id), 'order_no': _identity(order.get('order_no'), '原订单号'),
        'customer_id': str(order['company_id']), 'customer_name': customer[0]['company_name'],
        'owner_okki_user_id': owner, 'sales_user_id': invoice.sales_user_id if invoice else None,
        'invoice_id': invoice.id if invoice else None, 'currency': currency,
        'goods_amount': _money(goods), 'goods_amount_usd': _money(goods_usd),
        'gmv_eligible': is_valid_business_order(order['status'], order['status_name'], order['trail']),
        'account_date': original_day.isoformat(), 'raw_new_deal': raw_new_deal,
        'departments': departments, 'lines': lines, 'payments': _payments(db, order, currency)}
    result['order_role'] = source_role(result, {})[0]
    result['binding_hash'] = hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return result


def _page(items, page, page_size):
    page, page_size = max(1, int(page)), min(100, max(1, int(page_size)))
    return {'items': items[(page-1)*page_size:page*page_size], 'total': len(items), 'page': page, 'page_size': page_size}


def _options(db, user, customer_id='', keyword=''):
    scope = _scope(db, user)
    _require(db, 'okki_orders', {'order_id', 'order_no', 'name', 'company_id', 'user_id', 'trail'})
    _require(db, outbound.ITEMS_TABLE, {'outbound_invoice_id', 'order_id'})
    _require(db, outbound.RECORDS_TABLE, {'id', 'outbound_invoice_id', 'company_id'})
    rm = outbound._record_columns(db)
    if not rm['outbound_date']:
        _conflict('原出库镜像缺少出库日期，不能核验历史已发货范围')
    local_key = 'CAST(r.id AS CHAR)'
    if db.get_bind().dialect.name == 'mysql':
        local_key += ' COLLATE utf8mb4_unicode_ci'
    clauses = ["(o.trail IS NULL OR o.trail NOT LIKE '%个人%')", goods_order_sql('o'), outbound.deleted_clause(db, rm),
        f"(si.status='submitted' OR (si.id IS NULL AND r.`{rm['outbound_date']}` IS NOT NULL AND r.`{rm['outbound_date']}` < :legacy_before))"]
    params = {'legacy_before': LEGACY_OUTBOUND_BEFORE.isoformat()}
    if scope is not None:
        clauses.append('o.user_id=:owner')
        params['owner'] = scope
    if customer_id:
        clauses.append('o.company_id=:cid')
        params['cid'] = str(customer_id)
    if keyword:
        clauses.append('o.order_no LIKE :keyword')
        params['keyword'] = '%' + keyword.replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
        clauses[-1] += " ESCAPE '!'"
    # Group once in SQL: pickers must not issue one shipment/customer query per
    # historical order or re-read every order for each page of customers.
    rows = db.execute(text(f'''SELECT DISTINCT o.order_id, o.order_no,
        o.company_id AS customer_id, c.company_name AS customer_name,
        o.user_id AS owner_okki_user_id
        FROM `{_schema()}`.okki_orders o
        JOIN `{_schema()}`.`{outbound.ITEMS_TABLE}` i ON i.order_id=o.order_id
        JOIN `{_schema()}`.`{outbound.RECORDS_TABLE}` r ON r.outbound_invoice_id=i.outbound_invoice_id AND r.company_id=o.company_id
        LEFT JOIN ark_shipping_inspections si ON si.outbound_record_id={local_key}
        LEFT JOIN `{_schema()}`.customer_info c ON c.company_id=o.company_id
        WHERE {' AND '.join(clauses)} ORDER BY o.order_id DESC'''), params).mappings().all()
    return [{key: str(value) if value is not None else None for key, value in row.items()} for row in rows]


@_guard
def orders(db, user, customer_id='', keyword='', page=1, page_size=20):
    return _page(_options(db, user, customer_id, keyword), page, page_size)


@_guard
def customers(db, user, keyword='', page=1, page_size=20):
    items = _options(db, user)
    grouped = {}
    for row in items:
        if keyword and keyword.casefold() not in str(row['customer_name'] or '').casefold() and keyword not in row['customer_id']:
            continue
        target = grouped.setdefault(row['customer_id'], {'customer_id': row['customer_id'], 'customer_name': row['customer_name'], 'shipped_order_count': 0})
        target['shipped_order_count'] += 1
    return _page(sorted(grouped.values(), key=lambda item: (str(item['customer_name']), item['customer_id'])), page, page_size)
