"""Immutable receipt/list evidence and final-transaction funding reconciliation."""
from dataclasses import dataclass
from decimal import Decimal
import json
import logging

logger=logging.getLogger(__name__)
from app.invoice import settlement_service as shipments
from app.invoice import presale_runtime as pools
from app.invoice.freight_reconciliation_service import _canonical
from app.receipt import balance, reconciliation_service, remote, service, sync_service


@dataclass(frozen=True)
class FundingTarget:
    invoice: str
    freight: str | None
    receipts: tuple


@dataclass(frozen=True)
class FundingEvidence:
    target: FundingTarget
    valid: bool
    details: tuple
    goods: str
    freight: str | None


def freeze(invoice, graph):
    main={'order_id':invoice.xiaoman_order_id,'customer_id':invoice.customer_id,
        'currency':invoice.currency,'total_amount':str(invoice.total_amount),
        'surcharge_amount':str(invoice.surcharge_amount or 0)}
    target=graph.freight
    freight=None if target is None else json.dumps({key:getattr(target,key) for key in
        ('id','kind','version','remote_order_id','remote_order_name','remote_status','customer_id','currency')}
        | {'amount':str(target.amount)},sort_keys=True)
    selected=sorted({app.receipt_id for app in graph.applications if app.status!='released'})
    receipts=tuple((identity,graph.receipts[identity].status,graph.receipts[identity].xiaoman_receipt_id)
        for identity in selected)
    return FundingTarget(json.dumps(main,sort_keys=True),freight,receipts)


def _records(rows):
    if not isinstance(rows,list):raise ValueError('Incomplete funding list')
    records=[];identities=set()
    for row in rows:
        record=dict(reconciliation_service._record(row))
        identity=_canonical(record.get('cash_collection_id'))
        _canonical(record.get('order_id'))
        _canonical(record.get('collect_status'),zero=True)
        if str(record['collect_status']) not in {'0','1'} or identity in identities:
            raise ValueError('Unverified funding list')
        identities.add(identity);records.append(record)
    return records


def _main_detail(detail):
    if not isinstance(detail,dict):raise ValueError('Incomplete main detail')
    _canonical(detail.get('order_id'))
    company=detail.get('company_id')
    if isinstance(company,bool) or not isinstance(company,(str,int)) or not str(company).strip():
        raise ValueError('Incomplete customer')
    if not isinstance(detail.get('currency'),str) or not detail['currency'].strip():
        raise ValueError('Incomplete currency')
    remote.money(detail.get('amount'))


def read(db, target):
    details=[];valid=True
    for identity,status,remote_id in target.receipts:
        if status!='active' or not remote_id:
            valid=False;continue
        _canonical(remote_id)
        record=_records([remote.receipt_info(db,remote_id)])[0]
        for field in ('bank_charge','real_amount'):
            if record.get(field) is None:raise ValueError('Incomplete accepted receipt detail')
            remote.money(record[field])
        if str(record['cash_collection_id'])!=remote_id:raise ValueError('Changed receipt identity')
        details.append((identity,json.dumps(record,sort_keys=True,default=str)))
    main=json.loads(target.invoice);order_id=main['order_id']
    goods={'rows':[],'invoice_binding':[order_id,main['customer_id'],main['currency'],
        main['total_amount'],main['surcharge_amount']]}
    if order_id:
        _canonical(order_id)
        detail=remote.read(db,'/v1/invoices/order/info',{'order_id':order_id});_main_detail(detail)
        active=remote.order_active(db,detail)
        if not isinstance(active,bool):raise ValueError('Unverified main activity')
        valid=valid and active and (str(detail['order_id'])==order_id
            and str(detail['company_id'])==main['customer_id'] and detail['currency']==main['currency']
            and remote.money(detail['amount'])==Decimal(main['total_amount'])-Decimal(main['surcharge_amount']))
        goods['rows']=_records(remote.order_receipts(db,order_id))
    else:valid=False
    freight=None
    if target.freight:
        item=json.loads(target.freight);freight={'rows':[],'target_binding':[item['id'],item['remote_order_id'],
            item['amount'],item['currency'],item['customer_id'],item['version']]}
        if item['remote_status']=='bound' and item['remote_order_id']:
            _canonical(item['remote_order_id'])
            detail=remote.read(db,'/v1/invoices/order/info',{'order_id':item['remote_order_id']});_main_detail(detail)
            remote.money(detail.get('product_total_amount'))
            if not isinstance(detail.get('product_list'),list) or not isinstance(detail.get('name'),str):
                raise ValueError('Incomplete freight detail')
            active=remote.order_active(db,detail)
            if not isinstance(active,bool):raise ValueError('Unverified freight activity')
            valid=valid and active and (str(detail['order_id'])==item['remote_order_id']
                and detail['name']==item['remote_order_name'] and str(detail['company_id'])==item['customer_id']
                and detail['currency']==item['currency'] and remote.money(detail['amount'])==Decimal(item['amount'])
                and remote.money(detail['product_total_amount'])==0 and detail['product_list']==[])
            freight['rows']=_records(remote.order_receipts(db,item['remote_order_id']))
        else:valid=False
    return FundingEvidence(target,bool(valid),tuple(details),json.dumps(goods,sort_keys=True,default=str),
        json.dumps(freight,sort_keys=True,default=str) if freight is not None else None)


def apply(db, invoice, settlement, graph, evidence):
    # No supplier I/O or commits. Preserve accepted readback algorithms/log actor.
    for identity,encoded in evidence.details:
        row=graph.receipts[identity];data=json.loads(encoded)
        if sync_service.matches(row,data):
            sync_service.bind_remote(db,row,data,None)
        else:
            row.sync_status='uncertain'
            row.last_error='小满已创建回款，但金额、手续费、实到账金额、币种或关联订单不匹配，请核对远端原单'
            service.log(db,row,'uncertain',row.last_error)
    db.flush()  # Current financial queries must not erase unflushed readback.
    if not evidence.valid:return False
    goods=json.loads(evidence.goods);freight=json.loads(evidence.freight) if evidence.freight else None
    try:
        shipments.goods_balance(db,invoice,goods,current=True)
        if graph.freight:balance.calculate_target(db,graph.freight,freight,current=True)
        rows={'goods':{str(row['cash_collection_id']):row for row in goods['rows']},
            'freight':{str(row['cash_collection_id']):row for row in freight['rows']} if freight else {}}
        for app in graph.applications:
            if app.status=='released':continue
            receipt=graph.receipts[app.receipt_id]
            counterpart=rows[pools.source_component(app,receipt)].get(receipt.xiaoman_receipt_id)
            if counterpart is None or str(counterpart.get('collect_status'))!='1':return False
        selected=[app for app in graph.applications if app.status!='released']
        expected=pools.required(settlement.quote)
        if sum((app.amount for app in selected),Decimal(0))!=expected:return False
        if any(graph.receipts[app.receipt_id].status!='active'
                or graph.receipts[app.receipt_id].sync_status!='synced'
                or graph.receipts[app.receipt_id].collect_status!=1
                or graph.receipts[app.receipt_id].last_error for app in selected):return False
        summary=shipments.funding_balance(db,settlement,current=True)
        return Decimal(summary['remaining_amount'])==0 and Decimal(summary['effective_amount'])==expected
    except ValueError as error:
        # Diagnostic sinks must not cancel the authoritative risk state/audit.
        # Keep the two channels independent; never suppress process interrupts.
        try:
            logger.warning('Outbound funding did not verify (%s)',type(error).__name__)
        except Exception as diagnostic_error:
            db.info.setdefault('outbound_diagnostic_failures',[]).append({
                'sink':'logger','error':type(diagnostic_error).__name__})
        try:
            print('[shipment] complete funding evidence did not verify',flush=True)
        except Exception as diagnostic_error:
            db.info.setdefault('outbound_diagnostic_failures',[]).append({
                'sink':'stdout','error':type(diagnostic_error).__name__})
        # Complete valid evidence can disprove funding; technical reads never reach here.
        return False
