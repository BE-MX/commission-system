from copy import deepcopy
from types import SimpleNamespace
import pytest
from app.invoice import native_stock_observation as native


@pytest.fixture
def observed(monkeypatch):
    detail={'outbound_invoice_id':'77','status':1,'create_time':'2026-09-28 08:00:00',
        'invoice_warehouse_info':{'id':'8193514242746'},'record_list':[
            {'outbound_record_id':78,'order_id':'101','product_id':1,'sku_id':11,'outbound_count':4}]}
    state={'ids':['77'],'active':True,'detail':detail,'calls':[]}
    class DB:
        def execute(self,query,args):
            assert str(query).startswith('SELECT DISTINCT') and args=={'order_id':'101'}
            return SimpleNamespace(scalars=lambda:SimpleNamespace(all=lambda:state['ids']))
    monkeypatch.setattr(native,'get_settings',lambda:SimpleNamespace(BUSINESS_DB_NAME='lsordertest'))
    monkeypatch.setattr(native.okki_client,'fetch_token',lambda:('test',None))
    monkeypatch.setattr(native,'is_active',lambda *a:state['active'])
    def fetch(path,token,**kwargs):
        state['calls'].append(kwargs['params']);result=deepcopy(state['detail'])
        result['outbound_invoice_id']=kwargs['params']['outbound_invoice_id'];return result
    monkeypatch.setattr(native.okki_client,'_get_json',fetch)
    return state,native.reader(DB())


def test_multiple_verified_documents_sum_but_absent_and_deleted_keep_demand(observed):
    state,read=observed
    assert read(1,'101')=={(1,11):4}
    state['ids']=['77','88'];assert read(1,'101')=={(1,11):8}
    state['active']=False;assert read(1,'101')=={}
    state['ids']=[];assert read(1,'101')=={}


@pytest.mark.parametrize('invalid',['warehouse','order','quantity','duplicate','missing_rows','auth'])
def test_untrusted_native_evidence_never_releases_stock(observed,monkeypatch,invalid):
    state,read=observed;detail=state['detail'];row=detail['record_list'][0]
    if invalid=='warehouse':detail['invoice_warehouse_info']['id']='other'
    elif invalid=='order':row['order_id']='102'
    elif invalid=='quantity':row['outbound_count']=-1
    elif invalid=='duplicate':detail['record_list'].append(deepcopy(row))
    elif invalid=='missing_rows':detail['record_list']=[]
    elif invalid=='auth':monkeypatch.setattr(native.okki_client,'_get_json',lambda *a,**kw:None)
    with pytest.raises(ValueError):read(1,'101')


def test_presence_failure_is_not_treated_as_zero(observed,monkeypatch):
    _,read=observed
    def fail(*args):raise ValueError('provider unavailable')
    monkeypatch.setattr(native,'is_active',fail)
    with pytest.raises(ValueError):read(1,'101')
