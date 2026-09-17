"""Inspection filters use isolated mirror rows without widening permissions."""
from datetime import datetime
import pytest
from sqlalchemy import text
from app.shipping_inspection import outbound_service
from tests.test_shipping_inspection import _pc_client, _user, storage, product_display_source, outbound_scope_seed
from tests.test_shipping_inspection_scope import scoped_inspections, READ, ALL


@pytest.fixture(params=[False, True], ids=['record-link', 'invoice-bridge'])
def records_with_sales(db, scoped_inspections, request):
    sales, records, photos = scoped_inspections
    one, two = _user(db, '张三'), _user(db, '李四')
    records[0].submitted_by, records[1].submitted_by = one.id, two.id
    records[0].submitted_at = datetime(2026, 9, 16, 23, 59, 59)
    records[1].submitted_at = datetime(2026, 9, 17, 0, 0, 0)
    db.execute(text('ALTER TABLE lsordertest.okki_outbound_record_items ADD COLUMN order_id TEXT'))
    for oid, uid, company, name in [('OA','UA','C001','Eva'),('OB','UB','C002','Tessie'),('OTHER','UX','C001','Rainy')]:
        db.execute(text('INSERT INTO lsordertest.okki_orders (order_id,user_id,company_id) VALUES (:oid,:uid,:company)'), {'oid':oid,'uid':uid,'company':company})
        db.execute(text('INSERT INTO lsordertest.user_basic (user_id,full_name) VALUES (:uid,:name)'), {'uid':uid,'name':name})
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET order_id=CASE WHEN outbound_record_id='OB001' THEN 'OA' ELSE 'OB' END"))
    if request.param:
        db.execute(text('ALTER TABLE lsordertest.okki_outbound_records ADD COLUMN outbound_invoice_id TEXT'))
        db.execute(text('ALTER TABLE lsordertest.okki_outbound_record_items ADD COLUMN outbound_invoice_id TEXT'))
        db.execute(text("UPDATE lsordertest.okki_outbound_records SET outbound_invoice_id='invoice-' || id"))
        db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET outbound_invoice_id='invoice-' || outbound_record_id, outbound_record_id='unrelated-entity'"))
    db.commit()
    outbound_service._columns_cache.clear()
    yield sales, records
    outbound_service._columns_cache.clear()


def test_combined_filters_and_order_salespeople(db, records_with_sales):
    sales, records = records_with_sales
    with _pc_client(db, sales, [READ, ALL]) as client:
        path='/api/shipping-inspection/records'
        all_rows=client.get(path,params={'page_size':1}).json()['data']
        assert all_rows['total']==2 and len(all_rows['items'])==1
        assert all_rows['items'][0]['salesperson_name']=='Tessie'
        result=client.get(path,params={'keyword':'CK2026001','submitted_by_name':'张','salesperson_name':'Eva',
            'date_from':'2026-09-16','date_to':'2026-09-16'}).json()['data']
        assert result['total']==1
        assert result['items'][0]['salesperson_name']=='Eva'
        assert result['items'][0]['submitted_by_name']=='张三'
        for params in [{'salesperson_name':'Rainy'},{'salesperson_name':'%'},{'salesperson_name':"' OR 1=1 --"},
                       {'submitted_by_name':'李四','salesperson_name':'Eva'}]:
            assert client.get(path,params=params).json()['data']['total']==0
        assert client.get(path,params={'date_from':'2026-09-17','date_to':'2026-09-17'}).json()['data']['total']==1
        assert client.get(path,params={'date_from':'2026-09-18','date_to':'2026-09-17'}).status_code==422


def test_salesperson_filter_cannot_expand_read_scope(db, records_with_sales):
    sales, records=records_with_sales
    with _pc_client(db,sales,[READ]) as client:
        assert client.get('/api/shipping-inspection/records',params={'salesperson_name':'Tessie'}).json()['data']['total']==0
        assert client.get('/api/shipping-inspection/records',params={'salesperson_name':'Eva'}).json()['data']['total']==1
    with _pc_client(db,sales,[]) as client:
        assert client.get('/api/shipping-inspection/records',params={'submitted_by_name':'张三'}).status_code==403


def test_multiple_orders_are_deduplicated_and_chinese_binding_names_match(db, records_with_sales):
    from app.auth.models import ArkUserExternalBinding
    sales, records = records_with_sales
    eva = _user(db, '刘也')
    db.add(ArkUserExternalBinding(ark_user_id=eva.id, provider='okki', external_account_id='UA', binding_status='active'))
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET order_id='OB' WHERE id='IT002'"))
    extra = ',outbound_invoice_id' if 'outbound_invoice_id' in outbound_service._table_columns(db, outbound_service.ITEMS_TABLE) else ''
    db.execute(text(f"INSERT INTO lsordertest.okki_outbound_record_items (id,outbound_record_id,order_id{extra}) SELECT 'DUP',outbound_record_id,order_id{extra} FROM lsordertest.okki_outbound_record_items WHERE id='IT001'"))
    db.commit()
    with _pc_client(db, sales, [READ, ALL]) as client:
        result = client.get('/api/shipping-inspection/records', params={'salesperson_name':'刘也','page_size':1}).json()['data']
        assert result['total'] == 1 and len(result['items']) == 1
        assert result['items'][0]['salesperson_name'] == 'Eva（刘也）、Tessie'
        assert client.get('/api/shipping-inspection/records', params={'salesperson_name':'Tessie'}).json()['data']['total'] == 2
