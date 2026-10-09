"""Local-only detail loading and inspection completion regressions."""
from datetime import timedelta
from decimal import Decimal
import hashlib
import pytest
from sqlalchemy import text, event
from fastapi import HTTPException
from app.core.time import beijing_now
from app.invoice import detail_access, detail_outbounds, detail_receipts, detail_receipt_snapshot
from app.receipt import receipt_index, remote
from app.receipt.models import ReceiptIndexState
from app.shipping_inspection.models import ShippingInspection, ShippingOperationEvent
from tests.test_invoice_related_detail import ADMIN, SELF, order, receipt, doc, projection_order


def indexed(db, invoice, *, age=0, corrupt=False):
    stamp=(beijing_now()-timedelta(seconds=age)).strftime('%Y-%m-%d %H:%M:%S')
    payload={'version':1,'source':receipt_index._source(),'watermark':stamp,'rows':[
        {'cash_collection_id':'701','cash_collection_no':'REMOTE-701','order_id':invoice.xiaoman_order_id,
         'amount':'48','currency':'USD','collect_status':1,'collection_date':'2026-10-08','update_time':stamp}]}
    envelope={'payload':payload,'sha256':hashlib.sha256(receipt_index._encoded(payload)).hexdigest()}
    if corrupt: envelope['sha256']='invalid'
    db.add(ReceiptIndexState(source=payload['source'],snapshot=envelope,updated_at=beijing_now())); db.flush()


def test_inspection_submission_defines_outbound_not_okki_status():
    first,second=doc(status=1),doc('D2',status=2,first=4,second=8)
    first['inspection']={'state':'ready','status':'submitted'}
    second['inspection']={'state':'ready','status':'draft'}
    rows,quantities=detail_outbounds.project(projection_order(),[first,second])
    assert quantities=={'1':'6','2':'2'}
    assert rows[0]['state']=='shipped' and rows[1]['state']=='generated'


@pytest.mark.parametrize('age,corrupt',[(121,False),(-30,False),(0,True)])
def test_stale_future_or_invalid_snapshot_cannot_publish_totals(db,age,corrupt):
    invoice=order(db); receipt(db,invoice,xiaoman_receipt_id='701'); indexed(db,invoice,age=age,corrupt=corrupt)
    panel=detail_receipts.read(db,invoice,ADMIN,refresh=False)
    assert panel['state']=='unverified' and panel['summary'] is None and len(panel['items'])==1


def test_fresh_receipt_snapshot_loads_without_remote_and_keeps_gross_fee(db,monkeypatch):
    invoice=order(db); receipt(db,invoice,xiaoman_receipt_id='701'); indexed(db,invoice)
    def blocked(*a,**k): raise AssertionError('First paint must not call remote')
    monkeypatch.setattr(remote,'read',blocked); monkeypatch.setattr(remote,'order_snapshot',blocked)
    panel=detail_receipts.read(db,invoice,ADMIN,refresh=False)
    assert panel['state']=='ready' and panel['source']=='background_snapshot'
    assert Decimal(panel['summary']['effective_amount'])==50
    assert panel['checked_at'] and len(panel['items'])==1


def test_explicit_refresh_uses_live_order_verification(db,monkeypatch):
    invoice=order(db); calls=[]
    monkeypatch.setattr(remote,'order_snapshot',lambda *a:(calls.append(invoice.id) or {'rows':[]}))
    panel=detail_receipts.read(db,invoice,ADMIN,refresh=True)
    assert panel['state']=='ready' and calls==[invoice.id] and panel['source']=='live'


@pytest.fixture
def mirror(db):
    from app.shipping_inspection import outbound_service
    outbound_service._columns_cache.clear()
    assert db.get_bind().dialect.name=='sqlite'
    db.execute(text('DROP TABLE IF EXISTS lsordertest.okki_outbound_record_items'))
    db.execute(text('DROP TABLE IF EXISTS lsordertest.okki_outbound_records'))
    db.execute(text('CREATE TABLE lsordertest.okki_outbound_records (id INTEGER, outbound_invoice_id TEXT, serial_id TEXT, company_id TEXT, create_user_name TEXT, update_time TEXT)'))
    db.execute(text('CREATE TABLE lsordertest.okki_outbound_record_items (id INTEGER, outbound_invoice_id TEXT, order_id TEXT, order_record_id TEXT, product_id TEXT, sku_id TEXT, outbound_count INTEGER)'))
    db.execute(text("INSERT INTO lsordertest.okki_outbound_records VALUES (10,'D1','CK-1','101','Maker','2026-10-08 10:00:00')"))
    db.execute(text("INSERT INTO lsordertest.okki_outbound_record_items VALUES (20,'D1','2001','1','100','101',6),(21,'D1','9999','2','100','101',100)"))
    yield
    outbound_service._columns_cache.clear()


def invoice_with_items(db):
    from app.invoice.models import InvoiceItem
    invoice=order(db)
    db.add(InvoiceItem(invoice_id=invoice.id,product_id=100,sku_id=101,product_name='Line',product_display='Line',
        color='1',length='18',quantity=10,price_per_piece=10,total_price=100,xiaoman_unique_id='1'))
    db.flush()
    return detail_access.get_order(db,invoice.id,ADMIN)


@pytest.mark.parametrize('action,required,expected',[(None,[],6),('sync_sending',[],0),('sync_uncertain',[],0),('sync_done',['__all_items__'],0)])
def test_local_outbound_only_counts_current_submitted_inspections(db,mirror,monkeypatch,action,required,expected):
    invoice=invoice_with_items(db)
    db.add(ShippingInspection(outbound_record_id='10',status='submitted'))
    if action:
        db.add(ShippingOperationEvent(scope='outbound-invoice-sync',source='test',request_id='10',outbound_record_id='10',action=action,
            login_user_id=1,operator_user_id=1,operator_name='Test',login_name='Test',
            result={'required_recheck_ids':required,'print_before_recheck':{'verified_update_time':'2026-10-08 10:00:00'}}))
    db.flush()
    monkeypatch.setattr(remote,'read',lambda *a:pytest.fail('outbounds must never call remote'))
    panel=detail_outbounds.read(db,invoice,ADMIN)
    assert panel['state']=='ready' and panel['source']=='inspection'
    assert Decimal(panel['summary']['shipped_quantity'])==expected
    assert len(panel['items'])==1 and len(panel['items'][0]['items'])==1


def test_recalled_inspection_removes_shipped_quantity(db,mirror):
    invoice=invoice_with_items(db)
    db.add(ShippingInspection(outbound_record_id='10',status='draft',edit_version=1)); db.flush()
    assert detail_outbounds.read(db,invoice,ADMIN)['summary']['shipped_quantity']=='0'


def test_duplicate_mirror_and_deleted_receipt_are_not_counted(db,mirror):
    invoice=invoice_with_items(db)
    db.execute(text("INSERT INTO lsordertest.okki_outbound_records VALUES (11,'D1','DUP','101','Maker',NULL)"))
    assert detail_outbounds.read(db,invoice,ADMIN)['summary'] is None
    db.add(ShippingOperationEvent(scope='outbound-delete',source='test',request_id='D1',action='outbound_deleted',
        outbound_record_id='10',login_user_id=1,operator_user_id=1,operator_name='Test',login_name='Test')); db.flush()
    assert detail_outbounds.read(db,invoice,ADMIN)['summary']['shipped_quantity']=='0'


def sync_event(db, action='sync_done', result=None):
    row=ShippingOperationEvent(scope='outbound-invoice-sync',source='test',request_id='10',outbound_record_id='10',action=action,
        login_user_id=1,operator_user_id=1,operator_name='Test',login_name='Test',result=result or {})
    db.add(row); db.flush(); return row


def test_hidden_inspection_cannot_leak_through_progress_or_recheck_badge(db,mirror,monkeypatch):
    from app.shipping_inspection import router
    invoice=invoice_with_items(db)
    db.add(ShippingInspection(outbound_record_id='10',status='submitted'))
    sync_event(db,result={'required_recheck_ids':['__all_items__']})
    monkeypatch.setattr(router,'_inspection_scope',lambda *a:'not-visible-owner')
    panel=detail_outbounds.read(db,invoice,ADMIN)
    assert panel['state']=='unverified' and panel['summary'] is None
    assert panel['items'][0]['inspection']=={'state':'restricted','status':None}
    assert panel['items'][0]['anomaly'] is None


@pytest.mark.parametrize('time',['2026-10-08 10:00:00','2026-10-08 10:00:01'])
def test_stale_mirror_cannot_reuse_submitted_inspection(db,mirror,time):
    invoice=invoice_with_items(db)
    db.add(ShippingInspection(outbound_record_id='10',status='submitted'))
    sync_event(db,result={'verified':{'update_time':time,'serial_id':'CK-1','items':[]}})
    assert detail_outbounds.read(db,invoice,ADMIN)['summary'] is None


def test_presale_submission_does_not_require_or_change_local_shipped_state():
    from types import SimpleNamespace
    document=doc(status=1); document['inspection']['status']='submitted'
    frozen=SimpleNamespace(status='generated',payload={'record_list':document['record_list']})
    _,quantities=detail_outbounds.project(projection_order(),[document],presale_outbounds={'D1':frozen})
    assert quantities=={'1':'6','2':'2'} and frozen.status=='generated'


def test_receipt_scope_checked_before_loading_shared_snapshot(db,monkeypatch):
    invoice=order(db,owner=2)
    monkeypatch.setattr(detail_receipt_snapshot,'load',lambda *a:pytest.fail('Unauthorized snapshot read'))
    with pytest.raises(HTTPException): detail_receipts.read(db,invoice,SELF,refresh=False)


def test_new_remote_receipt_not_yet_in_index_is_not_double_counted(db):
    invoice=order(db); receipt(db,invoice,xiaoman_receipt_id='702'); indexed(db,invoice)
    panel=detail_receipts.read(db,invoice,ADMIN,refresh=False)
    assert panel['summary'] is None and len(panel['items'])==1


def test_unlinked_order_shows_local_zero_progress_without_shared_index(db):
    invoice=order(db); invoice.xiaoman_order_id=None
    panel=detail_receipts.read(db,invoice,ADMIN,refresh=False)
    assert panel['state']=='ready' and panel['source']=='local'
    assert Decimal(panel['summary']['effective_amount'])==0


def test_missing_snapshot_also_hides_presale_freight_totals(db):
    invoice=order(db,kind='presale')
    panel=detail_receipts.read(db,invoice,ADMIN,refresh=False)
    assert panel['summary'] is None and panel['freight']['state']=='unverified'
    assert panel['freight']['total_amount'] is None


def test_outbound_query_count_does_not_grow_per_document(db,mirror):
    invoice=invoice_with_items(db)
    detail_outbounds.read(db,invoice,ADMIN)  # Warm schema introspection only.
    queries=[]
    def record_query(*args): queries.append(args[2])
    event.listen(db.get_bind(),'before_cursor_execute',record_query)
    try:
        first=detail_outbounds.read(db,invoice,ADMIN)
        one_count=len(queries)
        assert first['state']=='ready'
        for identity in range(11,35):
            db.execute(text("INSERT INTO lsordertest.okki_outbound_records VALUES (:id,:doc,:doc,'101','Maker',NULL)"),{'id':identity,'doc':f'D{identity}'})
            db.execute(text("INSERT INTO lsordertest.okki_outbound_record_items VALUES (:id,:doc,'2001','1','100','101',0)"),{'id':identity+100,'doc':f'D{identity}'})
        queries.clear()
        panel=detail_outbounds.read(db,invoice,ADMIN)
        assert len(panel['items'])==25 and panel['state']=='ready'
        assert len(queries)==one_count
    finally:
        event.remove(db.get_bind(),'before_cursor_execute',record_query)
