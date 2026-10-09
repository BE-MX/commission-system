"""Outbound creation payload and exact original-target verification, without I/O."""
from copy import deepcopy
from app.shipping_inspection import outbound_sync_plan as common
from app.invoice.outbound_followup_service import DESTINATION_WAREHOUSE_ID


def build(order, invoice_no, remark, serial=None):
    target=common.canonical_identity(order['order_id'])
    if not isinstance(invoice_no,str) or not invoice_no.strip() or not isinstance(remark,str):
        raise ValueError('Missing invoice header')
    rows=common.index(order['product_list'],'unique_id')
    if not rows or not isinstance(order.get('handler'),list) or not order['handler']:
        raise ValueError('Missing outbound items or handlers')
    handlers=[common.canonical_identity(value) for value in order['handler']]
    if len(set(handlers))!=len(handlers):raise ValueError('Duplicate handlers')
    result=[]
    for identity,row in rows.items():
        quantity=common.number(row['count']);price=common.number(row['unit_price'])
        if quantity<=0 or price<0:raise ValueError('Invalid outbound commercial row')
        result.append({'order_id':target,'order_record_id':identity,
            'product_id':common.canonical_identity(row['product_id']),
            'sku_id':common.canonical_identity(row['sku_id']),
            'outbound_count':float(quantity),'sale_price':float(price),
            'product_unit':row.get('unit') or 'Piece','product_name':row['product_name'],
            'product_model':row.get('product_model') or '', 'product_cn_name':row.get('product_cn_name') or ''})
    return {'serial_id':serial or invoice_no,'remark':remark,'status':1,'source_type':2,
        'currency':order['currency'],'exchange_rate':float(common.number(order.get('exchange_rate',0))),
        'exchange_rate_usd':float(common.number(order.get('exchange_rate_usd',0))),
        'invoice_warehouse_id':DESTINATION_WAREHOUSE_ID,'company_id':order['company_id'],
        'handler':handlers,'record_list':result}


def isolated(detail, target):
    common.canonical_identity(detail['outbound_invoice_id'])
    rows=detail['record_list']
    if not isinstance(rows,list) or not rows or any(common.canonical_identity(row['order_id'])!=target for row in rows):
        raise ValueError('Outbound contains unrelated order rows')
    common.index(rows,'outbound_record_id');common.index(rows,'order_record_id')


def verify(detail, payload, target, expected_id=None):
    isolated(detail,target)
    if expected_id is not None and common.canonical_identity(detail['outbound_invoice_id'])!=expected_id:
        raise ValueError('Original outbound identity changed')
    warehouse=common.canonical_identity(detail['invoice_warehouse_info']['id'])
    handlers=[common.canonical_identity(row['user_id']) for row in detail['handler_info']]
    if not handlers or len(set(handlers))!=len(handlers):raise ValueError('Invalid outbound handlers')
    if (warehouse!=common.canonical_identity(payload['invoice_warehouse_id'])
            or sorted(handlers)!=sorted(payload['handler'])
            or any(common.number(detail[field])!=common.number(payload[field]) for field in ('exchange_rate','exchange_rate_usd'))):
        raise ValueError('Outbound destination or commercial headers differ from original command')
    if (detail['serial_id']!=payload['serial_id'] or type(detail['status']) is not int or detail['status']!=1
            or str(detail['company_info']['id'])!=str(payload['company_id']) or detail['currency']!=payload['currency']
            or not common.remarks_match(detail.get('remark'),payload['remark'])):
        raise ValueError('Outbound header differs from original command')
    def signature(row):
        return (common.canonical_identity(row['order_id']),common.canonical_identity(row['order_record_id']),
            common.canonical_identity(row['product_id']),common.canonical_identity(row['sku_id']),
            common.number(row['outbound_count']),common.number(row['sale_price']),
            row.get('product_name'),row.get('product_model') or '',row.get('product_unit'))
    if sorted(map(signature,detail['record_list']))!=sorted(map(signature,payload['record_list'])):
        raise ValueError('Outbound rows differ from original command')
    return deepcopy(detail)


def occupied_orders(detail, serial):
    """Only complete canonical occupied serial evidence can justify a fallback."""
    common.canonical_identity(detail['outbound_invoice_id'])
    if detail['serial_id']!=serial:raise ValueError('Occupied serial identity differs')
    rows=detail['record_list']
    if not isinstance(rows,list) or not rows:raise ValueError('Occupied serial has no complete rows')
    common.index(rows,'outbound_record_id')
    pairs=set();orders=set()
    for row in rows:
        order=common.canonical_identity(row['order_id'])
        pair=(order,common.canonical_identity(row['order_record_id']))
        if pair in pairs:raise ValueError('Duplicate occupied serial order row')
        for field in ('product_id','sku_id'):common.canonical_identity(row[field])
        pairs.add(pair);orders.add(order)
    return orders
