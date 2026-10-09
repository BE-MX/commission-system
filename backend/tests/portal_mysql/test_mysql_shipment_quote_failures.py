"""Quote no-commercial-commit and fixed technical failure responses."""
from uuid import uuid4
import pytest
from sqlalchemy import event,select,MetaData,Table,Column,Integer,String
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from app.invoice import shipment_create_service as facts,shipment_quote_service
from app.receipt import remote
from test_mysql_shipment_read_boundaries import guarded
from test_mysql_shipment_reads import setup,request,ROUTES
from test_mysql_shipment_create import shipment_app,snapshot  # noqa: F401
from test_mysql_full_application import assembled,boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401


@pytest.mark.parametrize('route',ROUTES)
def test_current_authority_sql_failure_fixed_503_no_data(shipment_app,route):
    c=shipment_app;hits=[]
    def fail(connection,cursor,statement,parameters,context,executemany):
        if 'FROM ark_users' in statement:
            hits.append(statement);raise OperationalError('private-shipment-auth-query',{},Exception('private-db-marker'))
    with c.app.client() as client:
        _,owner=setup(client,c,route);before=snapshot(c);c.io.clear();event.listen(c.ctx.engine,'before_cursor_execute',fail)
        try:response=request(client,c,route,owner)
        finally:event.remove(c.ctx.engine,'before_cursor_execute',fail)
        guarded(response,503);assert hits and 'private-db-marker' not in response.text
        assert snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('fault',['rows_shape','amount','duplicate','order_shape'])
def test_quote_untrusted_provider_data_fixed_503(shipment_app,fault,monkeypatch):
    c=shipment_app;original=remote.order_snapshot
    def broken(db,target):
        data=original(db,target)
        if fault=='rows_shape':data['rows']=None
        elif fault=='amount':data['rows'][0]['amount']='NaN'
        elif fault=='duplicate':data['rows'].append(dict(data['rows'][0]))
        return data
    with c.app.client() as client:
        _,owner=setup(client,c,'quote');before=snapshot(c)
        if fault=='order_shape':monkeypatch.setattr(remote,'read',lambda *_:None)
        else:monkeypatch.setattr(remote,'order_snapshot',broken)
        response=request(client,c,'quote',owner);guarded(response,503)
        assert snapshot(c)==before and c.calls==[]


def test_success_quote_two_commits_then_final_rollback_no_business_dml(shipment_app,monkeypatch):
    c=shipment_app;sessions=[];commits=[];rollbacks=[];dml=[];original=shipment_quote_service._authorize;evidence=facts._evidence
    metadata=MetaData();table=Table('owned_quote_success_metadata',metadata,Column('id',Integer,primary_key=True),Column('value',String(12)))
    metadata.create_all(c.ctx.engine);identity=int(uuid4().hex[:7],16)
    with c.ctx.engine.begin() as connection:connection.execute(table.insert().values(id=identity,value='old'))
    def authorize_source(db,*args):
        if not any(db is item for item in sessions):sessions.append(db)
        return original(db,*args)
    def refresh(db,*args):db.execute(table.update().where(table.c.id==identity).values(value='new'));return evidence(db,*args)
    def committed(db):
        if any(db is item for item in sessions):commits.append(db)
    def rolled_back(db):
        if any(db is item for item in sessions):rollbacks.append(db)
    def observe(connection,cursor,statement,parameters,context,executemany):
        if statement.lstrip().split(' ',1)[0].upper() in {'INSERT','UPDATE','DELETE','REPLACE'}:dml.append(statement)
    with c.app.client() as client:
        _,owner=setup(client,c,'quote');before=snapshot(c)
        monkeypatch.setattr(shipment_quote_service,'_authorize',authorize_source);monkeypatch.setattr(facts,'_evidence',refresh)
        event.listen(Session,'after_commit',committed);event.listen(Session,'after_rollback',rolled_back);event.listen(c.ctx.engine,'before_cursor_execute',observe)
        try:response=request(client,c,'quote',owner)
        finally:
            event.remove(Session,'after_commit',committed);event.remove(Session,'after_rollback',rolled_back);event.remove(c.ctx.engine,'before_cursor_execute',observe)
        guarded(response,200);assert response.json()['data']['new_payment_due']=='64.00'
        assert len(sessions)==1 and commits==[sessions[0],sessions[0]] and rollbacks and all(db is sessions[0] for db in rollbacks)
        assert len(dml)==1 and 'owned_quote_success_metadata' in dml[0] and snapshot(c)==before and c.calls==[]
        with Session(c.ctx.engine) as db:assert db.scalar(select(table.c.value).where(table.c.id==identity))=='new'
