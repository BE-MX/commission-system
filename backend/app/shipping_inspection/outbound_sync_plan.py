"""Pure, identity-based outbound edit planning and read-back verification."""
import hashlib
import json
from decimal import Decimal, InvalidOperation


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def index(rows, key):
    result = {}
    for row in rows:
        identity = str(row.get(key) or '')
        if not identity.isdigit() or int(identity) <= 0 or identity in result:
            raise ValueError('明细关联缺失或重复，不能自动匹配，请先在小满核对')
        result[identity] = row
    return result


def number(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('数量或价格无效') from exc
    if not result.is_finite():
        raise ValueError('数量或价格无效')
    return result


def build(before, order, products, remark, *, serial_id=None):
    if before.get('status') != 1:
        raise ValueError('仅待出库单可同步；已出库单请按实际发货办理补发或退货')
    if str(before.get('company_info', {}).get('id')) != str(order['company_id']) or before.get('currency') != order.get('currency'):
        raise ValueError('客户或币种不一致，请先核对原单')
    if not products:
        raise ValueError('订单没有可出库明细，请单独处理原出库单')
    old = index(before['record_list'], 'order_record_id')
    index(before['record_list'], 'outbound_record_id')
    wanted = index(products, 'unique_id')
    live = index(order['product_list'], 'unique_id')
    if set(wanted) != set(live):
        raise ValueError('最新方舟订单尚未同步到小满，请先在订单发票中完成同步')
    for identity, row in wanted.items():
        for key in ('product_id', 'sku_id', 'count', 'unit_price'):
            if number(row[key]) != number(live[identity][key]):
                raise ValueError('方舟与小满订单明细不一致，请先在订单发票中完成同步')
        if row.get('product_name') != live[identity].get('product_name'):
            raise ValueError('方舟与小满产品资料不一致，请先同步订单发票')
    if any(str(r.get('order_id')) != str(order['order_id']) for r in old.values()):
        raise ValueError('出库单包含其他订单，不能整单覆盖')
    edits, expected, changes = [], [], []
    material_order_ids = []
    for identity, product in wanted.items():
        previous = old.get(identity)
        row = dict(order_id=order['order_id'], order_record_id=int(identity),
                   product_id=product['product_id'], sku_id=product['sku_id'],
                   outbound_count=product['count'], sale_price=product['unit_price'],
                   product_name=product['product_name'], product_unit=product.get('unit') or 'Piece',
                   product_model=product.get('product_model') or '', product_cn_name=product.get('product_cn_name') or '')
        if number(row['outbound_count']) <= 0 or number(row['sale_price']) < 0:
            raise ValueError('出库数量必须大于零，单价不能为负数')
        if previous:
            row['outbound_record_id'] = previous['outbound_record_id']
            row['cost_unit_price_rmb'] = previous.get('cost_unit_price_rmb', 0)
        if previous is None or any(str(previous.get(k, '')) != str(row.get(k, '')) for k in (
                'product_id', 'sku_id', 'product_name', 'product_model', 'product_cn_name', 'product_unit')) \
                or number(previous['outbound_count']) != number(row['outbound_count']):
            material_order_ids.append(str(identity))
        edits.append(row)
        expected.append(row)
        if previous is None or any(str(previous.get(k, '')) != str(row.get(k, '')) for k in ('product_id', 'sku_id', 'product_name', 'product_model', 'product_cn_name', 'product_unit')) or any(number(previous[k]) != number(row[k]) for k in ('outbound_count', 'sale_price')):
            changes.append({'action': '修改' if previous else '新增', 'before': display(previous), 'after': display(row)})
    removed_order_ids = []
    for identity, previous in old.items():
        if identity not in wanted:
            removed_order_ids.append(str(identity))
            # OKKI validates row fields before applying remove, so retain the
            # original values even though the row will be deleted.
            removed = {key: previous[key] for key in (
                'outbound_record_id', 'outbound_count', 'sale_price', 'product_id', 'sku_id',
                'order_id', 'order_record_id', 'product_name', 'product_unit',
                'product_model', 'product_cn_name', 'cost_unit_price_rmb') if key in previous}
            edits.append({**removed, 'remove': 1})
            changes.append({'action': '删除', 'before': display(previous), 'after': None})
    handler = [str(x['user_id']) for x in before.get('handler_info', [])]
    if not handler:
        raise ValueError('小满出库单缺少处理人，请先补齐')
    # Deliberately omit status: never turn an externally shipped document back into pending.
    payload = {'outbound_invoice_id': before['outbound_invoice_id'], 'handler': handler,
               'remark': remark, 'record_list': edits}
    serial_changed = serial_id is not None and serial_id != before.get('serial_id')
    if serial_changed:
        payload['serial_id'] = serial_id
    remark_changed = (before.get('remark') or '') != remark
    return {'payload': payload, 'expected': expected, 'changes': changes,
            'serial_before': before.get('serial_id'),
            'serial_after': serial_id if serial_changed else before.get('serial_id'), 'serial_changed': serial_changed,
            'remark_before': before.get('remark') or '', 'remark_after': remark,
            'changed': bool(changes) or remark_changed or serial_changed,
            'material_order_ids': material_order_ids, 'removed_order_ids': removed_order_ids,
            'remark_changed': remark_changed,
            'requires_whole_recheck': remark_changed or bool(removed_order_ids),
            'material_changed': bool(material_order_ids or removed_order_ids or remark_changed or serial_changed)}


def display(row):
    return None if row is None else {'name': row.get('product_name'), 'model': row.get('product_model'),
        'quantity': row.get('outbound_count'), 'price': row.get('sale_price'), 'unit': row.get('product_unit')}


def verify(before, after, plan):
    actual = index(after.get('record_list', []), 'order_record_id')
    expected = index(plan['expected'], 'order_record_id')
    index(after.get('record_list', []), 'outbound_record_id')
    if set(actual) != set(expected):
        raise ValueError('同步后明细增删结果不一致，需人工核对')
    for identity, row in expected.items():
        for key in ('product_id', 'sku_id', 'order_id', 'order_record_id', 'outbound_count', 'sale_price'):
            if number(actual[identity][key]) != number(row[key]):
                raise ValueError('同步后产品、数量或价格不一致，需人工核对')
        for key in ('product_name', 'product_model', 'product_cn_name', 'product_unit'):
            if (actual[identity].get(key) or '') != (row.get(key) or ''):
                raise ValueError('同步后产品资料不一致，需人工核对')
        if row.get('outbound_record_id') and actual[identity]['outbound_record_id'] != row['outbound_record_id']:
            raise ValueError('同步改变了原明细身份，需人工核对')
        if row.get('outbound_record_id') and number(actual[identity]['cost_unit_price_rmb']) != number(row['cost_unit_price_rmb']):
            raise ValueError('成本价发生了非预期变化，需人工核对')
    allowed = {'record_list', 'remark', 'serial_id', 'update_time', 'update_user_info', 'product_total_count',
               'product_total_amount', 'product_total_amount_rmb', 'product_total_amount_usd'}
    if any(before.get(k) != after.get(k) for k in before if k not in allowed):
        raise ValueError('出库单状态或其他单头资料发生变化，需人工核对')
    if (after.get('remark') or '') != plan['remark_after']:
        raise ValueError('出库备注未同步，需人工核对')
    if after.get('serial_id') != plan['serial_after']:
        raise ValueError('出库单号未同步，需人工核对')


def missing_only(before, after, plan):
    """Return missing order IDs only when every present row and header matches the target."""
    actual = index(after.get('record_list', []), 'order_record_id')
    expected = index(plan['expected'], 'order_record_id')
    if not actual or not set(actual) < set(expected):
        raise ValueError('出库单并非仅缺少新增明细，需人工核对')
    missing = [identity for identity in expected if identity not in actual]
    if any(expected[identity].get('outbound_record_id') for identity in missing):
        raise ValueError('原有出库明细缺失，不能作为新增明细自动补齐')
    partial = {**plan, 'expected': [row for row in plan['expected']
                                    if str(row['order_record_id']) in actual]}
    verify(before, after, partial)
    return missing
