"""Owned loopback MySQL 8: migration and actual financial writer contention.

Requires portal_mysql's fresh-datadir fixture; never accepts a database URL.
Only source evidence is synthetic. Services, authority, money, SQL and locks run.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import queue
from uuid import uuid4

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi import HTTPException
import pytest
from sqlalchemy import Column, MetaData, Table, event, func, inspect, select, text
from sqlalchemy.orm import Session

from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission, ArkUserExternalBinding
from app.invoice.models import Invoice
from app.invoice.settlement_models import Receivable
from app.models.commission import CommissionBatch, CommissionDetail, SyncedPayment, PaymentCommissionStatus
from app.models.customer import CustomerCommissionSnapshot
from app.portal.models import AuthorityBarrier
from app.sales_return import access, read_service, schemas, service, sources
from app.sales_return.models import SalesReturn, ReturnAllocation, ReturnEffect, ReturnReceipt
from app.sales_return.router import execute
from app.services.commission_calculator import calculate_commission, confirm_batch
from test_mysql_concurrency import wait_for_lock

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='session')
def return_mysql_schema(mysql_engine):
    metadata=MetaData()
    upstream=(ArkUser,ArkRole,ArkPermission,ArkUserRole,ArkRolePermission,ArkUserExternalBinding,Invoice,
        SyncedPayment,CommissionBatch,CommissionDetail,PaymentCommissionStatus,CustomerCommissionSnapshot,AuthorityBarrier,Receivable)
    for model in upstream:
        Table(model.__tablename__,metadata,*(Column(c.name,c.type,primary_key=c.primary_key,nullable=c.nullable,
            default=c.default,server_default=c.server_default) for c in model.__table__.columns
            if not (model is SyncedPayment and c.name=='source')))
    metadata.create_all(mysql_engine)
    spec=spec_from_file_location('owned_sales_return_migration',BACKEND/'alembic/versions/214_sales_return_ledger.py')
    migration=module_from_spec(spec)
    spec.loader.exec_module(migration)
    for _ in range(2):
        with mysql_engine.begin() as connection:
            migration.op=Operations(MigrationContext.configure(connection))
            migration.upgrade()
    with Session(mysql_engine) as db:
        db.add(AuthorityBarrier(code='authority',version=1))
        role=ArkRole(name='super_admin',label='Owned isolated admin')
        users=[ArkUser(username=f'owned-admin-{number}',password_hash='test-only',real_name=f'Owned Admin {number}',roles=[role]) for number in (1,2)]
        db.add_all(users)
        db.flush()
        actors=[user.id for user in users]
        db.commit()
    return mysql_engine,actors


@pytest.fixture
def scenario(return_mysql_schema,monkeypatch):
    engine,actors=return_mysql_schema
    order=uuid4().hex
    snapshot={'order_id':order,'order_no':'PI-'+order,'customer_id':'C-'+order,'customer_name':'Synthetic Company',
        'owner_okki_user_id':'original-owner','sales_user_id':None,'invoice_id':None,'currency':'USD',
        'goods_amount':'100.00','goods_amount_usd':'100.00','gmv_eligible':True,'order_role':'repeat','departments':[],
        'binding_hash':'owned-synthetic','lines':[{'source_key':'OUT:LINE','outbound_id':'OUT','outbound_line_id':'LINE',
        'order_line_id':'ORIGINAL-LINE','product_id':'1','sku_id':'1','product_name':'Synthetic Hair','specification':'',
        'quantity':1,'net_amount':'100.00','net_amount_usd':'100.00'}],
        'payments':[{'payment_id':'PAY-'+order,'principal':'100.00','principal_usd':'100.00',
        'collection_date':'2025-12-01','currency':'USD','commission_basis_usd':'100.00'}]}
    monkeypatch.setattr(sources,'snapshot',lambda *_args,**_kwargs:deepcopy(snapshot))
    return engine,actors,snapshot


def _user(actor):
    return {'sub':str(actor),'roles':['super_admin'],'permissions':[]}


def _draft(snapshot,key):
    return schemas.Create(order_id=snapshot['order_id'],return_type='return_refund',reason_code='quality',
        reason='Owned MySQL verified return',request_key=key,lines=[{'source_key':'OUT:LINE','quantity':1,'reduction_amount':'100.00'}])


def _prepare(ctx,count=1):
    engine,actors,snapshot=ctx
    result=[]
    for number in range(count):
        with Session(engine) as db:
            body=_draft(snapshot,uuid4().hex)
            current=access.authorize(db,_user(actors[number%2]),'sales_return:write',write=True)
            quote=service.preview(db,body,current)
            row=service.create(db,body,current)
            db.commit()
            result.append((row.id,schemas.Activate(version=1,quote_version=quote['quote_version'],request_key=uuid4().hex)))
    return result


def _activate(db,actor,identifier,body):
    result=execute(db,_user(actor),'sales_return:write',lambda current: _result(service.activate(db,identifier,body,current)),write=True)
    return result['data']


def _result(row):
    return {'id':row.id,'status':row.status}


def _compete(ctx,first_action,second_action,*,commit=True):
    """Hold the real first transaction; prove the second is waiting in InnoDB."""
    engine=ctx[0]
    started=queue.Queue()
    def second():
        with Session(engine) as db:
            started.put(db.scalar(text('SELECT CONNECTION_ID()')))
            try:
                result=second_action(db)
                db.commit()
                return {'ok':result}
            except (HTTPException,ValueError) as error:
                db.rollback()
                return {'status':getattr(error,'status_code',409),'detail':str(error)}
    with Session(engine) as first,ThreadPoolExecutor(max_workers=1) as executor:
        first_result=first_action(first)
        future=executor.submit(second)
        try:
            wait_for_lock(engine,started.get(timeout=3))
            assert not future.done(),'The second writer must really wait before first commit/rollback'
            first.commit() if commit else first.rollback()
        finally:
            first.rollback()
        second_result=future.result(timeout=10)
    return first_result,second_result


def _uncommitted_activation(db,actor,identifier,body):
    current=access.authorize(db,_user(actor),'sales_return:write',write=True)
    row=service.activate(db,identifier,body,current)
    db.flush()
    return _result(row)


def _counts(engine,order):
    with Session(engine) as db:
        return tuple(db.scalar(select(func.count()).select_from(model).where(model.order_id==order))
                     for model in (ReturnEffect,ReturnReceipt,SyncedPayment))


def test_migration_214_is_repeatable_and_fk_types_match(return_mysql_schema):
    engine,_=return_mysql_schema
    config=Config()
    config.set_main_option('script_location',str(BACKEND/'alembic'))
    assert ScriptDirectory.from_config(config).get_heads()==['214_sales_return_ledger']
    with engine.connect() as connection:
        columns={column['name'] for column in inspect(connection).get_columns('synced_payment')}
        assert 'source' in columns
        fks=connection.execute(text('''SELECT k.TABLE_NAME,k.COLUMN_NAME,k.REFERENCED_TABLE_NAME,k.REFERENCED_COLUMN_NAME,
            c.COLUMN_TYPE,p.COLUMN_TYPE AS parent_type FROM information_schema.KEY_COLUMN_USAGE k
            JOIN information_schema.COLUMNS c ON c.TABLE_SCHEMA=k.TABLE_SCHEMA AND c.TABLE_NAME=k.TABLE_NAME AND c.COLUMN_NAME=k.COLUMN_NAME
            JOIN information_schema.COLUMNS p ON p.TABLE_SCHEMA=k.REFERENCED_TABLE_SCHEMA AND p.TABLE_NAME=k.REFERENCED_TABLE_NAME AND p.COLUMN_NAME=k.REFERENCED_COLUMN_NAME
            WHERE k.TABLE_SCHEMA=DATABASE() AND k.REFERENCED_TABLE_NAME IS NOT NULL AND k.TABLE_NAME LIKE 'ark%return%' ''')).mappings().all()
        assert len(fks)>=8
        assert all(row['COLUMN_TYPE']==row['parent_type'] for row in fks)
        assert connection.scalar(text('SELECT @@transaction_isolation'))=='REPEATABLE-READ'


def test_two_people_cannot_return_the_same_last_shipped_quantity(scenario):
    (first_id,first_body),(second_id,second_body)=_prepare(scenario,2)
    engine,actors,snapshot=scenario
    _,loser=_compete(scenario,
        lambda db:_uncommitted_activation(db,actors[0],first_id,first_body),
        lambda db:_activate(db,actors[1],second_id,second_body))
    assert loser.get('status')==409,loser
    assert _counts(engine,snapshot['order_id'])==(1,1,1)
    with Session(engine) as db:
        assert db.get(SalesReturn,first_id).status=='effective'
        assert db.get(SalesReturn,second_id).status=='draft'
        assert db.scalar(select(func.sum(ReturnReceipt.amount)).where(ReturnReceipt.order_id==snapshot['order_id']))==Decimal('-100')


def test_concurrent_same_key_and_lost_ack_replay_one_financial_group(scenario):
    (identifier,body),=_prepare(scenario)
    engine,actors,snapshot=scenario
    first,replayed=_compete(scenario,
        lambda db:_uncommitted_activation(db,actors[0],identifier,body),
        lambda db:_activate(db,actors[1],identifier,body))
    assert replayed=={'ok':first}
    # The first reply can be lost after COMMIT; a new connection uses exactly
    # the original command identity and recovers the persisted result.
    with Session(engine) as db:
        assert _activate(db,actors[0],identifier,body)==first
    assert _counts(engine,snapshot['order_id'])==(1,1,1)


def test_real_rollback_releases_quota_without_partial_finance(scenario):
    (first_id,first_body),(second_id,second_body)=_prepare(scenario,2)
    engine,actors,snapshot=scenario
    _,winner=_compete(scenario,
        lambda db:_uncommitted_activation(db,actors[0],first_id,first_body),
        lambda db:_activate(db,actors[1],second_id,second_body),commit=False)
    assert winner=={'ok':{'id':second_id,'status':'effective'}}
    assert _counts(engine,snapshot['order_id'])==(1,1,1)
    with Session(engine) as db:
        assert db.get(SalesReturn,first_id).status=='draft'
        assert db.get(SalesReturn,second_id).status=='effective'
        assert db.scalar(select(func.count()).select_from(ReturnAllocation).where(ReturnAllocation.return_id==first_id))==0


def test_sql_insert_failure_rolls_back_actual_router_finance_transaction(scenario):
    (identifier,body),=_prepare(scenario)
    engine,actors,snapshot=scenario
    def fail(_mapper,_connection,target):
        if target.order_id==snapshot['order_id'] and target.source=='ark_return':
            raise ValueError('Owned storage failure')
    event.listen(SyncedPayment,'before_insert',fail)
    try:
        with Session(engine) as db:
            with pytest.raises(HTTPException) as error:
                _activate(db,actors[0],identifier,body)
            assert error.value.status_code==409
    finally:
        event.remove(SyncedPayment,'before_insert',fail)
    assert _counts(engine,snapshot['order_id'])==(0,0,0)
    with Session(engine) as db:
        assert db.get(SalesReturn,identifier).status=='draft'
        assert _activate(db,actors[0],identifier,body)['status']=='effective'
    assert _counts(engine,snapshot['order_id'])==(1,1,1)


@pytest.mark.parametrize('refund_first',[True,False])
def test_commission_confirmation_and_new_refund_obey_real_commit_order(scenario,refund_first):
    (identifier,body),=_prepare(scenario)
    engine,actors,snapshot=scenario
    with Session(engine) as db:
        original_batch=CommissionBatch(batch_name='Original paid '+uuid4().hex,period_start=date(2025,12,1),
            period_end=date(2025,12,31),status='confirmed')
        db.add(original_batch)
        db.flush()
        payment_id=snapshot['payments'][0]['payment_id']
        db.add(SyncedPayment(payment_id=payment_id,source='okki',order_id=snapshot['order_id'],
            customer_id=snapshot['customer_id'],payment_date=date(2025,12,1),payment_amount=100,service_fee=0))
        db.add(CommissionDetail(batch_id=original_batch.id,payment_id=payment_id,order_id=snapshot['order_id'],
            customer_id=snapshot['customer_id'],payment_amount=100,salesperson_id='original-person',
            salesperson_rate=Decimal('.02'),salesperson_commission=2,status='paid'))
        db.add(PaymentCommissionStatus(payment_id=payment_id,batch_id=original_batch.id))
        batch=CommissionBatch(batch_name='Owned confirmation '+uuid4().hex,period_start=date(2026,1,1),
            period_end=date(2099,12,31),status='calculated')
        db.add(batch)
        db.flush()
        batch_id=batch.id
        # Earlier cases may retain unrelated refund inputs. Mark those existing
        # inputs assigned so this case isolates only the newly racing refund.
        previous=db.scalars(select(SyncedPayment).where(SyncedPayment.source=='ark_return')).all()
        assigned=set(db.scalars(select(PaymentCommissionStatus.payment_id)).all())
        for payment in previous:
            if payment.payment_id not in assigned:
                db.add(PaymentCommissionStatus(payment_id=payment.payment_id,batch_id=batch.id))
        db.commit()
    def confirmation(db):
        confirm_batch(db,batch_id,str(actors[1]))
        return {'confirmed':True}
    if refund_first:
        _,outcome=_compete(scenario,
            lambda db:_uncommitted_activation(db,actors[0],identifier,body),confirmation)
        assert outcome.get('status')==409,outcome
        with Session(engine) as db:
            assert db.get(CommissionBatch,batch_id).status=='calculated'
    else:
        _,outcome=_compete(scenario,confirmation,
            lambda db:_activate(db,actors[0],identifier,body))
        assert outcome=={'ok':{'id':identifier,'status':'effective'}}
        with Session(engine) as db:
            assert db.get(CommissionBatch,batch_id).status=='confirmed'
            payment=db.scalar(select(SyncedPayment).where(SyncedPayment.order_id==snapshot['order_id'],SyncedPayment.source=='ark_return'))
            assert db.scalar(select(PaymentCommissionStatus).where(PaymentCommissionStatus.payment_id==payment.payment_id)) is None
            # An event committed just after confirmation remains unassigned and
            # is actually calculated in the next period despite its older date.
            catchup=CommissionBatch(batch_name='Catchup '+uuid4().hex,period_start=payment.payment_date+timedelta(days=1),
                period_end=payment.payment_date+timedelta(days=1),status='draft')
            db.add(catchup)
            db.flush()
            computed=calculate_commission(db,catchup.id)
            assert computed.total_payments==1 and computed.errors==[]
            detail=db.scalar(select(CommissionDetail).where(CommissionDetail.batch_id==catchup.id))
            assert detail.payment_id==payment.payment_id and detail.salesperson_id=='original-person'
            assert detail.salesperson_commission==Decimal('-2.00')
            confirm_batch(db,catchup.id,str(actors[1]))
            db.commit()
