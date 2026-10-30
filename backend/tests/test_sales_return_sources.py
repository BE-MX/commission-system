"""Read-source regression tests use only isolated SQLite fixtures."""
import json
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from app.auth.models import ArkUserExternalBinding
from app.sales_return import sources
from app.shipping_inspection import outbound_service
from app.shipping_inspection.models import ShippingInspection

USER = {'id': 7, 'roles': [], 'permissions': ['sales_return:read']}
ADMIN = {'sub': '8', 'roles': ['super_admin'], 'permissions': []}

@pytest.fixture
def source_db(db):
    outbound_service._columns_cache.clear()
    for table in ('okki_outbound_record_items', 'okki_outbound_records', 'okki_receipts'):
        db.execute(text(f'DROP TABLE lsordertest.{table}'))
    statements = [
        '''CREATE TABLE lsordertest.okki_outbound_records (id TEXT PRIMARY KEY, outbound_invoice_id TEXT,
            serial_id TEXT, warehouse_invoice_time TEXT, company_id TEXT, company_name TEXT,
            create_user_name TEXT, update_time TEXT, currency TEXT,
            product_total_amount NUMERIC, product_total_amount_usd NUMERIC, exchange_rate_usd NUMERIC)''',
        '''CREATE TABLE lsordertest.okki_outbound_record_items (id TEXT PRIMARY KEY,
            outbound_record_id TEXT, outbound_invoice_id TEXT, order_id TEXT, order_record_id TEXT,
            product_id TEXT, sku_id TEXT, outbound_count NUMERIC, sale_count NUMERIC,
            sale_price NUMERIC, product_amount NUMERIC, product_name TEXT, product_model TEXT)''',
        '''CREATE TABLE lsordertest.okki_order_items (id TEXT PRIMARY KEY, order_id TEXT, item_index INTEGER,
            product_id TEXT, sku_id TEXT, quantity NUMERIC, unit_price NUMERIC,
            amount NUMERIC, product_name TEXT, product_model TEXT)''',
        '''CREATE TABLE lsordertest.okki_receipts (cash_collection_id TEXT PRIMARY KEY, order_id TEXT,
            company_id TEXT, amount_usd NUMERIC, service_fee_amount_usd NUMERIC,
            collection_date TEXT, collect_status INTEGER, currency TEXT, amount NUMERIC,
            service_fee_amount NUMERIC, real_amount NUMERIC, real_amount_usd NUMERIC,
            bank_charge NUMERIC, bank_charge_usd NUMERIC)''',
        '''INSERT INTO lsordertest.okki_orders (order_id,order_no,company_id,user_id,amount_usd,status,status_name,account_date,
            trail,custom_fields,departments) VALUES ('101','PI-101','C1','70',100,'13972831656','已结束',
            '2025-12-01','外贸','{"22595163468":"是"}','[{"department_id": 1,"rate": 100}]')''',
        "INSERT INTO lsordertest.customer_info (company_id,company_name) VALUES ('C1','Test Company')",
        "INSERT INTO lsordertest.okki_outbound_records VALUES ('LOCAL-1','OUT-1','OUT-NO','2026-10-20','C1','Test Company','Maker','2026-10-20 12:00:00','USD',50,50,1)",
        "INSERT INTO lsordertest.okki_outbound_record_items VALUES ('LOCAL-LINE','REMOTE-LINE','OUT-1','101','REMOTE-ORDER-LINE','P1','S1',2,4,25,50,'Hair','Black')",
        "INSERT INTO lsordertest.okki_order_items VALUES ('UNRELATED-LOCAL-ID','101',0,'P1','S1',4,25,100,'Hair','Black')",
        "INSERT INTO lsordertest.okki_receipts VALUES ('PAY-1','101','C1',82,2,'2026-10-10',1,'USD',82,2,81,81,1,1)",
    ]
    for statement in statements:
        db.execute(text(statement))
    db.add(ArkUserExternalBinding(ark_user_id=7, provider='okki', external_account_id='70', binding_status='active', is_primary=True))
    db.add(ShippingInspection(outbound_record_id='LOCAL-1', status='submitted'))
    db.flush()
    yield db
    outbound_service._columns_cache.clear()


def test_historical_source_keeps_remote_ids_and_original_full_goods(source_db):
    result = sources.snapshot(source_db, '101', USER)
    assert result['invoice_id'] is None
    assert result['goods_amount'] == result['goods_amount_usd'] == '100.00'
    assert result['order_role'] == 'new_sign'
    assert result['gmv_eligible'] is True
    assert result['lines'][0] == {'source_key':'OUT-1:REMOTE-LINE','outbound_id':'OUT-1',
        'outbound_line_id':'REMOTE-LINE','order_line_id':'REMOTE-ORDER-LINE','product_id':'P1',
        'sku_id':'S1','product_name':'Hair','specification':'Black','quantity':2,
        'net_amount':'50.00','net_amount_usd':'50.00'}
    assert result['payments'][0]['principal'] == '79.00'
    assert result['payments'][0]['commission_basis_usd'] == '80.00'
    assert len(result['binding_hash']) == 64
    json.dumps(result)


def test_wrong_owner_cannot_read_order_or_picker(source_db):
    source_db.execute(text("UPDATE lsordertest.okki_orders SET user_id='OTHER'"))
    with pytest.raises(HTTPException) as error:
        sources.snapshot(source_db, '101', USER)
    assert error.value.status_code == 404
    assert sources.orders(source_db, USER)['items'] == []
    assert sources.snapshot(source_db, '101', ADMIN)['order_id'] == '101'


def test_generated_outbound_not_shipped(source_db):
    source_db.query(ShippingInspection).one().status = 'draft'
    source_db.flush()
    with pytest.raises(HTTPException) as error:
        sources.snapshot(source_db, '101', USER)
    assert error.value.status_code == 409
    assert '实际发货' in error.value.detail
    assert sources.orders(source_db, USER)['items'] == []


@pytest.mark.parametrize('statement,detail', [
    ("UPDATE lsordertest.okki_outbound_record_items SET order_record_id=NULL", '明细 ID'),
    ("UPDATE lsordertest.okki_outbound_record_items SET product_amount=NULL", '商品净额'),
    ("UPDATE lsordertest.okki_outbound_record_items SET outbound_count=5", '超过原订单数量'),
    ("UPDATE lsordertest.okki_outbound_record_items SET outbound_count=1.5", '整件'),
    ("UPDATE lsordertest.okki_outbound_records SET currency=NULL", '币种'),
    ("UPDATE lsordertest.okki_receipts SET collect_status=NULL", '生效状态'),
    ("UPDATE lsordertest.okki_receipts SET currency=NULL", '币种'),
    ("UPDATE lsordertest.okki_receipts SET service_fee_amount_usd=NULL", '手续费'),
    ("UPDATE lsordertest.okki_orders SET departments=NULL", '部门拆分'),
])
def test_unknown_evidence_fails_closed(source_db, statement, detail):
    source_db.execute(text(statement))
    with pytest.raises(HTTPException) as error:
        sources.snapshot(source_db, '101', USER)
    assert error.value.status_code == 409
    assert detail in error.value.detail


def test_non_usd_does_not_fall_back_to_one_to_one(source_db):
    source_db.execute(text("UPDATE lsordertest.okki_outbound_records SET currency='EUR',product_total_amount_usd=NULL"))
    with pytest.raises(HTTPException) as error:
        sources.snapshot(source_db, '101', USER)
    assert error.value.status_code == 409
    assert '美元' in error.value.detail


def test_source_hash_detects_value_change(source_db):
    before = sources.snapshot(source_db, '101', USER)['binding_hash']
    source_db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET product_amount=40"))
    assert sources.snapshot(source_db, '101', USER)['binding_hash'] != before


def test_picker_scope_and_literal_keyword(source_db):
    assert sources.customers(source_db, USER, keyword='test')['items'][0]['shipped_order_count'] == 1
    assert sources.orders(source_db, USER, customer_id='C1', keyword='PI-101')['total'] == 1
    assert sources.orders(source_db, USER, keyword='%')['total'] == 0


def test_non_usd_freezes_verified_original_conversion_and_both_fees(source_db):
    source_db.execute(text("UPDATE lsordertest.okki_outbound_records SET currency='EUR',product_total_amount=100,product_total_amount_usd=120"))
    source_db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET outbound_count=4,product_amount=100"))
    source_db.execute(text("UPDATE lsordertest.okki_receipts SET currency='EUR', amount=82,amount_usd=98.4,real_amount=81,real_amount_usd=97.2,bank_charge=1,bank_charge_usd=1.2,service_fee_amount_usd=2.4"))
    result = sources.snapshot(source_db, '101', USER)
    assert result['goods_amount'] == '100.00'
    assert result['goods_amount_usd'] == '120.00'
    assert result['lines'][0]['net_amount_usd'] == '120.00'
    assert result['payments'][0]['principal'] == '79.00'
    assert result['payments'][0]['principal_usd'] == '94.80'
    assert result['payments'][0]['commission_basis_usd'] == '96.00'


def test_linked_pi_requires_exact_original_line_not_same_sku(source_db):
    from datetime import date
    from app.invoice.models import Invoice, InvoiceItem
    invoice = Invoice(invoice_no='LOCAL-PI', invoice_date=date(2026, 10, 1), customer_id='C1',
        customer_name='Test Company', currency='USD', sales_user_id=7, xiaoman_order_id='101')
    invoice.items.append(InvoiceItem(product_name='Hair', product_display='Hair', color='Black',
        product_id='P1', sku_id='S1', quantity=4, total_price=100, xiaoman_unique_id='OTHER-REMOTE-ID'))
    source_db.add(invoice)
    source_db.flush()
    with pytest.raises(HTTPException) as error:
        sources.snapshot(source_db, '101', USER)
    assert error.value.status_code == 409
    assert '精确匹配' in error.value.detail


def test_duplicate_remote_outbound_line_is_never_counted_twice(source_db):
    source_db.execute(text("INSERT INTO lsordertest.okki_outbound_record_items SELECT 'SECOND-LOCAL-ID',outbound_record_id,outbound_invoice_id,order_id,order_record_id,product_id,sku_id,outbound_count,sale_count,sale_price,product_amount,product_name,product_model FROM lsordertest.okki_outbound_record_items"))
    with pytest.raises(HTTPException) as error:
        sources.snapshot(source_db, '101', USER)
    assert error.value.status_code == 409


def test_bank_fee_evidence_must_reconcile(source_db):
    source_db.execute(text("UPDATE lsordertest.okki_receipts SET real_amount=82"))
    with pytest.raises(HTTPException) as error:
        sources.snapshot(source_db, '101', USER)
    assert error.value.status_code == 409
    assert '银行手续费不一致' in error.value.detail


def test_historical_non_usd_partial_shipment_does_not_guess_goods_currency(source_db):
    source_db.execute(text("UPDATE lsordertest.okki_outbound_records SET currency='EUR',product_total_amount_usd=60"))
    with pytest.raises(HTTPException) as error:
        sources.snapshot(source_db, '101', USER)
    assert error.value.status_code == 409
    assert '完整实际出库' in error.value.detail


@pytest.mark.parametrize('departments',[None,[],[{'department_id':'D1','rate':100}],
    [{'department_id':1.5,'rate':100}],[{'department_id':1,'rate':50}]])
def test_invalid_original_department_allocation_cannot_be_frozen(source_db,departments):
    source_db.execute(text('UPDATE lsordertest.okki_orders SET departments=:value'),{'value':json.dumps(departments)})
    with pytest.raises(HTTPException) as error:
        sources.snapshot(source_db,'101',USER)
    assert error.value.status_code==409
    assert '部门' in error.value.detail


def test_source_freezes_original_identity_and_real_department_contract(source_db):
    from decimal import Decimal
    from app.dingtalk.gmv_daily_service import _parse_allocations
    result=sources.snapshot(source_db,'101',USER)
    assert result['account_date']=='2025-12-01' and result['raw_new_deal']=='是'
    parsed,issues,fatal=_parse_allocations(Decimal(result['goods_amount_usd']),result['departments'],result['order_no'])
    assert issues==fatal==[]
    assert parsed[0]['department_id']==1 and parsed[0]['amount']==Decimal('100')


def test_freight_receivable_is_never_a_goods_return_candidate(source_db):
    from datetime import date
    from app.invoice.models import Invoice
    from app.invoice.settlement_models import Receivable
    invoice=Invoice(invoice_no='FREIGHT-OWNER',invoice_date=date(2026,10,1),customer_id='C1',customer_name='Test Company')
    source_db.add(invoice)
    source_db.flush()
    source_db.add(Receivable(invoice_id=invoice.id,business_key='freight-source-test',kind='freight',amount=100,
        currency='USD',customer_id='C1',remote_order_id='101',remote_status='bound'))
    source_db.flush()
    assert sources.orders(source_db,USER)['total']==0
    with pytest.raises(HTTPException) as error:
        sources.snapshot(source_db,'101',USER)
    assert error.value.status_code==409 and '费用订单' in error.value.detail


def test_original_order_amount_including_fees_is_not_goods_gmv_basis(source_db):
    source_db.execute(text('UPDATE lsordertest.okki_orders SET amount_usd=150'))
    result=sources.snapshot(source_db,'101',USER)
    assert result['gmv_eligible'] is True and result['goods_amount_usd']=='100.00'
    assert result['lines'][0]['net_amount_usd']=='50.00'


def _report_decisions(role='repeat',day='2025-12-01'):
    return {'order_decisions':[{'order_id':'101','order_no':'PI-101','company_id':'111','owner_id':'70',
        'account_date':day,'role':role,'reason':'Verified original report ruling'}]}


def test_source_role_is_report_scoped_and_uses_original_not_return_date():
    from app.battle_report.order_decisions import decision_index
    original={'order_id':'101','order_no':'PI-101','customer_id':'111','owner_okki_user_id':'70',
        'account_date':'2025-12-01','raw_new_deal':None,'effective_date':'2026-10-01'}
    assert sources.source_role(original,decision_index(_report_decisions('repeat')))==('repeat',None)
    assert sources.source_role(original,decision_index(_report_decisions('new_sign')))==('new_sign',None)
    assert sources.source_role(original,{})[0]=='pending'
    role,issue=sources.source_role(original,decision_index(_report_decisions('repeat','2026-10-01')))
    assert role=='pending' and '核算日期' in issue


def test_current_report_ruling_classifies_return_amount_without_customer_count(db):
    from datetime import date,datetime
    from types import SimpleNamespace
    from app.sales_return.models import ReturnEffect
    from app.sales_return.gmv import adjustments
    from app.perf_goal.statistics import fetch_order_facts,aggregate,owner_total
    from app.battle_report.award_statistics import calculate
    original={'order_id':'101','order_no':'PI-101','customer_id':'111','owner_okki_user_id':'70',
        'account_date':'2025-12-01','raw_new_deal':None,'payments':[{'private':'not in projection'}]}
    db.add(ReturnEffect(return_id=999,effect_kind='activate',order_id='101',owner_okki_user_id='70',customer_id='111',
        currency='USD',amount=-50,amount_usd=-50,effective_date=date(2026,10,1),gmv_eligible=1,
        order_role='pending',departments=[{'department_id':1,'rate':100}],snapshot=original))
    db.flush()
    report_rules=_report_decisions('repeat')
    facts,issues=fetch_order_facts(db,['70'],date(2026,10,1),date(2026,10,31),report_rules)
    assert issues==[] and facts[0]['role']=='repeat'
    assert facts[0]['day']==date(2026,10,1) and 'payments' not in facts[0]['original_order']
    totals=owner_total(aggregate(facts),'70')
    assert totals['gmv']==totals['repeat_amount']==-50
    assert totals['new_sign']==totals['repeat_customers']==0
    member=SimpleNamespace(id=1,okki_user_id='70',user_name='Original',team='Team',ark_user_id=7,is_captain=False)
    report=SimpleNamespace(start_date=date(2026,10,1),end_date=date(2026,10,31),award_rules=report_rules,award_kind='new_sign_pk')
    result=calculate(report,[member],adjustments(db,date(2026,10,1),date(2026,10,31)),datetime(2026,10,30))
    person=result['people'][0]
    assert person['repeat_amount']=='-50.00' and person['new_count']==person['repeat_count']==person['repeat_orders']==0
    assert result['applied_order_decision_count']==1
    report.award_rules=_report_decisions('new_sign')
    changed=calculate(report,[member],adjustments(db,date(2026,10,1),date(2026,10,31)),datetime(2026,10,30))
    assert changed['people'][0]['new_amount']=='-50.00'
    assert changed['people'][0]['new_count']==changed['people'][0]['repeat_count']==0


@pytest.mark.parametrize('scope',['team','historical_owner'])
def test_team_and_historical_trend_paths_keep_original_report_ruling(db,scope):
    from datetime import date
    from app.sales_return.models import ReturnEffect
    from app.perf_goal.models import PerfGoalConfig
    from app.perf_goal.trend import _facts
    from app.perf_goal.statistics import aggregate,owner_total
    original={'order_id':'101','order_no':'PI-101','customer_id':'111','owner_okki_user_id':'70',
        'account_date':'2025-12-01','raw_new_deal':None}
    db.add(ReturnEffect(return_id=888,effect_kind='activate',order_id='101',owner_okki_user_id='70',customer_id='111',
        currency='USD',amount=-50,amount_usd=-50,effective_date=date(2026,10,1),gmv_eligible=1,
        order_role='pending',departments=[{'department_id':1,'rate':100}],snapshot=original))
    db.add(PerfGoalConfig(key='main',payload=_report_decisions('repeat')))
    db.flush()
    people=[{'okki_user_id':'70','user_id':7,'name':'Original','historical_return_owner':scope=='historical_owner'}]
    facts,issues=_facts(db,people,date(2026,10,1),date(2026,10,31),1 if scope=='team' else None)
    assert len(facts)==1 and facts[0]['role']=='repeat'
    assert not any('核算日期' in issue for issue in issues)
    totals=owner_total(aggregate(facts),'70')
    assert totals['gmv']==totals['repeat_amount']==-50
    assert totals['new_sign']==totals['repeat_customers']==0
