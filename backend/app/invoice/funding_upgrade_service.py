"""Audited unpaid V1 funding upgrade. Supplier GETs never hold business locks."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import json
import re
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from app.core.time import beijing_now

from app.invoice import edit_authority, linked_outbound_service, okki_client, presale_runtime as pools
from app.invoice import settlement_service as shipments, shipment_create_service as facts
from app.invoice import shipment_retry_service, shipment_state_service
from app.invoice.models import InvoiceItem
from app.invoice.presale_funding import FundingLot, plan_funding
from app.invoice.settlement_models import (ShipmentSettlement, SettlementItem, Receivable, ReceiptBatch,
    SettlementApplication, ShipmentOutbound, SettlementEvent, SettlementFundingAmendment)
from app.invoice.settlement_schemas import ShipmentCreate
from app.portal.authority import lock_authority
from app.portal.errors import PortalError, TransactionBusy
from app.receipt import access, authority, edit_service, remote, service as receipts
from app.receipt.models import Receipt, ReceiptIntent, ReceiptLog, ReceiptAttempt


def values(row):
    return json.loads(json.dumps({column.name:getattr(row,column.name)
        for column in row.__table__.columns},default=str))


def cash_facts(receipt):
    return {key:value for key,value in values(receipt).items() if key in {
        'id','invoice_id','batch_id','receivable_id','receipt_no','source','auto_key','request_key','request_hash',
        'amount','bank_charge','currency','customer_id','collection_date','payment_type','remark','attachment_ids',
        'xiaoman_order_id','xiaoman_receipt_id','xiaoman_receipt_no','created_by','created_at'}}


@dataclass(frozen=True)
class Lookup:
    main: object
    freight: object
    cash: dict


@dataclass
class Graph:
    invoice: object
    settlement: object
    receipt: object
    freight: object
    intent: object
    items: tuple
    originals: tuple
    applications: tuple
    settlements: tuple
    receipts: tuple
    outbounds: tuple
    logs: tuple
    attempts: tuple
    amendment: object
    binding: str


def _capture(db, identity, body, user):
    authority.fresh_boundary(db)
    try:
        lock_authority(db,force=True)
        current=authority.current_user(db,user,'invoice:write','shipment:write','receipt:write')
        invoice_id=db.scalar(select(ShipmentSettlement.invoice_id).where(ShipmentSettlement.id==identity))
        if invoice_id is None:raise HTTPException(404,'订单或发货结算不存在')
        invoice=edit_authority.lock_document(db,invoice_id,force=True)
        if invoice is None:raise HTTPException(404,'订单或发货结算不存在')
        db.refresh(invoice,with_for_update=True); access.ensure_invoice(db,invoice,current)
        if invoice.order_type!='presale' or invoice.shipping_fee:
            raise ValueError('仅主单运费为零的预售单支持资金升级')
        receipts.ensure_order_ready(db,invoice,current=True)
        rows=facts._rows
        settlements=rows(db,ShipmentSettlement,ShipmentSettlement.invoice_id==invoice.id)
        settlement=next((row for row in settlements if row.id==identity),None)
        receipt_rows=rows(db,Receipt,or_(Receipt.invoice_id==invoice.id,Receipt.id==body.receipt_id))
        receipt=next((row for row in receipt_rows if row.id==body.receipt_id),None)
        if settlement is None or receipt is None:raise ValueError('原结算或首款关联已变化')
        items=rows(db,SettlementItem,SettlementItem.settlement_id==identity)
        originals=rows(db,InvoiceItem,InvoiceItem.invoice_id==invoice.id)
        if not items or any(item.invoice_item_id not in {row.id for row in originals} for item in items):
            raise ValueError('原结算产品关联已变化')
        targets=rows(db,Receivable,or_(Receivable.invoice_id==invoice.id,Receivable.settlement_id==identity))
        freight=[row for row in targets if row.settlement_id==identity]
        if len(freight)>1 or any(row.kind!='freight' for row in freight):raise ValueError('原运费目标关联异常')
        target=freight[0] if freight else None
        intents=rows(db,ReceiptIntent,or_(ReceiptIntent.invoice_id==invoice.id,ReceiptIntent.receipt_id==receipt.id))
        if len(intents)>1:raise ValueError('首款意图关联异常')
        intent=intents[0] if intents else None
        apps=rows(db,SettlementApplication,or_(SettlementApplication.settlement_id.in_([row.id for row in settlements]),
            SettlementApplication.receipt_id.in_([row.id for row in receipt_rows])))
        outbounds=rows(db,ShipmentOutbound,or_(ShipmentOutbound.invoice_id==invoice.id,
            ShipmentOutbound.settlement_id.in_([row.id for row in settlements])))
        logs=rows(db,ReceiptLog,ReceiptLog.receipt_id.in_([row.id for row in receipt_rows]))
        attempts=rows(db,ReceiptAttempt,ReceiptAttempt.receipt_id.in_([row.id for row in receipt_rows]))
        amendments=rows(db,SettlementFundingAmendment,or_(SettlementFundingAmendment.invoice_id==invoice.id,
            SettlementFundingAmendment.request_key==body.request_key,SettlementFundingAmendment.settlement_id==identity))
        matching=[row for row in amendments if row.request_key==body.request_key or row.settlement_id==identity]
        if len(matching)>1:raise ValueError('资金升级记录关联异常')
        amendment=matching[0] if matching else None
        binding=shipments.digest([shipment_retry_service._binding(db,invoice,settlement),
            [values(row) for row in amendments], [values(row) for row in outbounds], [values(row) for row in attempts]])
        graph=Graph(invoice,settlement,receipt,target,intent,tuple(items),tuple(originals),tuple(apps),tuple(settlements),
            tuple(receipt_rows),tuple(outbounds),tuple(logs),tuple(attempts),amendment,binding)
        return graph,current
    except TransactionBusy:raise
    except PortalError as error:
        raise HTTPException(error.status,'资金升级授权暂不可用',
            headers={'Cache-Control':'private, no-store','Pragma':'no-cache'}) from None


def _amount(quote,key):
    if key not in quote:raise ValueError('原报价资金字段不完整')
    return remote.money(quote[key])


def _legacy_money(graph):
    row,invoice,target=graph.settlement,graph.invoice,graph.freight
    quote=row.quote
    if (not isinstance(quote,dict) or quote.get('funding_version') not in {None,1}
            or quote.get('currency')!=invoice.currency or quote.get('invoice_id')!=invoice.id
            or quote.get('customer_id')!=invoice.customer_id or quote.get('invoice_no')!=invoice.invoice_no
            or quote.get('is_final') is not bool(row.is_final) or quote.get('quote_hash')!=row.quote_hash
            or not re.fullmatch(r'[a-f0-9]{64}',row.quote_hash)):
        raise ValueError('原报价身份或摘要不完整，不能升级')
    g,p,h,f=(_amount(quote,key) for key in ('goods_amount','packaging_amount','handling_amount','freight_amount'))
    d,dc,gd,gc,due=(_amount(quote,key) for key in ('deposit_applied','deposit_charge_applied',
        'goods_payment_due','goods_payment_charge','new_payment_due'))
    if d or dc or gd!=g+p+h or gc!=h or due!=gd+f:
        raise ValueError('原报价金额不能证明本批未付款，不能升级')
    expected=sorted((item.invoice_item_id,item.quantity,item.line_amount) for item in graph.items)
    try:
        actual=sorted((part['invoice_item_id'],part['quantity'],remote.money(part['line_amount'])) for part in quote['items'])
    except (KeyError,TypeError,ValueError):raise ValueError('原报价产品快照不完整') from None
    if actual!=expected or len(actual)!=len({part[0] for part in actual}) or sum(part[2] for part in expected)!=g:
        raise ValueError('原报价商品金额与冻结明细不一致')
    for item in graph.items:
        snapshot=item.snapshot
        original=next(part for part in graph.originals if part.id==item.invoice_item_id)
        if (not isinstance(snapshot,dict) or str(snapshot.get('order_id'))!=invoice.xiaoman_order_id
                or not re.fullmatch(r'[1-9][0-9]*',str(snapshot.get('order_record_id','')))
                or type(item.quantity) is not int or item.quantity<=0 or snapshot.get('outbound_count')!=item.quantity
                or snapshot.get('product_id')!=original.product_id or snapshot.get('sku_id')!=original.sku_id
                or str(snapshot.get('order_record_id'))!=str(original.xiaoman_unique_id)):
            raise ValueError('原结算产品身份或数量不完整')
    if f and (target is None or target.invoice_id!=invoice.id or target.kind!='freight'
            or target.settlement_id!=row.id or target.business_key!=f'settlement:{row.id}:freight'
            or target.customer_id!=invoice.customer_id or target.currency!=invoice.currency or target.amount!=f
            or target.handling_amount or target.remote_status!='bound' or not target.remote_order_id
            or not target.remote_order_name or target.remote_payload is None
            or shipments.digest(target.remote_payload)!=target.remote_payload_hash):
        raise ValueError('原运费目标身份、金额或冻结载荷不一致')
    if not f and target is not None:raise ValueError('零运费原报价存在额外目标')
    hashes=set()
    # Decimal wire strings retain trailing zeros in old request hashes. These
    # candidates have exactly the same frozen cents; no monetary fallback.
    variants={str(f),format(f,'.2f'),format(f.normalize(),'f')}
    if f*10==(f*10).to_integral_value():variants.add(format(f,'.1f'))
    for amount in variants:
        body=ShipmentCreate(items=[{'invoice_item_id':part['invoice_item_id'],'quantity':part['quantity']}
            for part in quote['items']],
            freight_amount=amount,is_final=bool(row.is_final),quote_hash=row.quote_hash,request_key=row.request_key)
        hashes.update({shipments.digest(body.model_dump(mode='json')),
            shipments.digest(body.model_dump(mode='json',exclude={'is_final'}))})
    if row.request_hash not in hashes:
        raise ValueError('原创建请求摘要与冻结商品、运费不一致')
    return g+p,h,f


def _check_fresh(db,graph,body):
    row,receipt,invoice=graph.settlement,graph.receipt,graph.invoice
    if row.version!=body.version or receipt.version!=body.receipt_version:raise ValueError('原结算或首款版本已变化')
    if row.state not in {'awaiting_payment','paused'}:raise ValueError('仅未付款或暂停的旧批次支持资金升级')
    active=[entry for entry in graph.settlements if entry.state not in {'shipped','cancelled'}]
    if len(active)!=1 or active[0].id!=row.id:raise ValueError('必须是本订单唯一活动结算')
    if (len(graph.receipts)!=1 or receipt.invoice_id!=invoice.id or receipt.customer_id!=invoice.customer_id
            or receipt.currency!=invoice.currency or receipt.xiaoman_order_id!=invoice.xiaoman_order_id
            or receipt.purpose not in pools.POOL_PURPOSES or receipt.status!='active' or receipt.sync_status!='synced'
            or receipt.collect_status!=1 or not receipt.xiaoman_receipt_id or receipt.last_error or receipt.batch_id
            or receipt.lease_until and receipt.lease_until>beijing_now() or remote.net_amount(receipt)<=0):
        raise ValueError('原首款不是唯一已核验、未占用的预售现金')
    if any(attempt.handled_at is None for attempt in graph.attempts):
        raise ValueError('原首款存在未处理的发送结果，不能升级')
    if receipt.attempt_token:
        completed=next((attempt for attempt in graph.attempts if attempt.token==receipt.attempt_token),None)
        if (receipt.send_phase!='verified' or completed is None or completed.receipt_id!=receipt.id
                or completed.remote_id!=receipt.xiaoman_receipt_id or completed.handled_at is None):
            raise ValueError('原首款历史发送令牌缺少完成证据')
    if graph.applications or graph.outbounds or any(log.action=='late_result' for log in graph.logs):
        raise ValueError('已有资金分配、出库或迟到结果，不能升级')
    if db.scalar(select(ReceiptBatch.id).where(ReceiptBatch.request_key==row.request_key).with_for_update()):
        raise ValueError('本批已有真实付款批次，不能升级')
    target,intent=graph.freight,graph.intent
    if receipt.source=='auto' and intent is None:raise ValueError('自动首款缺少原回款意图')
    if receipt.receivable_id:
        main=db.scalar(select(Receivable).where(Receivable.id==receipt.receivable_id).with_for_update()
            .execution_options(populate_existing=True))
        if (main is None or main.invoice_id!=invoice.id or main.settlement_id is not None or main.kind!='goods'
                or main.business_key!=f'invoice:{invoice.id}:goods' or main.remote_order_id!=invoice.xiaoman_order_id
                or main.customer_id!=invoice.customer_id or main.currency!=invoice.currency):
            raise ValueError('原首款应收目标身份已变化')
    if target and (target.lease_until and target.lease_until>beijing_now() or target.last_error):
        raise ValueError('运费目标存在未完成发送')
    if intent and (intent.invoice_id!=invoice.id or intent.receipt_id!=receipt.id or intent.status!='converted'
            or intent.lease_until or intent.attempt_token or intent.last_error
            or intent.amount!=receipt.amount or intent.currency!=receipt.currency or intent.customer_id!=receipt.customer_id
            or intent.collection_date!=receipt.collection_date or intent.payment_type!=receipt.payment_type
            or intent.attachment_ids!=receipt.attachment_ids
            or intent.bank_charge is not None and intent.bank_charge!=receipt.bank_charge
            or intent.purpose is not None and intent.purpose!=receipt.purpose):
        raise ValueError('首款意图与冻结现金不一致')
    return _legacy_money(graph)


def _lookup(graph):
    invoice,target=graph.invoice,graph.freight
    main=edit_service.OrderTarget(invoice.id,invoice.xiaoman_order_id,invoice.customer_id,
        invoice.currency,invoice.total_amount,invoice.surcharge_amount)
    freight=facts.FreightTarget(*(getattr(target,key) for key in facts.FreightTarget.__dataclass_fields__)) if target else None
    return Lookup(main,freight,cash_facts(graph.receipt))


def _read_evidence(db,lookup):
    main,freight=lookup.main,lookup.freight
    snapshot=remote.order_snapshot(db,main)
    facts._validate_receipts(snapshot,main.currency,invoice_binding=remote.invoice_binding(main))
    detail=remote.read(db,'/v1/invoices/order/info',{'order_id':main.xiaoman_order_id})
    if (not isinstance(detail,dict) or str(detail.get('order_id'))!=main.xiaoman_order_id
            or str(detail.get('company_id'))!=main.customer_id or detail.get('currency')!=main.currency
            or remote.money(detail.get('amount'))!=main.total_amount-Decimal(main.surcharge_amount or 0)
            or not remote.order_active(db,detail)):
        raise ValueError('主单活动身份不可验证')
    main_outbounds=linked_outbound_service.find_related(db,detail)
    facts._validate_outbounds(main_outbounds)
    cash=lookup.cash
    live=remote.receipt_info(db,cash['xiaoman_receipt_id'])
    from app.receipt.sync_service import matches
    expected_cash=SimpleNamespace(xiaoman_order_id=cash['xiaoman_order_id'],currency=cash['currency'],
        amount=Decimal(cash['amount']),bank_charge=Decimal(cash['bank_charge']),
        collection_date=date.fromisoformat(cash['collection_date']))
    if (not isinstance(live,dict) or str(live.get('cash_collection_id'))!=cash['xiaoman_receipt_id']
            or not matches(expected_cash,live)
            or str(live.get('order_id'))!=cash['xiaoman_order_id'] or live.get('currency')!=cash['currency']
            or remote.money(live.get('amount'))!=Decimal(cash['amount'])-Decimal(cash['bank_charge'])
            or live.get('collection_date')!=cash['collection_date'] or str(live.get('collect_status'))!='1'
            or len(snapshot['rows'])!=1 or str(snapshot['rows'][0].get('cash_collection_id'))!=cash['xiaoman_receipt_id']
            or remote.money(snapshot['rows'][0].get('amount'))!=remote.money(live['amount'])
            or str(snapshot['rows'][0].get('collect_status'))!='1'):
        raise ValueError('远端原首款身份、金额、日期或生效状态已变化')
    fr_snapshot,fr_detail,fr_outbounds=None,None,[]
    if freight:
        from app.invoice.freight_delivery import _verify
        fr_snapshot=remote.target_snapshot(db,freight)
        facts._validate_receipts(fr_snapshot,freight.currency,target_binding=[freight.id,freight.remote_order_id,
            str(freight.amount),freight.currency,freight.customer_id,freight.version])
        fr_detail=remote.read(db,'/v1/invoices/order/info',{'order_id':freight.remote_order_id})
        if (not isinstance(fr_detail,dict) or not remote.order_active(db,fr_detail) or not _verify(freight,fr_detail)
                or isinstance(fr_detail.get('product_total_count'),bool) or str(fr_detail.get('product_total_count'))!='0'):
            raise ValueError('原运费单活动身份或零商品证据不一致')
        fr_outbounds=linked_outbound_service.find_related(db,fr_detail)
        facts._validate_outbounds(fr_outbounds)
        if fr_snapshot['rows']:raise ValueError('原运费单已有回款，不能升级')
    if main_outbounds or fr_outbounds:raise ValueError('主单或运费单已有远端出库，不能升级')
    materials={'main':detail,'main_receipts':snapshot,'receipt':live,'main_outbounds':main_outbounds,
        'freight':fr_detail,'freight_receipts':fr_snapshot,'freight_outbounds':fr_outbounds}
    # Remote responses can carry provider pictures, signed URLs and unrelated
    # custom fields. Audit only verified financial facts and canonical digests.
    def project(data,keys):
        return {key:data[key] for key in keys if key in data}
    cash_keys=('cash_collection_id','order_id','amount','real_amount','bank_charge','bank_charge_rmb',
        'bank_charge_usd','currency','collection_date','collect_status')
    order_keys=('order_id','name','company_id','amount','currency','create_time')
    def receipt_summary(data,binding):
        return {'rows':[project(part,cash_keys) for part in data['rows']],binding:data[binding],
            'count':len(data['rows'])} if data else None
    evidence={'verified_at':beijing_now().isoformat(),
        'main':{**project(detail,order_keys),'active_verified':True},
        'receipt':project(live,cash_keys),'main_receipts':receipt_summary(snapshot,'invoice_binding'),
        'main_outbounds':{'count':0},'freight_outbounds':{'count':0},
        'freight':{**project(fr_detail,order_keys),'active_verified':True,'product_total_count':0,
            'product_total_amount':'0.00','product_list':[]} if fr_detail else None,
        'freight_receipts':receipt_summary(fr_snapshot,'target_binding'),
        'digests':{key:shipments.digest(value) for key,value in materials.items()}}
    return json.loads(json.dumps(evidence,default=str))


def _snapshot(graph,apps=()):
    return {'settlement':values(graph.settlement),'receipt':values(graph.receipt),
        'intent':values(graph.intent) if graph.intent else None,'freight':values(graph.freight) if graph.freight else None,
        'items':[values(item) for item in graph.items],'applications':[values(app) for app in apps]}


def _apply(db,graph,body,current,evidence):
    goods,handling,freight=_check_fresh(db,graph,body)
    row,receipt=graph.settlement,graph.receipt
    before=_snapshot(graph)
    plan=plan_funding(str(goods),str(handling),str(freight),[FundingLot(receipt.id,'presale_advance',
        str(receipt.amount),str(receipt.bank_charge),effective=True)],is_final=bool(row.is_final))
    quote=deepcopy(row.quote)
    quote.update(funding_version=2,pool_applications=plan['applications'],pool_balances=plan['balances'],
        funding_total_amount=format(goods+handling+freight,'.2f'),deposit_applied='0.00',deposit_charge_applied='0.00',
        advance_applied=plan['applied_amount'],goods_payment_due=plan['goods_payment_due'],
        goods_payment_charge=plan['goods_charge_due'],freight_payment_due=plan['freight_payment_due'],
        new_payment_due=plan['additional_payment_due'],additional_payment_due=plan['additional_payment_due'],deposit_receipt_id=None)
    quote.pop('quote_hash',None)
    quote['quote_hash']=shipments.digest({'quote':quote,'original_quote_hash':row.quote_hash,
        'upgrade_request':body.model_dump(mode='json'),'evidence':evidence,'cash':cash_facts(receipt)})
    if quote['quote_hash']==row.quote_hash:raise ValueError('资金升级摘要未变化')
    previous=receipt.purpose
    receipt.purpose='presale_advance'; receipt.version+=1
    if graph.intent:
        graph.intent.purpose='presale_advance'; graph.intent.bank_charge=receipt.bank_charge
    receipts.log(db,receipt,'purpose_changed',f'Funding upgrade {previous} -> presale_advance; {body.reason}',access.user_id(current))
    row.quote=quote; row.quote_hash=quote['quote_hash']; row.version+=1
    db.flush()
    for part in plan['applications']:
        shipments.application(db,row,receipt,part['component'],Decimal(part['amount']),Decimal(part['bank_charge']))
    apps=facts._rows(db,SettlementApplication,SettlementApplication.settlement_id==row.id)
    amendment=SettlementFundingAmendment(settlement_id=row.id,invoice_id=graph.invoice.id,receipt_id=receipt.id,
        request_key=body.request_key,request_hash=shipments.digest(body.model_dump(mode='json')),before_snapshot=before,
        after_snapshot=_snapshot(graph,apps),evidence=evidence,actor_id=access.user_id(current),reason=body.reason)
    db.add(amendment)
    db.add(SettlementEvent(settlement_id=row.id,action='upgrade_funding',reason=body.reason,actor_id=access.user_id(current)))
    db.flush()
    return _result(db,graph,amendment)


def _replay(db,graph,body,current):
    amendment=graph.amendment
    row,receipt=graph.settlement,graph.receipt
    if (amendment.request_key!=body.request_key or amendment.request_hash!=shipments.digest(body.model_dump(mode='json'))
            or amendment.actor_id!=access.user_id(current) or amendment.invoice_id!=graph.invoice.id
            or amendment.settlement_id!=row.id or amendment.receipt_id!=receipt.id):
        raise HTTPException(409,'资金升级标识已用于其他提交，请读取原批核对')
    after=amendment.after_snapshot
    immutable={'id','invoice_id','sequence','settlement_no','is_final','quote','quote_hash','request_key','request_hash','created_by','created_at'}
    if any(values(row)[key]!=after['settlement'][key] for key in immutable):raise ValueError('资金升级后原结算冻结事实已变化')
    saved_cash={key:after['receipt'][key] for key in cash_facts(receipt)}
    if cash_facts(receipt)!=saved_cash or receipt.purpose!=after['receipt']['purpose']:
        raise ValueError('资金升级后原首款现金事实已变化')
    if [values(item) for item in graph.items]!=after['items']:raise ValueError('资金升级后产品冻结事实已变化')
    fr_keys={'id','invoice_id','settlement_id','business_key','kind','amount','handling_amount','currency','customer_id',
        'remote_order_id','remote_order_name','remote_payload','remote_payload_hash','created_at'}
    if bool(graph.freight)!=bool(after['freight']) or graph.freight and any(
            values(graph.freight)[key]!=after['freight'][key] for key in fr_keys):raise ValueError('资金升级后运费冻结事实已变化')
    if bool(graph.intent)!=bool(after['intent']) or graph.intent and any(values(graph.intent)[key]!=after['intent'][key]
            for key in ('id','invoice_id','receipt_id','amount','bank_charge','purpose','currency','customer_id',
                'collection_date','payment_type','remark','attachment_ids','created_by')):
        raise ValueError('资金升级后首款意图冻结事实已变化')
    apps=[app for app in graph.applications if app.settlement_id==row.id]
    keys=('id','settlement_id','receipt_id','component','amount','bank_charge','created_at')
    if ([{key:values(app)[key] for key in keys} for app in apps]
            !=[{key:part[key] for key in keys} for part in after['applications']]):
        raise ValueError('资金升级后分配冻结事实已变化')
    expected='released' if row.state=='cancelled' else 'applied' if row.state=='shipped' else 'reserved'
    if any(app.status!=expected for app in apps):raise ValueError('资金升级后分配状态与原批不一致')
    pools.pool_lots(db,graph.invoice,current=True)
    pools.validate_quote_applications(row,apps,{receipt.id:receipt})
    return _result(db,graph,amendment)


def _result(db,graph,amendment):
    return {'amendment':{'id':amendment.id,'request_key':amendment.request_key,'receipt_id':amendment.receipt_id,
        'actor_id':amendment.actor_id,'reason':amendment.reason,'created_at':str(amendment.created_at),
        'before_quote':deepcopy(amendment.before_snapshot['settlement']['quote']),
        'before_quote_hash':amendment.before_snapshot['settlement']['quote_hash'],
        'after_quote':deepcopy(amendment.after_snapshot['settlement']['quote']),
        'after_quote_hash':amendment.after_snapshot['settlement']['quote_hash']},
        'settlement':shipments.describe(db,graph.settlement,current=True)}


def upgrade(db,identity,body,user):
    graph,current=_capture(db,identity,body,user)
    if graph.amendment:return _replay(db,graph,body,current)
    _check_fresh(db,graph,body)
    expected,lookup=graph.binding,_lookup(graph)
    db.commit()
    try:
        evidence=_read_evidence(db,lookup)
        db.commit()
    except (ValueError,TypeError,okki_client.OkkiApiError,SQLAlchemyError,OSError,HTTPException) as error:
        shipment_state_service.result_unavailable(error)
    finally:
        transaction=db.get_transaction()
        if transaction is not None and not transaction.is_active:db.close()
        else:db.rollback()
        db.expire_all()
    graph,current=_capture(db,identity,body,user)
    if graph.amendment:return _replay(db,graph,body,current)
    if graph.binding!=expected or _lookup(graph)!=lookup:
        raise HTTPException(409,'原批次、首款或运费在核验期间已变化，请读取原批核对')
    return _apply(db,graph,body,current,evidence)
