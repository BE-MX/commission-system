"""Whole-order reservations, warehouse scope and native-stock handoff (isolated DB)."""
import json
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.core.time import beijing_now
from app.invoice import product_service, shipment_inventory_service
from app.invoice.models import Invoice, InvoiceItem, InvoiceSyncLog, OkkiOutboundTask

WAREHOUSE = '8193514242746'


@pytest.mark.parametrize('native,remaining', [(10,0),(4,6),(0,10)])
def test_historical_edit_credits_only_live_native_subset(stock, native, remaining):
    from app.invoice.stock_reservations import protected
    db,_ = stock
    invoice,task = reserve(db,[(1,11,10)],status='done')
    db.add(InvoiceSyncLog(invoice_id=invoice.id,action='update',success=1,
        created_at=task.processed_at+timedelta(seconds=1),
        request_digest=json.dumps({'product_list':[{'product_id':1,'sku_id':11,'count':10}]}),
        response_body=json.dumps({'order_id':task.order_id})))
    db.flush()
    assert protected(db)=={(1,11):10}  # Baseline used to double-count the native outbound.
    calls=[]
    def observe(identity,order_id):
        calls.append((identity,order_id));return {(1,11):native}
    result=protected(db,before_task_id=task.id+1,native_reader=observe,native_keys={(1,11)})
    assert result.get((1,11),0)==remaining
    assert calls==[(invoice.id,task.order_id)]
    for options in [{'invoice_id':invoice.id},{'before_task_id':task.id},{'native_keys':{(2,22)}}]:
        calls.clear();protected(db,native_reader=observe,**options);assert calls==[]


def test_live_native_does_not_override_unresolved_outbound_changes(stock):
    from app.invoice.stock_reservations import protected
    from app.shipping_inspection.models import ShippingOperationEvent
    db,_=stock
    invoice,task=reserve(db,[(1,11,10)],status='done')
    db.add(ShippingOperationEvent(scope='outbound-invoice-sync',request_id='inflight-native',
        source='pc',action='sync_uncertain',outbound_record_id='OB1',operator_user_id=0,login_user_id=0,
        operator_name='Test',login_name='Test',payload={'invoice_id':invoice.id},result={}))
    db.flush()
    assert protected(db,native_reader=lambda *args:pytest.fail('Unresolved change must not be credited'))=={(1,11):10}


@pytest.fixture
def stock(db, monkeypatch):
    db.execute(text('CREATE TABLE lsordertest.okki_product_skus (product_id INTEGER, sku_id INTEGER)'))
    db.execute(text('CREATE TABLE lsordertest.okki_inventory (product_id INTEGER, sku_id INTEGER, warehouse_id TEXT, enable_count NUMERIC, disable_flag INTEGER, synced_at DATETIME)'))
    for product, sku, amount in [(1, 11, 20), (2, 22, 6)]:
        db.execute(text('INSERT INTO lsordertest.okki_product_skus VALUES (:p,:s)'), {'p':product,'s':sku})
        db.execute(text('INSERT INTO lsordertest.okki_inventory VALUES (:p,:s,:w,:q,0,:at)'),
                   {'p':product,'s':sku,'w':WAREHOUSE,'q':amount,'at':beijing_now()-timedelta(hours=1)})
    raw = {(1,11):20, (2,22):6}
    def observe(target, item_ids=None):
        assert target.warehouse_id == WAREHOUSE
        return {'source':'okki_live', 'items':[
            {'product_id':p,'sku_id':s,'available_stock':raw.get((int(p),int(s)))}
            for _,p,s in target.lines]}
    monkeypatch.setattr(shipment_inventory_service, 'observe', observe)
    return db, raw


def reserve(db, quantities, *, status='waiting_stock', invoice_status='synced'):
    number = db.query(Invoice).count()+1
    invoice = Invoice(invoice_no=f'RESERVE-{number}', order_type='stock', customer_id='1',
        customer_name='Test', invoice_date=date(2026,10,21), sales_user_id=1,
        xiaoman_order_id=str(100+number), sync_status='synced', status=invoice_status, outbound_auto_requested=1)
    invoice.items = [InvoiceItem(sort_order=i,item_type='stock',product_id=p,sku_id=s,
        product_name='Test',product_display='Test',color='1',length='18',quantity=q,price_per_piece=1,total_price=q)
        for i,(p,s,q) in enumerate(quantities)]
    db.add(invoice);db.flush()
    payload = {'product_list':[{'product_id':p,'sku_id':s,'count':q} for p,s,q in quantities]}
    db.add(InvoiceSyncLog(invoice_id=invoice.id, action='create', success=1,
        created_at=beijing_now()-timedelta(seconds=1),
        request_digest=json.dumps(payload), response_body=json.dumps({'order_id':invoice.xiaoman_order_id})))
    task=OkkiOutboundTask(invoice_id=invoice.id,order_id=invoice.xiaoman_order_id,status=status,
        processed_at=beijing_now() if status=='done' else None)
    db.add(task);db.flush()
    return invoice,task


def test_free_stock_deducts_all_lines_not_just_shortage_and_aggregates_orders(stock):
    db,_=stock
    reserve(db, [(1,11,8),(2,22,10)])
    reserve(db, [(1,11,7)])
    assert product_service.load_available_stocks(db,{1,2}) == {(1,11):5,(2,22):0}


def test_overview_free_stock_aggregates_skus_and_enabled_warehouses(stock):
    from app.stock.free_inventory_service import get_free_inventory
    db, raw = stock
    reserve(db, [(1,11,8), (1,11,7)])
    db.execute(text('INSERT INTO lsordertest.okki_product_skus VALUES (1,12)'))
    db.execute(text('INSERT INTO lsordertest.okki_inventory VALUES (1,12,:w,9,0,:at)'),
               {'w':WAREHOUSE, 'at':beijing_now()})
    db.execute(text('INSERT INTO lsordertest.okki_inventory VALUES (1,11,"other",30,0,:at)'),
               {'at':beijing_now()})
    db.execute(text('INSERT INTO lsordertest.okki_inventory VALUES (1,11,"disabled",100,1,:at)'),
               {'at':beijing_now()})
    # Default warehouse 20 - 15, second SKU 9, other warehouse 30.
    assert get_free_inventory(db, {1,2})[0] == {1:44, 2:6}


def test_overview_free_stock_does_not_deduct_native_stock_twice(stock):
    from app.stock.free_inventory_service import get_free_inventory
    db, raw = stock
    reserve(db, [(1,11,8)], status='done')
    db.execute(text('UPDATE lsordertest.okki_inventory SET enable_count=12, synced_at=:at WHERE product_id=1'),
               {'at':beijing_now()+timedelta(seconds=1)})
    assert get_free_inventory(db, {1})[0] == {1:12}


def test_overview_free_stock_distinguishes_zero_from_unknown(stock, monkeypatch):
    from app.stock.free_inventory_service import get_free_inventory
    db, _ = stock
    reserve(db, [(1,11,25)])
    assert get_free_inventory(db, {1,999})[0] == {1:0, 999:None}
    db.execute(text('UPDATE lsordertest.okki_inventory SET enable_count=NULL WHERE product_id=1'))
    assert get_free_inventory(db, {1,2})[0] == {1:None, 2:6}


def test_overview_free_stock_requires_every_sku_even_if_other_warehouse_has_stock(stock):
    from app.stock.free_inventory_service import get_free_inventory
    db, _ = stock
    db.execute(text('INSERT INTO lsordertest.okki_product_skus VALUES (1,12)'))
    db.execute(text('INSERT INTO lsordertest.okki_inventory VALUES (1,12,"other",50,0,:at)'),
               {'at':beijing_now()})
    assert get_free_inventory(db, {1})[0] == {1:None}


def test_overview_empty_page_does_not_read_inventory():
    from app.stock.free_inventory_service import get_free_inventory
    assert get_free_inventory(None, set()) == ({}, {})


def test_overview_native_handoff_waits_for_newer_mirror(stock):
    from app.stock.free_inventory_service import get_free_inventory
    db, _ = stock
    reserve(db, [(1,11,8)], status='done')
    assert get_free_inventory(db, {1})[0] == {1:None}


@pytest.mark.parametrize('status', ['running', 'uncertain'])
def test_overview_inflight_send_cannot_be_deducted_again(stock, status):
    from app.stock.free_inventory_service import get_free_inventory
    db, _ = stock
    reserve(db, [(1,11,8)], status=status)
    db.execute(text('UPDATE lsordertest.okki_inventory SET enable_count=12, synced_at=:at WHERE product_id=1'),
               {'at':beijing_now()+timedelta(seconds=1)})
    assert get_free_inventory(db, {1})[0] == {1:None}


def test_overview_never_calls_provider_and_returns_oldest_sync_time(stock, monkeypatch):
    from app.stock.free_inventory_service import get_free_inventory
    db, _ = stock
    reserve(db, [(1,11,8)])
    monkeypatch.setattr(shipment_inventory_service, 'observe',
                        lambda *args: pytest.fail('Overview must not make provider calls'))
    values, times = get_free_inventory(db, {1,2})
    assert values == {1:12, 2:6}
    expected = db.execute(text('SELECT MIN(synced_at) FROM lsordertest.okki_inventory WHERE product_id=1')).scalar()
    assert times[1] == str(expected).replace(' ', 'T')


def test_repeated_skus_reserve_total_and_other_warehouses_are_not_sellable(stock):
    db,_=stock
    reserve(db, [(1,11,3),(1,11,4)])
    db.execute(text('INSERT INTO lsordertest.okki_inventory VALUES (1,11,"other",100,0,:at)'), {'at':beijing_now()})
    assert product_service.load_available_stocks(db,{1}) == {(1,11):13}


def test_unsynced_edit_keeps_last_successful_reservation(stock):
    db,_=stock
    invoice,_=reserve(db,[(1,11,8)])
    invoice.items[0].quantity=1
    invoice.sync_status='not_synced'
    db.flush()
    assert product_service.load_available_stocks(db,{1}) == {(1,11):12}


def test_cancelled_unsent_orders_release_but_uncertain_sends_remain_protected(stock):
    db,_=stock
    reserve(db,[(1,11,8)],invoice_status='cancelled')
    reserve(db,[(1,11,7)],status='uncertain')
    assert product_service.load_available_stocks(db,{1}) == {(1,11):13}


def test_native_created_stock_uses_live_quantity_without_double_deduction_or_stale_mirror(stock):
    db,raw=stock
    reserve(db,[(1,11,8)],status='done')
    raw[(1,11)]=12  # Native availability already reflects this outbound.
    assert product_service.load_available_stocks(db,{1}) == {(1,11):12}


def test_live_failure_does_not_fall_back_to_stale_sellable_inventory(stock,monkeypatch):
    db,_=stock
    reserve(db,[(1,11,8)])
    monkeypatch.setattr(shipment_inventory_service,'observe',lambda target:{'items':[]})
    assert product_service.load_available_stocks(db,{1}) == {}


def test_own_retained_demand_is_not_mistaken_for_real_inventory(stock):
    from app.invoice.stock_reservations import read_inventory
    db,raw=stock
    invoice,_=reserve(db,[(1,11,10)])
    raw[(1,11)]=6
    free,capacity=read_inventory(db,{1},invoice_id=invoice.id)
    assert free[(1,11)]==0 and capacity[(1,11)]==6
    raw[(1,11)]=10
    free,capacity=read_inventory(db,{1},invoice_id=invoice.id)
    assert free[(1,11)]==0 and capacity[(1,11)]==10


def test_later_outbound_cannot_take_previous_order_stock(stock,monkeypatch):
    from app.invoice import outbound_followup_service as followup
    db,_=stock
    first,_=reserve(db,[(1,11,8)])
    second,_=reserve(db,[(1,11,7)])
    monkeypatch.setattr(followup.remote,'read',lambda *a,**kw:{'count':1,'list':[
        {'sku_id':11,'product_id':1,'warehouse_id':WAREHOUSE,'enable_count':10,'disable_flag':0}]})
    monkeypatch.setattr(followup,'_stock_reader',lambda session: lambda sku:followup.remote.read(session,'inventory',{}))
    def order(invoice,count):
        return {'order_id':invoice.xiaoman_order_id,'product_list':[{'product_id':1,'sku_id':11,'count':count}]}
    assert followup._stock_shortages(db,order(first,8))==[]
    assert followup._stock_shortages(db,order(second,7))==[{'sku_id':'11','required':7.,'available':2.}]


def test_cancel_pending_keeps_reservation_and_successful_snapshot_survives_edit(stock):
    from app.invoice.stock_reservations import remember
    db,_=stock
    invoice,_=reserve(db,[(1,11,8)])
    remember(db,invoice)
    invoice.items[0].quantity=1
    invoice.sync_status='not_synced';invoice.status='cancel_pending';db.flush()
    assert product_service.load_available_stocks(db,{1})=={(1,11):12}


def test_bad_success_snapshot_never_silently_releases_stock(stock):
    db,_=stock
    invoice,_=reserve(db,[(1,11,8)])
    log=db.query(InvoiceSyncLog).filter_by(invoice_id=invoice.id).one()
    log.request_digest='{broken';db.flush()
    assert product_service.load_available_stocks(db,{1})=={}


def test_existing_partial_native_outbound_preserves_remainder_and_ignores_old_mirror(stock):
    from app.invoice.stock_reservations import remember_native
    db,raw=stock
    invoice,task=reserve(db,[(1,11,10)],status='skipped')
    task.reason='Existing outbound requires manual handling'
    remember_native(db,invoice.id,task.order_id,[{'invoice_warehouse_info':{'id':WAREHOUSE},'record_list':[
        {'order_id':task.order_id,'product_id':1,'sku_id':11,'outbound_count':4}]}])
    raw[(1,11)]=16
    assert product_service.load_available_stocks(db,{1})=={(1,11):10}  # 16 native free - 6 still reserved.


def test_legacy_existing_without_native_proof_is_unknown_never_old_mirror(stock):
    db,_=stock
    _,task=reserve(db,[(1,11,8)],status='skipped');task.reason='existing:old';db.flush()
    assert product_service.load_available_stocks(db,{1})=={}


def test_inventory_reader_requests_product_scope_without_touching_shared_invoice_token(monkeypatch):
    from app.invoice import outbound_followup_service as followup, okki_client
    calls=[]
    monkeypatch.setattr(okki_client,'fetch_token',lambda **kw:calls.append(kw) or ('private-product-token',None))
    monkeypatch.setattr(okki_client,'ensure_access_token',lambda *a,**kw:pytest.fail('must not modify shared invoice credentials'))
    monkeypatch.setattr(okki_client,'_get_json',lambda path,token,**kw:calls.append((path,token,kw)) or {'list':[],'count':0})
    reader=followup._stock_reader(None)
    reader('11');reader('22')
    assert calls[0]=={'scope':'invoices company product'}
    assert len(calls)==3 and calls[1][1]=='private-product-token'


@pytest.mark.parametrize('status',['done','skipped'])
def test_native_handoff_retains_new_successful_order_demand_until_native_reverified(stock,status):
    from app.invoice.stock_reservations import remember_native, protected
    db,raw=stock
    invoice,task=reserve(db,[(1,11,10)],status=status)
    if status=='skipped':task.reason='existing:77'
    detail={'invoice_warehouse_info':{'id':WAREHOUSE},'record_list':[
        {'order_id':task.order_id,'product_id':1,'sku_id':11,'outbound_count':10}]}
    remember_native(db,invoice.id,task.order_id,[detail])
    db.add(InvoiceSyncLog(invoice_id=invoice.id,action='update',success=1,
        request_digest=json.dumps({'product_list':[{'product_id':1,'sku_id':11,'count':15}]}),
        response_body=json.dumps({'order_id':task.order_id})))
    db.flush();raw[(1,11)]=20
    assert product_service.load_available_stocks(db,{1})=={(1,11):15}
    assert protected(db)=={(1,11):5}
    detail['record_list'][0]['outbound_count']=15
    remember_native(db,invoice.id,task.order_id,[detail]);raw[(1,11)]=15
    assert product_service.load_available_stocks(db,{1})=={(1,11):15}


def test_unverified_native_change_never_reuses_an_old_occupation_snapshot(stock):
    from app.invoice.stock_reservations import remember_native, protected
    from app.shipping_inspection.models import ShippingOperationEvent
    db,_=stock
    invoice,task=reserve(db,[(1,11,10)],status='done')
    remember_native(db,invoice.id,task.order_id,[{'invoice_warehouse_info':{'id':WAREHOUSE},'record_list':[
        {'order_id':task.order_id,'product_id':1,'sku_id':11,'outbound_count':10}]}])
    db.add(ShippingOperationEvent(scope='outbound-invoice-sync',request_id='unverified',
        source='pc',action='sync_uncertain',outbound_record_id='OB1',operator_user_id=0,login_user_id=0,
        operator_name='Test',login_name='Test',payload={'invoice_id':invoice.id},result={}))
    db.flush()
    assert product_service.load_available_stocks(db,{1})=={}
    assert protected(db)=={(1,11):10}


def test_historical_completed_generation_is_captured_before_edit_and_new_unproved_generation_is_unknown(stock):
    from app.invoice.stock_reservations import remember, protected
    db,raw=stock
    invoice,task=reserve(db,[(1,11,10)],status='done')
    remember(db,invoice)
    invoice.items[0].quantity=15;invoice.sync_status='not_synced';db.flush()
    assert protected(db)=={}
    db.add(InvoiceSyncLog(invoice_id=invoice.id,action='update',success=1,
        request_digest=json.dumps({'product_list':[{'product_id':1,'sku_id':11,'count':15}]}),
        response_body=json.dumps({'order_id':task.order_id})))
    invoice.sync_status='synced';db.flush();remember(db,invoice)
    raw[(1,11)]=20
    assert product_service.load_available_stocks(db,{1})=={(1,11):15}


def test_historical_done_with_newer_success_and_no_native_baseline_is_unknown(stock):
    db,_=stock
    invoice,task=reserve(db,[(1,11,10)],status='done')
    db.add(InvoiceSyncLog(invoice_id=invoice.id,action='update',success=1,
        created_at=task.processed_at+timedelta(seconds=1),
        request_digest=json.dumps({'product_list':[{'product_id':1,'sku_id':11,'count':15}]}),
        response_body=json.dumps({'order_id':task.order_id})))
    db.flush()
    assert product_service.load_available_stocks(db,{1})=={}


def test_shortage_execution_uses_live_historical_credit(stock,monkeypatch):
    from app.invoice import outbound_followup_service as followup, native_stock_observation
    db,_=stock
    old,task=reserve(db,[(1,11,100)],status='done')
    db.add(InvoiceSyncLog(invoice_id=old.id,action='update',success=1,
        created_at=task.processed_at+timedelta(seconds=1),
        request_digest=json.dumps({'product_list':[{'product_id':1,'sku_id':11,'count':100}]}),
        response_body=json.dumps({'order_id':task.order_id})))
    current,_=reserve(db,[(1,11,50)])
    sequence=[]
    def inventory(sku):
        sequence.append('inventory');return {'count':1,'list':[
            {'sku_id':11,'product_id':1,'warehouse_id':WAREHOUSE,'enable_count':85,'disable_flag':0}]}
    def native(*args):
        sequence.append('native');return {(1,11):100}
    monkeypatch.setattr(followup,'_stock_reader',lambda db:inventory)
    monkeypatch.setattr(native_stock_observation,'reader',lambda db:native)
    order={'order_id':current.xiaoman_order_id,'product_list':[{'product_id':1,'sku_id':11,'count':50}]}
    assert followup._stock_shortages(db,order)==[]
    assert sequence==['native','inventory']
    monkeypatch.setattr(native_stock_observation,'reader',lambda db:lambda *args:{(1,11):20})
    assert followup._stock_shortages(db,order)==[{'sku_id':'11','required':50.,'available':5.}]


def test_additional_outbound_credits_historical_native_before_live_inventory(stock,monkeypatch):
    from app.invoice import native_stock_observation
    from app.invoice.stock_reservations import require_additional
    db,raw=stock
    old,task=reserve(db,[(1,11,100)],status='done')
    db.add(InvoiceSyncLog(invoice_id=old.id,action='update',success=1,
        created_at=task.processed_at+timedelta(seconds=1),
        request_digest=json.dumps({'product_list':[{'product_id':1,'sku_id':11,'count':100}]}),
        response_body=json.dumps({'order_id':task.order_id})))
    db.flush();raw[(1,11)]=0
    def native(*args):
        raw[(1,11)]=50;return {(1,11):100}
    monkeypatch.setattr(native_stock_observation,'reader',lambda db:native)
    payload={'invoice_warehouse_id':WAREHOUSE,'record_list':[
        {'order_id':102,'order_record_id':99,'product_id':1,'sku_id':11,'outbound_count':50}]}
    require_additional(db,payload)
    monkeypatch.setattr(native_stock_observation,'reader',lambda db:lambda *args:{(1,11):0})
    with pytest.raises(ValueError,match='自由可用'):require_additional(db,payload)


def test_outbound_increases_can_use_only_unclaimed_stock_and_unchanged_rows_keep_their_native_hold(stock):
    from app.invoice.stock_reservations import require_additional
    db,_=stock
    reserve(db,[(1,11,18)])
    before={'invoice_warehouse_info':{'id':WAREHOUSE},'record_list':[
        {'order_id':999,'order_record_id':9,'product_id':1,'sku_id':11,'outbound_count':10}]}
    payload={'record_list':[dict(before['record_list'][0],outbound_count=12)]}
    require_additional(db,payload,before=before)  # 20 native - 18 protected leaves exactly 2.
    payload['record_list'][0]['outbound_count']=13
    with pytest.raises(ValueError,match='自由可用'):require_additional(db,payload,before=before)
    payload['record_list'][0]['outbound_count']=10
    require_additional(db,payload,before=before)  # Existing native occupation never gets deducted again.
    assert db.query(OkkiOutboundTask).count()==1  # Read guard must not roll back caller's transaction.
