"""Inspection completion races on a test-owned loopback MySQL, never a shared DB."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

import pytest
from sqlalchemy import Column, MetaData, Table, text
from sqlalchemy.orm import Session

from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.settlement_models import ShipmentSettlement, ShipmentOutbound, SettlementApplication, SettlementEvent
from app.invoice import settlement_service, shipment_delivery
from app.receipt.models import Receipt
from app.shipping_inspection import outbound_service, service
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto, ShippingOperationEvent


@pytest.fixture
def shipment(mysql_engine, monkeypatch):
    metadata = MetaData()
    models = (Invoice, InvoiceItem, ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission,
        ShipmentSettlement, ShipmentOutbound, SettlementApplication, SettlementEvent,
        Receipt, ShippingInspection, ShippingInspectionPhoto, ShippingOperationEvent)
    for model in models:
        Table(model.__tablename__, metadata, *(Column(col.name, col.type,
            primary_key=col.primary_key, nullable=not col.primary_key) for col in model.__table__.columns))
    metadata.create_all(mysql_engine)
    monkeypatch.setattr(outbound_service.settings, 'BUSINESS_DB_NAME', mysql_engine.url.database)
    outbound_service._columns_cache.clear()
    with Session(mysql_engine, autoflush=False) as db:
        db.execute(text('CREATE TABLE IF NOT EXISTS okki_outbound_records (id VARCHAR(64) PRIMARY KEY, outbound_invoice_id VARCHAR(64), serial_id VARCHAR(96), company_id VARCHAR(64))'))
        db.execute(text('CREATE TABLE IF NOT EXISTS okki_outbound_record_items (id VARCHAR(64) PRIMARY KEY, outbound_invoice_id VARCHAR(64), outbound_record_id VARCHAR(64), order_id VARCHAR(64), order_record_id VARCHAR(64), product_id VARCHAR(64), sku_id VARCHAR(64), outbound_count INT)'))
        invoice = Invoice(invoice_no='INSPECTION', order_type='presale', customer_id='200', customer_name='Test',
            invoice_date=date(2026,10,10), currency='USD', product_amount=10, total_amount=10)
        db.add(invoice); db.flush()
        row = ShipmentSettlement(invoice_id=invoice.id, sequence=1, settlement_no=f'INSPECTION-{invoice.id}',
            state='outbound_pending', is_final=0, created_by=1, quote_hash='a'*64, request_hash='b'*64,
            request_key=f'inspection-{invoice.id}', quote={'new_payment_due':'10','deposit_applied':'0',
                'goods_payment_due':'10','goods_payment_charge':'0','freight_amount':'0','currency':'USD'})
        db.add(row); db.flush()
        payload = {'serial_id':row.settlement_no,'record_list':[{'order_id':100,'order_record_id':11,
            'product_id':1,'sku_id':2,'outbound_count':1}]}
        remote_id = str(900 + invoice.id)
        target = ShipmentOutbound(invoice_id=invoice.id, settlement_id=row.id, outbound_no=row.settlement_no,
            status='pending_remote', remote_id=remote_id, payload=payload, payload_hash=settlement_service.digest(payload),
            remote_line_snapshot={'11':{'outbound_record_id':'901','cost_unit_price_rmb':'0'}})
        receipt = Receipt(invoice_id=invoice.id, receipt_no=f'INSPECT-PAY-{invoice.id}', source='manual',
            purpose='presale_goods', amount=10, bank_charge=0, currency='USD', customer_id='200',
            collection_date=date(2026,10,10), payment_type='TT', created_by=1, collect_status=1,
            sync_status='synced', status='active', request_key=f'inspect-pay-{invoice.id}',request_hash='a'*64)
        db.add_all([target,receipt]); db.flush()
        db.add(SettlementApplication(settlement_id=row.id, receipt_id=receipt.id,component='goods',amount=10,bank_charge=0))
        record_id = 'mirror-' + str(invoice.id)
        inspection = ShippingInspection(outbound_record_id=record_id,outbound_no=row.settlement_no,status='draft',created_by=1)
        db.add(inspection); db.flush()
        db.add(ShippingInspectionPhoto(inspection_id=inspection.id,file_path='fixture.jpg',created_by=1))
        db.execute(text('INSERT INTO okki_outbound_records VALUES (:rid,:remote,:serial,\'200\')'),dict(rid=record_id,remote=remote_id,serial=row.settlement_no))
        db.execute(text('INSERT INTO okki_outbound_record_items VALUES (:rid,:remote,\'901\',\'100\',\'11\',\'1\',\'2\',1)'),dict(rid=record_id,remote=remote_id))
        db.commit()
        ids = (record_id, row.id, target.id, inspection.id)
    yield mysql_engine, ids
    outbound_service._columns_cache.clear()


def test_two_concurrent_submissions_consume_cash_once(shipment):
    engine, (record_id,row_id,target_id,inspection_id) = shipment
    barrier = Barrier(2)
    def submit():
        with Session(engine, autoflush=False) as db:
            barrier.wait(timeout=10)
            return service.submit(db,outbound_record_id=record_id,user_id=1).status
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit) for _ in range(2)]
        assert [future.result(timeout=20) for future in futures] == ['submitted','submitted']
    with Session(engine) as db:
        assert db.get(ShipmentSettlement,row_id).state == 'shipped'
        assert db.get(ShipmentOutbound,target_id).status == 'shipped'
        assert db.query(SettlementApplication).filter_by(settlement_id=row_id,status='applied').count() == 1
        assert db.query(SettlementEvent).filter_by(settlement_id=row_id,action='inspection_submitted').count() == 1


def test_real_recall_between_funding_read_and_apply_cannot_be_overwritten(shipment,monkeypatch):
    engine, (record_id,row_id,target_id,inspection_id) = shipment
    with Session(engine,autoflush=False) as db:
        service.submit(db,outbound_record_id=record_id,user_id=1)
        target=db.get(ShipmentOutbound,target_id)
        detail={**target.payload,'outbound_invoice_id':target.remote_id,'status':1,'create_time':'2026-10-10 10:00:00',
            'record_list':[{**target.payload['record_list'][0],'outbound_record_id':'901','cost_unit_price_rmb':'0'}]}
        monkeypatch.setattr(shipment_delivery.remote,'read',lambda *_:detail)
        monkeypatch.setattr(shipment_delivery.okki_client,'ensure_access_token',lambda *_:'test')
        monkeypatch.setattr(shipment_delivery.outbound_presence,'is_active',lambda *_:True)
        monkeypatch.setattr(shipment_delivery,'_live_funding',lambda *_:None)
        def recall(*_):
            db.commit()  # Funding IO owns no invoice/inspection locks.
            with Session(engine,autoflush=False) as other:
                service.recall(other,inspection_id,1,0)
            return True
        monkeypatch.setattr(shipment_delivery,'_refresh_funding',recall)
        with pytest.raises(ValueError,match='检验状态.*变化'):
            shipment_delivery.refresh(db,target_id)
    with Session(engine) as db:
        assert db.get(ShipmentSettlement,row_id).state == 'outbound_pending'
        assert db.get(ShipmentOutbound,target_id).status == 'pending_remote'
        assert db.get(ShippingInspection,inspection_id).status == 'draft'
        assert db.query(SettlementApplication).filter_by(settlement_id=row_id,status='applied').count() == 1
