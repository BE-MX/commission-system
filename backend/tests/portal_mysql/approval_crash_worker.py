"""Spawn-only approval transaction owner; private connection data stays in IPC."""
def write_table(statement,database,allowed):
    import re
    remaining=statement.strip()
    while True:
        comment=re.match(r'(?:/\*[\s\S]*?\*/|--[^\r\n]*(?:\r?\n|$)|\#[^\r\n]*(?:\r?\n|$))\s*',remaining)
        if not comment:break
        remaining=remaining[comment.end():]
    if re.match(r'^(?:SELECT|SHOW|DESCRIBE|DESC|EXPLAIN)\b',remaining,re.I):return None
    if re.fullmatch(r'SET SESSION innodb_lock_wait_timeout\s*=\s*%s',remaining,re.I):return None
    if re.fullmatch(r'(?:SAVEPOINT|RELEASE SAVEPOINT|ROLLBACK TO SAVEPOINT)\s+[A-Za-z0-9_]+',remaining,re.I):return None
    match=re.match(r'^(?:INSERT\s+(?:(?:LOW_PRIORITY|DELAYED|HIGH_PRIORITY|IGNORE)\s+)*(?:INTO\s+)?|REPLACE\s+(?:(?:LOW_PRIORITY|DELAYED)\s+)*(?:INTO\s+)?|UPDATE\s+(?:(?:LOW_PRIORITY|IGNORE)\s+)*|DELETE\s+(?:(?:LOW_PRIORITY|QUICK|IGNORE)\s+)*FROM\s+)(`?[A-Za-z0-9_]+`?(?:\.`?[A-Za-z0-9_]+`?)?)(?=\s|\(|$)',remaining,re.I)
    assert match is not None,'Unexpected statement outside finite approval SQL gate'
    parts=match.group(1).replace('`','').split('.')
    assert len(parts)==1 or parts[0]==database,'Unexpected DML schema'
    table=parts[-1]
    assert table in allowed,'Unexpected commercial DML outside twelve-model approval graph'
    return table


def run(url,settings,command,checkpoint,release,output):
    import os,socket
    from pathlib import Path
    from types import SimpleNamespace
    from decimal import Decimal
    from uuid import uuid4,UUID
    import pymysql
    from sqlalchemy import create_engine,event,text
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session
    import conftest as isolation
    engine=None
    try:
        assert not (Path(__file__).resolve().parents[2]/'.env').exists()
        isolation.ALLOWED.update(port=url.port,password=url.password,database=url.database)
        assert url.host=='127.0.0.1' and url.database=='portal_isolated_test'
        pymysql.connect=isolation.isolated_connect
        event.listen(Engine,'do_connect',isolation.isolated_engine)
        original_connect,original_connect_ex=socket.socket.connect,socket.socket.connect_ex
        def permitted(address):
            assert isinstance(address,tuple) and address[:2]==('127.0.0.1',url.port),'Only owned MySQL socket allowed'
        def connect(sock,address):permitted(address);return original_connect(sock,address)
        def connect_ex(sock,address):permitted(address);return original_connect_ex(sock,address)
        socket.socket.connect=connect;socket.socket.connect_ex=connect_ex
        import mysql_service_fixture  # noqa: F401; register models without fixture execution
        from app.core.time import beijing_now
        from app.portal import (auth_service as auth,authority,admin_service,quote_service,
            catalog_service,pricing,sku_source,order_queries,approval_service,invoice_adapter,order_service,proposal_decisions)
        from app.portal.inventory import InventoryObservation
        from app.portal.schemas import ApproveInput,SubmitInput,AcceptInput
        from app.portal.models import OrderRequest,Revision,RequestLine,CommandReceipt,Conversion,Publication,PiAmendment,AuditEvent,OutboxEvent,Quote,PortalSession
        from app.invoice.models import Invoice,InvoiceItem
        from app.receipt.models import ReceiptIntent
        config=SimpleNamespace(**settings)
        for module in (auth,authority,admin_service,quote_service,catalog_service,pricing,sku_source,order_queries):
            module.get_settings=lambda:config
        operation=command.get('operation','approve')
        assert operation in {'approve','submit','accept'}
        probes={'stock':0,'price':0,'writes':{}}
        if operation!='approve':probes['auth_writes']={}
        def stock(db,rows):
            probes['stock']+=1
            if command['sources_unavailable']:raise AssertionError('Successful replay must not query inventory')
            return {row.public_id:InventoryObservation(Decimal('1000'),'g',beijing_now(),'synthetic-test-mirror') for row in rows}
        catalog_service.load_observations=stock
        original_price=pricing.resolve
        def price(*args,**kwargs):
            probes['price']+=1
            if command['sources_unavailable']:raise AssertionError('Successful replay must not query price')
            return original_price(*args,**kwargs)
        pricing.resolve=price
        sku_source.product_service._schema=lambda:'portal_isolated_test'
        invoices=invoice_adapter.invoices
        invoices.resolve_okki_flags=lambda *args:{'okki_new_deal':1,'okki_free_shipping':0,'okki_first_return':0}
        invoices.get_customer_grade=lambda *args:None
        invoices.suggest_invoice_no=lambda *args:'PI-CRASH-'+uuid4().hex
        invoices.product_service.valid_okki_product_skus=lambda db,pairs:pairs
        engine=create_engine(url,isolation_level='REPEATABLE READ',hide_parameters=True)
        allowed={model.__tablename__ for model in (Invoice,InvoiceItem,ReceiptIntent,OrderRequest,Revision,
            RequestLine,CommandReceipt,Conversion,Publication,PiAmendment,AuditEvent,OutboxEvent)}
        if operation!='approve':allowed.update({Quote.__tablename__,PortalSession.__tablename__})
        @event.listens_for(engine,'before_cursor_execute')
        def write_guard(connection,cursor,statement,parameters,context,executemany):
            table=write_table(statement,url.database,allowed)
            if table is not None:
                bucket=probes['auth_writes'] if operation!='approve' and table==PortalSession.__tablename__ else probes['writes']
                bucket[table]=bucket.get(table,0)+1
        @event.listens_for(engine,'connect')
        def configure(connection,record):
            with connection.cursor() as cursor:
                cursor.execute("SET time_zone = '+08:00'")
                cursor.execute('SET SESSION innodb_lock_wait_timeout = 8')
        with Session(engine) as db:
            connection_id=db.scalar(text('SELECT CONNECTION_ID()'));db.rollback()
            original_commit=db.commit
            if checkpoint is not None:
                assert checkpoint in {'before_commit','after_commit'}
                def controlled_commit():
                    if checkpoint=='after_commit':original_commit()
                    output.put(('checkpoint',os.getpid(),connection_id,checkpoint))
                    if not release.wait(30):raise AssertionError('Owned crash checkpoint not released')
                    raise AssertionError('Crash worker must be killed before returning a receipt')
                db.commit=controlled_commit
            if operation=='approve':
                result=approval_service.execute(db,command['actor'],command['request_id'],3,
                    ApproveInput.model_validate(command['body']))
            elif operation=='submit':
                result=order_service.submit(db,command['token'],command['csrf'],UUID(command['key']),
                    SubmitInput.model_validate(command['body']))
                db.commit()
            else:
                result=proposal_decisions.decide(db,command['token'],command['csrf'],command['request_id'],
                    command['revision_id'],command['version'],AcceptInput.model_validate(command['body']),accept=True)
                db.commit()
            output.put(('success',os.getpid(),result,probes))
    except Exception as error:
        output.put(('worker_error',type(error).__name__))
    finally:
        if engine is not None:engine.dispose()
