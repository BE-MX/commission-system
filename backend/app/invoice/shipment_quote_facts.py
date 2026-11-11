"""Business projections for shipment quotes and their local read boundaries."""
import hashlib
import json
from decimal import Decimal, InvalidOperation


LABELS = {'items': '产品行、数量或单价', 'amounts': '商品金额或费用', 'exchange_rates': '汇率',
          'funding': '回款、余额或资金分配', 'outbounds': '已有出库单或出库数量',
          'freight': '运费单或运费回款', 'document': '订单身份或发货资料'}

LOCAL_FIELDS = {
    'Invoice': 'id invoice_no order_type transaction_mode customer_id currency status sync_status xiaoman_order_id sales_user_id shipping_fee total_amount product_amount internal_accessory surcharge_amount presale_current_accessory presale_current_handling delivery_address remark inspection_requirement linked_sync_id cancellation',
    'InvoiceItem': 'id invoice_id sort_order product_kind item_type product_id sku_id custom_product_id xiaoman_unique_id quantity price_per_piece discount_amount total_price presale_archived presale_shipped_quantity presale_shipped_amount product_name',
    'Receipt': 'id invoice_id batch_id receivable_id purpose amount bank_charge reversed_amount reversed_bank_charge customer_id currency xiaoman_order_id xiaoman_receipt_id collect_status status sync_status attachment_ids collection_date payment_type',
    'ReceiptIntent': 'id invoice_id eligible status amount bank_charge purpose customer_id currency receipt_id attachment_ids collection_date payment_type created_by',
    'InvoiceAllocation': 'id invoice_id status',
    'ShipmentSettlement': 'id invoice_id sequence settlement_no state is_final quote',
    'SettlementItem': 'id settlement_id invoice_item_id quantity line_amount snapshot',
    'ShipmentOutbound': 'id invoice_id settlement_id outbound_no status remote_id payload remote_line_snapshot',
    'SettlementApplication': 'id settlement_id receipt_id component amount bank_charge released_amount released_bank_charge status',
    'Receivable': 'id invoice_id settlement_id business_key kind amount handling_amount customer_id currency remote_order_id remote_order_name remote_status version',
    'ReceiptBatch': 'id batch_no customer_id currency gross_amount bank_charge_total collection_date payment_type status request_key request_hash transaction_mode finance_status allocated_amount refunded_amount net_amount actual_bank_fee bank_account_id bank_reference rate_to_cny rate_to_usd confirmed_date',
    'BatchAttachment': 'batch_id attachment_id',
    'ReceiptLog': 'id receipt_id action message',
    'ReceiptAttachment': 'id invoice_id receipt_id storage_key sha256 size content_type created_by',
}
LOCAL_LABELS = {'Invoice': '订单身份、金额或发货资料', 'InvoiceItem': LABELS['items'],
                'InvoiceAllocation': '半成品分配', 'ShipmentSettlement': '历史批次或资金分配',
                'SettlementItem': '历史出库明细', 'ShipmentOutbound': LABELS['outbounds'],
                'Receivable': LABELS['freight'], 'ReceiptAttachment': '回款凭证绑定',
                'BatchAttachment': '回款凭证绑定'}


def pick(value, fields):
    return {key: value.get(key) if isinstance(value, dict) else getattr(value, key, None)
            for key in fields.split()}


def canonical(value, key=''):
    if isinstance(value, dict):
        return {str(k): canonical(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        rows = [canonical(row) for row in value]
        # Only row collections are unordered; positional bindings retain their order.
        return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, default=str)) if key in {
            'local', 'quoted', 'remote', 'record_list', 'receipts', 'outbounds', 'handlers', 'users'} else rows
    numeric = key.endswith(('_amount', '_price', '_quantity', '_count', '_charge')) or key in {
        'amount', 'quantity', 'count', 'sale_price', 'unit_price', 'exchange_rate', 'exchange_rate_usd',
        'price_per_piece', 'shipping_fee', 'internal_accessory', 'presale_current_accessory', 'presale_current_handling'}
    if isinstance(value, Decimal) or numeric and value is not None and not isinstance(value, bool):
        try:
            number = Decimal(str(value))
            if number.is_finite():
                return format(number.normalize(), 'f')
        except InvalidOperation:
            pass
    if value is not None and (key.endswith('_id') or key in {'id', 'status', 'collect_status'}):
        return str(value)
    return value


def digest(value):
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def local_facts(models):
    from app.invoice.presale_order_revision import business_config
    result = {}
    for model, rows in models:
        name = model.__name__
        if name == 'SettlementEvent':
            continue
        if name == 'ReceiptLog':
            rows = [row for row in rows if row.action in {'late_result', 'credit_effective'}]
        values = [pick(row, LOCAL_FIELDS[name]) for row in rows]
        if name == 'Invoice':
            for value, row in zip(values, rows):
                value['presale_order_revision'] = business_config(row)
        if name == 'Receipt':
            for value, row in zip(values, rows):
                value['has_error'] = bool(row.last_error)
        # The second Receipt group covers funding references beyond the original query.
        result.setdefault(name, []).extend(values)
    return {name: digest({'local': values}) for name, values in result.items()}


def changes(before, after, *, local=False):
    labels = LOCAL_LABELS if local else LABELS
    return '、'.join(dict.fromkeys(labels.get(key, LABELS['funding']) for key in sorted(set(before) | set(after))
                                 if before.get(key) != after.get(key)))


def receipt_facts(snapshot):
    return [pick(row, 'cash_collection_id order_id currency amount collect_status') for row in snapshot.get('rows', [])]


def quote_facts(invoice, quote, lines, evidence, receipts):
    order = evidence['order']
    order_lines = [pick(row, 'unique_id product_id sku_id count unit_price amount unit product_name to_outbound_count task_outbound_count')
                   for row in order.get('product_list', [])]
    outbounds = []
    for row in evidence['outbounds']:
        document = pick(row, 'outbound_invoice_id serial_id status currency source_type')
        document['company_id'] = (row.get('company_info') or {}).get('id')
        document['warehouse_id'] = (row.get('invoice_warehouse_info') or {}).get('id')
        document['handlers'] = [pick(handler, 'user_id') for handler in row.get('handler_info') or []]
        document['record_list'] = [pick(item, 'outbound_record_id order_id order_record_id product_id sku_id outbound_count sale_price product_unit cost_unit_price_rmb')
                                   for item in row.get('record_list', [])]
        outbounds.append(document)
    freight = {str(identity): {'receipts': receipt_facts(snapshot), 'binding': snapshot.get('target_binding')}
               for identity, snapshot in evidence.get('freight', {}).items()}
    amounts = {key: value for key, value in quote.items() if key not in {
        'invoice_no', 'delivery_address', 'remark', 'pool_balances', 'pool_applications', 'return_credit_sources',
        'items', 'capabilities', 'quote_hash', 'quote_facts'}}
    facts = {
        'items': {'local': [pick(row, LOCAL_FIELDS['InvoiceItem']) for row in invoice.items], 'quoted': lines, 'remote': order_lines},
        'amounts': amounts,
        'exchange_rates': {'main': pick(order, 'exchange_rate exchange_rate_usd'),
                           'receipt': {'exchange_rate': evidence['receipt'].get('exchange_rate')},
                           'freight': {str(k): {'exchange_rate': v.get('exchange_rate')} for k, v in evidence.get('freight', {}).items()}},
        'funding': {'remote': receipt_facts(evidence['receipt']),
                    'local': [dict(pick(row, LOCAL_FIELDS['Receipt']), has_error=bool(row.last_error)) for row in receipts],
                    'balances': quote.get('pool_balances'), 'applications': quote.get('pool_applications'),
                    'return_credit_sources': quote.get('return_credit_sources')},
        'outbounds': {'outbounds': outbounds}, 'freight': freight,
        'document': {'local': pick(invoice, LOCAL_FIELDS['Invoice']),
                     'remote': dict(pick(order, 'order_id company_id currency status amount product_total_amount handler departments'),
                                    users=[pick(user, 'user_id') for user in order.get('users') or []])},
    }
    return {key: digest(value) for key, value in facts.items()}
