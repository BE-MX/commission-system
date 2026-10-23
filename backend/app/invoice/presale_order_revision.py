"""Explicit whole-order targets, immutable shipment sources and commercial credits.

Credits reduce future goods obligations; they never create payments or free cash.
All command callers hold the invoice lock. Normal append-batch orders have no
revision and keep their established behavior.
"""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from app.invoice.settlement_models import SettlementItem, ShipmentSettlement
from app.core.time import beijing_now
from uuid import uuid4


def config(invoice):
    value=getattr(invoice,'presale_order_revision',None)
    if value is None:return None
    if (not isinstance(value,dict) or value.get('schema_version')!=1
            or value.get('mode')!='whole_order' or not isinstance(value.get('sources'),dict)):
        raise ValueError('整单修订来源记录异常，请核对原单')
    return value


def sources(invoice, item_id):
    value=config(invoice)
    return list(value['sources'].get(str(item_id),[])) if value else []


def business_config(invoice):
    value=deepcopy(config(invoice))
    if value:value.pop('synced_projection',None)
    return value


def record_synced(invoice):
    value=deepcopy(config(invoice))
    if value is None:return
    value['synced_projection']={str(item.xiaoman_unique_id):{
        'quantity':item.quantity,'amount':str(item.total_price),'unit_price':str(item.price_per_piece or 0)}
        for item in invoice.items if not item.presale_archived}
    invoice.presale_order_revision=value


def used_credit(db, invoice, *, current=False):
    query=db.query(ShipmentSettlement).filter(ShipmentSettlement.invoice_id==invoice.id,
        ShipmentSettlement.state!='cancelled').order_by(ShipmentSettlement.id)
    if current:query=query.populate_existing().with_for_update()
    return sum((Decimal(row.quote.get('price_credit_applied','0')) for row in query.all()),Decimal(0))


def history(db, invoice, *, current=False):
    query=db.query(SettlementItem,ShipmentSettlement).join(ShipmentSettlement,
        ShipmentSettlement.id==SettlementItem.settlement_id).filter(
        ShipmentSettlement.invoice_id==invoice.id,ShipmentSettlement.state=='shipped')
    if current:query=query.order_by(SettlementItem.id).populate_existing().with_for_update()
    result={}
    for line,_ in query.all():
        quantity,amount=result.get(line.invoice_item_id,(0,Decimal(0)))
        result[line.invoice_item_id]=(quantity+line.quantity,amount+line.line_amount)
    return result


def recompute(db, invoice, *, current=False, persist=True):
    value=deepcopy(config(invoice))
    if value is None:return
    if Decimal(invoice.internal_accessory or 0) or Decimal(invoice.surcharge_amount or 0):
        raise ValueError('本整单修订仅支持无包装费和手续费的订单，费用调整请单独核对')
    quote_query=db.query(ShipmentSettlement).filter(ShipmentSettlement.invoice_id==invoice.id,
        ShipmentSettlement.state!='cancelled')
    if current:quote_query=quote_query.order_by(ShipmentSettlement.id).populate_existing().with_for_update()
    if any(Decimal(row.quote.get('packaging_amount','0')) or Decimal(row.quote.get('handling_amount','0'))
            for row in quote_query.all()):
        raise ValueError('历史批次存在包装费或手续费，不能套用商品整单修订')
    active={item.id:item for item in invoice.items if not item.presale_archived}
    all_items={item.id:item for item in invoice.items}
    facts=history(db,invoice,current=current);assigned=set();basis=[];credit=Decimal(0)
    for identity,item in active.items():
        refs=sources(invoice,identity)
        if len(set(refs))!=len(refs) or identity in refs:
            raise ValueError('整单历史来源重复')
        for source in refs:
            original=all_items.get(source)
            if (source in assigned or original is None or not original.presale_archived
                    or (original.product_id,original.sku_id)!=(item.product_id,item.sku_id)
                    or original.xiaoman_unique_id!=item.xiaoman_unique_id):
                raise ValueError('整单历史来源不属于当前产品或已重复使用')
            assigned.add(source)
        q=sum(facts.get(k,(0,0))[0] for k in refs+[identity])
        original_amount=sum((facts.get(k,(0,Decimal(0)))[1] for k in refs+[identity]),Decimal(0))
        if q>item.quantity:raise ValueError('整单数量不能小于历史已发数量')
        target=(Decimal(item.total_price)*q/item.quantity).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        credit+=original_amount-target
        basis.append({'item_id':identity,'source_item_ids':refs,'shipped_quantity':q,
            'historical_amount':str(original_amount),'target_shipped_amount':str(target),
            'quantity':item.quantity,'target_amount':str(item.total_price),
            'product_id':str(item.product_id),'sku_id':str(item.sku_id),'remote_uid':item.xiaoman_unique_id,
            'unit_price':str(item.price_per_piece or 0),'discount_amount':str(item.discount_amount or 0)})
    if set(k for k,(q,_) in facts.items() if q)-assigned-set(active):
        raise ValueError('整单修订遗漏已发产品，不能删除历史需求')
    used=used_credit(db,invoice,current=current)
    if credit<0 or credit<used:
        raise ValueError('已发部分调价不足以覆盖已使用抵扣，请先核对原批次')
    value.update(approved_credit=str(credit.quantize(Decimal('.01'))),line_basis=basis)
    if persist:invoice.presale_order_revision=value
    return value


def edit_context(db,invoice,body):
    value=config(invoice)
    if value is None:return None
    if Decimal(body.internal_accessory or 0) or Decimal(body.surcharge_amount or 0):
        raise ValueError('本整单修订不支持变更包装费或手续费，请先核对费用')
    current={item.id:item for item in invoice.items if not item.presale_archived}
    echoed=[line.id for line in body.items if line.id]
    if len(echoed)!=len(set(echoed)):raise ValueError('整单修订不能复制既有明细ID，请新增独立行')
    required={identity for identity in current if sources(invoice,identity)}
    facts=history(db,invoice)
    required|={identity for identity in current if facts.get(identity,(0,0))[0]}
    if not required.issubset(echoed):raise ValueError('不能删除整单中的已发产品')
    return {identity:{'item':item,'sources':sources(invoice,identity),'uid':item.xiaoman_unique_id}
        for identity,item in current.items()}


def finish_edit(db,invoice,context,pairs,actor=None):
    if context is None:return
    db.flush();mapping={}
    for item,previous_id in pairs:
        previous=context.get(previous_id)
        if previous:
            old=previous['item'];refs=list(previous['sources'])
            if old.presale_archived:refs.append(old.id)
            if refs and (item.product_id,item.sku_id)!=(old.product_id,old.sku_id):
                raise ValueError('已发产品不能更换规格，请新增独立产品行')
            item.xiaoman_unique_id=previous['uid']
            if refs:mapping[str(item.id)]=refs
    before=deepcopy(config(invoice))
    value=deepcopy(before);value['sources']=mapping
    value['revision']=int(value['revision'])+1
    value.update(updated_by=actor,updated_at=str(beijing_now()),request_id=str(uuid4()))
    invoice.presale_order_revision=value
    recompute(db,invoice)
    from app.shipping_inspection.models import ShippingOperationEvent
    db.add(ShippingOperationEvent(scope='presale-order-revision',request_id=value['request_id'],
        action='order_revised',source='invoice',outbound_record_id='invoice:'+str(invoice.id),
        operator_user_id=int(actor or 0),login_user_id=int(actor or 0),
        operator_name='订单修订',login_name='订单修订',
        payload={'invoice_id':invoice.id,'before':before,'after':deepcopy(invoice.presale_order_revision)},
        result={'remote_write':False,'cash_write':False}))


def apply_credit(db,invoice,result,*,current=False):
    value=config(invoice)
    if value is None:return
    # Recompute independently; persisted approval cannot silently change during
    # quoting or be supplied by a client. A changed history requires resaving.
    computed=recompute(db,invoice,current=current,persist=False)
    if computed['approved_credit']!=value['approved_credit']:
        raise ValueError('已发调价依据变化，请重新保存并核对整单')
    available=Decimal(value['approved_credit'])-used_credit(db,invoice,current=current)
    gross=Decimal(result['goods_amount']);applied=min(gross,available)
    if available<0:raise ValueError('已发调价抵扣已被其他批次占用')
    result.update(gross_goods_amount=str(gross),price_credit_applied=str(applied),
        price_credit_available=str(available),order_revision=value['revision'],
        goods_amount=str(gross-applied))


def approved_remote_line(invoice, source_id):
    """Resolve a historical row to its explicitly approved commercial successor."""
    if config(invoice) is None:return None
    rows=[item for item in invoice.items if not item.presale_archived
        and (source_id==item.id or source_id in sources(invoice,item.id))]
    if len(rows)!=1:raise ValueError('原批次缺少唯一整单修订来源')
    return rows[0]


def validate_credit(db,invoice,settlement,*,current=False):
    quote=settlement.quote
    if 'price_credit_applied' not in quote:return
    value=config(invoice)
    credit=Decimal(quote['price_credit_applied']);gross=Decimal(quote['gross_goods_amount'])
    if (value is None or credit<0 or credit>gross
            or gross-credit!=Decimal(quote['goods_amount'])
            or not 0<int(quote['order_revision'])<=value['revision']
            or used_credit(db,invoice,current=current)>Decimal(value['approved_credit'])):
        raise ValueError('原批次已发调价抵扣超额或与修订不一致')


def activate(db,invoice,mapping,previous_projection,*,actor,request_id,confirmation):
    """Audited internal maintenance command; caller supplies verified fixed facts.

    Not exposed as an employee bypass or an automatic SKU-based migration.
    Caller owns authority/fence, invoice locks, remote association preflight,
    transaction, immutable before backup and independent readback.
    """
    from app.invoice import service
    from app.shipping_inspection.models import ShippingOperationEvent
    if (invoice.order_type!='presale' or config(invoice) is not None or not confirmation.strip()
            or invoice.linked_sync_id or invoice.sync_status!='synced' or invoice.sync_attempt):
        raise ValueError('原单状态不允许首次整单修订，请读取原维护结果')
    if db.query(ShippingOperationEvent.id).filter_by(scope='presale-order-revision',request_id=request_id).first():
        raise ValueError('本次整单修订已记录，禁止重复执行')
    if db.query(ShipmentSettlement.id).filter(ShipmentSettlement.invoice_id==invoice.id,
            ShipmentSettlement.state.notin_(['shipped','cancelled'])).first():
        raise ValueError('存在尚未完成的原批次，不能修订整单')
    active={item.id:item for item in invoice.items if not item.presale_archived}
    originals={item.id:item for item in invoice.items if item.presale_archived}
    before={'total_amount':str(invoice.total_amount),'sources':{},'current_uids':{str(k):v.xiaoman_unique_id for k,v in active.items()}}
    removed=[]
    for identity,source_ids in mapping.items():
        item=active.get(int(identity))
        if item is None or not source_ids:raise ValueError('整单来源映射不完整')
        origin=[originals.get(identity) for identity in source_ids]
        if any(row is None for row in origin):raise ValueError('来源不是本单历史行')
        uids={row.xiaoman_unique_id for row in origin}
        if len(uids)!=1 or None in uids:raise ValueError('历史明细远端身份不唯一')
        uid=next(iter(uids))
        if uid not in previous_projection:raise ValueError('历史明细缺少上次核验的远端投影')
        if item.xiaoman_unique_id and item.xiaoman_unique_id!=uid:
            removed.append({'unique_id':item.xiaoman_unique_id,'product_id':item.product_id,'sku_id':item.sku_id,
                'product_kind':item.product_kind,'item_type':item.item_type,'custom_product_id':item.custom_product_id})
        item.xiaoman_unique_id=uid
    invoice.presale_order_revision={'schema_version':1,'mode':'whole_order','revision':1,
        'sources':deepcopy(mapping),'approved_credit':'0.00','request_id':request_id,
        'updated_by':actor,'updated_at':str(beijing_now()),'confirmation':confirmation,
        'synced_projection':deepcopy(previous_projection)}
    recompute(db,invoice,current=True)
    service._append_removed_lines(invoice,removed)
    invoice.sync_status='not_synced';invoice.status='ready';invoice.synced_at=None
    service._refresh_invoice_totals(invoice)
    db.add(ShippingOperationEvent(scope='presale-order-revision',request_id=request_id,
        action='revision_activated',source='invoice',outbound_record_id='invoice:'+str(invoice.id),
        operator_user_id=int(actor or 0),login_user_id=int(actor or 0),operator_name='用户确认整单修订',login_name='系统执行',
        payload={'invoice_id':invoice.id,'confirmation':confirmation,'before':before,'after':deepcopy(invoice.presale_order_revision)},
        result={'remote_write':False,'cash_write':False,'total_amount':str(invoice.total_amount),'removed_redundant_line_ids':removed}))
