"""Portal PI creation/replay is local and never executes stock or receipt writes."""
from decimal import Decimal
from uuid import uuid4
from app.core.time import beijing_today
import re
import smtplib
import urllib.request
import httpx
import socket
from sqlalchemy import Column, MetaData, Table, event, select
from sqlalchemy.orm import Session
from app.invoice import okki_client, xiaoman_service, outbound_task_service
from app.invoice.models import Invoice, InvoiceItem, OkkiOutboundTask, InvoiceSyncLog, InvoiceLinkedSync
from app.invoice.settlement_models import ShipmentSettlement, ShipmentOutbound, Receivable, ReceiptBatch
from app.receipt import service as receipts, sync_service, invoice_link
from app.receipt.models import Receipt, ReceiptIntent, ReceiptLog
from app.semifinished import invoice_service as allocations, inventory_service
from app.semifinished.models import InvoiceAllocation, InventoryBalance, InventoryLedger
from app.shipping_inspection.models import ShippingOperationEvent
from app.portal import approval_service, pi_service
from app.portal.models import OrderRequest, OutboxEvent
from test_mysql_services import accepted_request, assert_one_pi


def test_real_pi_and_replay_never_push_reserve_ship_or_collect(trade, monkeypatch):
    ctx = trade
    forbidden_models = (Receipt,ReceiptLog,InvoiceAllocation,InventoryBalance,InventoryLedger,
        OkkiOutboundTask,InvoiceSyncLog,InvoiceLinkedSync,ShippingOperationEvent,
        ShipmentSettlement,ShipmentOutbound,Receivable,ReceiptBatch)
    metadata = MetaData()
    for model in forbidden_models:
        Table(model.__tablename__,metadata,*(Column(c.name,c.type,primary_key=c.primary_key,
            nullable=False if c.primary_key else True) for c in model.__table__.columns))
    metadata.create_all(ctx.engine,checkfirst=True)
    # Nonempty unrelated stock/receipt balances detect accidental updates as well
    # as extra rows. Thin upstream tables omit FKs; these are isolated sentinels.
    with Session(ctx.engine) as db:
        db.add(InventoryBalance(id=900001,material_id=900001,on_hand_grams=100,reserved_grams=15,version=7))
        db.add(Receipt(id=900001,receipt_no='ISOLATED-OLD-RECEIPT',invoice_id=900001,
            source='manual',request_key=uuid4().hex,request_hash='a'*64,amount=12,currency='USD',
            collection_date=beijing_today(),payment_type='bank',customer_id='owned-sentinel',
            created_by=ctx.actor,status='active',sync_status='synced',version=2))
        db.commit()
    def snapshot():
        with Session(ctx.engine) as db:
            return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
                for model in forbidden_models)
    baseline = snapshot()
    called = []
    def forbid(name):
        def denied(*args,**kwargs):
            called.append(name)
            raise AssertionError('Forbidden side effect: '+name)
        return denied
    boundaries = ((xiaoman_service,'sync_invoice'),(okki_client,'push_order'),
        (okki_client,'push_outbound'),(outbound_task_service,'enqueue_outbound_task'),
        (allocations,'prepare_invoice_sync'),(allocations,'finalize_invoice_sync'),
        (inventory_service,'write_ledger'),(receipts,'new_row'),(sync_service,'deliver'),
        (invoice_link,'arm'))
    for module,name in boundaries: monkeypatch.setattr(module,name,forbid(module.__name__+'.'+name))
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',forbid('httpx-network'))
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',forbid('httpx-async-network'))
    monkeypatch.setattr(urllib.request,'urlopen',forbid('urllib-network'))
    monkeypatch.setattr(smtplib.SMTP,'sendmail',forbid('smtp-send'))
    original_connect = socket.socket.connect
    database_connections = []
    def owned_connect(connection,address):
        if not isinstance(address,tuple) or address[:2] != ('127.0.0.1',ctx.engine.url.port):
            called.append('non-owned-network')
            raise AssertionError('Only the owned MySQL socket is allowed')
        database_connections.append(True)
        return original_connect(connection,address)
    monkeypatch.setattr(socket.socket,'connect',owned_connect)
    # Force actual DB reconnect to prove the network guard permits the owned DB.
    ctx.engine.dispose()
    # Detect attempted DML, including effects rolled back before final snapshots.
    writes = []
    forbidden_writes = []
    def inspect_write(connection,cursor,statement,parameters,context,executemany):
        match = re.match(r'\s*(?:INSERT\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)\s+[`"]?(\w+)',statement,re.I)
        if not match: return
        table = match.group(1); writes.append(table)
        if table not in {'ark_invoices','ark_invoice_items'} and not table.startswith('ark_order_portal_'):
            forbidden_writes.append(table)
            raise AssertionError('Unexpected approval DML: '+table)
    event.listen(ctx.engine,'before_cursor_execute',inspect_write)
    try:
        request_id,accepted = accepted_request(ctx)
        with Session(ctx.engine) as db:
            result = approval_service.execute(db,ctx.actor,request_id,3,accepted)
            assert not result['replayed'] and result['current_state'] == 'invoice_created'
        assert snapshot() == baseline
        assert_one_pi(ctx,request_id)
        with Session(ctx.engine) as db:
            order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
            invoice = db.get(Invoice,order.invoice_id)
            intent = db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id == invoice.id))
            item = db.scalar(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id))
            assert invoice.total_amount == Decimal('128.00')
            assert invoice.internal_received is None and invoice.internal_balance is None
            assert invoice.sync_status == 'not_synced' and invoice.xiaoman_order_id is None
            assert invoice.outbound_auto_requested == 0 and invoice.linked_sync_id is None
            assert item.semifinished_enabled == 0 and not item.semifinished_plan and item.xiaoman_unique_id is None
            # Portal PIs skip the creation-time receipt intent draft; Ark receipt
            # entries (manual receipt or invoice edit) handle collection later.
            assert intent is None
            _,_,published = pi_service.capture(db,ctx.token,request_id)
            assert published['total_amount'] == '128.00'
            db.commit()
            replay = approval_service.execute(db,ctx.actor,request_id,3,accepted)
            assert replay['replayed'] and replay['original_receipt'] == result['original_receipt']
        assert snapshot() == baseline
        assert_one_pi(ctx,request_id)
        assert called == [] and forbidden_writes == [] and database_connections
        assert {'ark_invoices','ark_invoice_items'} <= set(writes) and 'ark_receipt_intents' not in set(writes)
        with Session(ctx.engine) as db:
            notice = db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == 'order_invoice_created',
                OutboxEvent.aggregate_public_id == request_id))
            assert notice.status == 'pending'  # Notice queue is allowed; no worker runs here.
    finally:
        event.remove(ctx.engine,'before_cursor_execute',inspect_write)