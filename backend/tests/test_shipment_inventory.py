"""Live stock parsing and SKU aggregation; no network or production data."""
from copy import deepcopy
from types import SimpleNamespace as NS
from datetime import datetime, timezone
import pytest
from app.invoice import shipment_inventory_service as stocks


def invoice():
    return NS(id=1, items=[NS(id=7,product_id=11,sku_id=22,presale_archived=0),
        NS(id=8,product_id=11,sku_id=22,presale_archived=0)])


@pytest.fixture
def source(monkeypatch):
    calls=[]
    monkeypatch.setattr(stocks,'get_settings',lambda:NS(OKKI_PRESALE_WAREHOUSE_ID=17))
    def token(**kwargs):calls.append(kwargs);return 'private-token',None
    monkeypatch.setattr(stocks.okki_client,'fetch_token',token)
    data={'count':2,'list':[dict(product_id=11,sku_id=22,warehouse_id=17,enable_count='6.9',disable_flag=0),
        dict(product_id=11,sku_id=22,warehouse_id=18,enable_count='9999',disable_flag=0)]}
    def read(path,token,**kwargs):calls.append(kwargs);return deepcopy(data)
    monkeypatch.setattr(stocks.okki_client,'_get_json',read)
    return data,calls


def test_exact_warehouse_fresh_scope_one_read_per_duplicate_sku(source):
    data,calls=source;inv=invoice();target=stocks.capture(inv);result=stocks.observe(target)
    assert [row['available_stock'] for row in result['items']]==['6.9','6.9']
    assert len(calls)==2 and calls[0]=={'scope':'invoices company product'}
    stocks.require_stock(inv,NS(items=[NS(invoice_item_id=7,quantity=3),NS(invoice_item_id=8,quantity=3)]),target,result)
    with pytest.raises(ValueError,match='合计超过'):
        stocks.require_stock(inv,NS(items=[NS(invoice_item_id=7,quantity=4),NS(invoice_item_id=8,quantity=3)]),target,result)


@pytest.mark.parametrize('field,value', [('enable_count',None),('enable_count',''),('enable_count','NaN'),
    ('enable_count','Infinity'),('enable_count','-1'),('enable_count','9007199254740992'),
    ('disable_flag',None),('disable_flag',True),('disable_flag',2),('product_id',12),('sku_id',23)])
def test_invalid_stock_never_becomes_zero_or_available(source,field,value):
    data,_=source;data['list'][0][field]=value
    inv=invoice();target=stocks.capture(inv);snapshot=stocks.observe(target)
    assert all(row['available_stock'] is None for row in snapshot['items'])
    with pytest.raises(ValueError,match='待核对'):
        stocks.require_stock(inv,NS(items=[NS(invoice_item_id=7,quantity=1)]),target,snapshot)


@pytest.mark.parametrize('fault',['partial','missing','duplicate','zero','disabled'])
def test_complete_unique_target_required_and_true_zero_recognized(source,fault):
    data,_=source
    if fault=='partial':data['count']=3
    if fault=='missing':data['list'].pop(0);data['count']=1
    if fault=='duplicate':data['list'].append(dict(data['list'][0]));data['count']=3
    if fault=='zero':data['list'][0]['enable_count']='0'
    if fault=='disabled':data['list'][0]['disable_flag']=1
    result=stocks.observe(stocks.capture(invoice()))
    assert result['items'][0]['available_stock']==('0' if fault in {'zero','disabled'} else None)


def test_provider_denial_stops_after_one_call_no_mirror_fallback(source,monkeypatch):
    _,calls=source;inv=invoice();inv.items[1].sku_id=23
    def denied(*args,**kwargs):calls.append('denied');raise stocks.okki_client.OkkiApiError('no permission invoices scopes')
    monkeypatch.setattr(stocks.okki_client,'_get_json',denied)
    snapshot=stocks.observe(stocks.capture(inv))
    assert calls.count('denied')==1 and all(row['available_stock'] is None for row in snapshot['items'])


def test_final_warehouse_and_mapping_fenced(source,monkeypatch):
    inv=invoice();target=stocks.capture(inv);snapshot=stocks.observe(target);body=NS(items=[NS(invoice_item_id=7,quantity=1)])
    inv.items[0].sku_id=23
    with pytest.raises(ValueError,match='已变化'):stocks.require_stock(inv,body,target,snapshot)
    inv.items[0].sku_id=22;monkeypatch.setattr(stocks,'get_settings',lambda:NS(OKKI_PRESALE_WAREHOUSE_ID=18))
    with pytest.raises(ValueError,match='已变化'):stocks.require_stock(inv,body,target,snapshot)


def test_unmapped_and_unconfigured_do_not_call_provider(source,monkeypatch):
    _,calls=source;inv=invoice()
    for row in inv.items:row.sku_id=None
    assert stocks.observe(stocks.capture(inv))['items'][0]['available_stock'] is None
    monkeypatch.setattr(stocks,'get_settings',lambda:NS(OKKI_PRESALE_WAREHOUSE_ID=None))
    assert stocks.observe(stocks.capture(invoice()))['items'][0]['available_stock'] is None
    assert calls==[]


@pytest.mark.parametrize('utc_hour,utc_minute,expected',[(15,59,'2026-10-15T23:59:01'),(16,0,'2026-10-16T00:00:01')])
def test_query_time_is_beijing_across_utc_day_boundary(source,monkeypatch,utc_hour,utc_minute,expected):
    from app.core import time
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            return datetime(2026,10,15,utc_hour,utc_minute,1,tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(time,'datetime',Clock)
    assert stocks.observe(stocks.capture(invoice()))['queried_at']==expected


def test_bulk_reads_share_connection_pool_with_bounded_parallelism(source,monkeypatch):
    import threading
    _,calls=source;inv=invoice()
    inv.items=[NS(id=i,product_id=11,sku_id=100+i,presale_archived=0) for i in range(33)]
    active=0;peak=0;clients=[];lock=threading.Lock();wave=threading.Barrier(4,timeout=5)
    def read(path,token,**options):
        nonlocal active,peak
        with lock:active+=1;peak=max(peak,active);clients.append(options.get('client'))
        try:
            if options['params']['sku_id']!='100':wave.wait()
            return {'count':1,'list':[dict(product_id=11,sku_id=options['params']['sku_id'],warehouse_id=17,enable_count='9',disable_flag=0)]}
        finally:
            with lock:active-=1
    monkeypatch.setattr(stocks.okki_client,'_get_json',read)
    result=stocks.observe(stocks.capture(inv))
    assert all(row['available_stock']=='9' for row in result['items'])
    assert peak==4 and len(clients)==33 and clients[0] is not None and all(client is clients[0] for client in clients)
    assert clients[0].is_closed


def test_systemic_wave_error_stops_later_skus_and_closes_pool(source,monkeypatch):
    import threading
    _,calls=source;inv=invoice();inv.items=[NS(id=i,product_id=11,sku_id=100+i,presale_archived=0) for i in range(12)]
    seen=[];clients=[];lock=threading.Lock();wave=threading.Barrier(4,timeout=5)
    def read(path,token,**options):
        sku=options['params']['sku_id']
        with lock:seen.append(sku);clients.append(options['client'])
        if sku!='100':wave.wait()  # All four reads are in flight before the injected error.
        if sku=='102':raise stocks.okki_client.OkkiApiError('unavailable')
        return {'count':1,'list':[dict(product_id=11,sku_id=sku,warehouse_id=17,enable_count='9',disable_flag=0)]}
    monkeypatch.setattr(stocks.okki_client,'_get_json',read)
    result=stocks.observe(stocks.capture(inv))
    assert set(seen)=={'100','101','102','103','104'} and clients[0].is_closed
    assert result['items'][0]['available_stock']=='9'
    assert all(row['available_stock'] is None for row in result['items'][1:])


def test_reused_client_still_uses_standard_http_response_validation(monkeypatch):
    import httpx
    received=[]
    def handler(request):
        received.append(request)
        assert request.headers['authorization']=='Bearer synthetic-token'
        assert request.url.params['sku_id']=='22'
        return httpx.Response(200,json={'code':200,'data':{'count':0,'list':[]}})
    monkeypatch.setattr(stocks.okki_client,'get_settings',lambda:NS(OKKI_API_BASE='https://inventory.example.test'))
    monkeypatch.setattr(httpx,'get',lambda *_a,**_k:pytest.fail('Pooled call opened a new top-level connection'))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert stocks.okki_client._get_json('/v1/product/inventory-list','synthetic-token',
            context='test',params={'sku_id':'22'},client=client)=={'count':0,'list':[]}
    assert len(received)==1


def test_bad_first_sku_does_not_hide_later_valid_stock(source,monkeypatch):
    inv=invoice();inv.items[1].sku_id=23
    def read(path,token,**options):
        sku=options['params']['sku_id']
        return {'count':0,'list':[]} if sku=='22' else {'count':1,'list':[
            dict(product_id=11,sku_id=sku,warehouse_id=17,enable_count='8',disable_flag=0)]}
    monkeypatch.setattr(stocks.okki_client,'_get_json',read)
    result=stocks.observe(stocks.capture(inv))
    assert [row['available_stock'] for row in result['items']]==[None,'8']
