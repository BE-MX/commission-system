"""Owned InnoDB funding races; real model columns, synthetic provider evidence.

This finite schema preserves financial unique constraints and production column
types/defaults; it is not a full migration replay or employee HTTP auth test.
Every write uses the guarded, freshly started mysql_engine from conftest.py.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date
from decimal import Decimal
import queue
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import Column, MetaData, Table, UniqueConstraint, select, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.invoice import settlement_service as shipments, shipment_create_service, shipment_state_service
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.settlement_models import (ShipmentSettlement, SettlementItem, SettlementApplication,
    SettlementEvent, ShipmentOutbound, Receivable, ReceiptBatch, BatchAttachment)
from app.invoice.settlement_schemas import ShipmentCreate, ShipmentQuote
from app.receipt import purpose_service
from app.receipt.models import Receipt, ReceiptIntent, ReceiptLog, ReceiptAttachment
from app.receipt.schemas import PresalePurposeUpdate
from app.semifinished.models import InvoiceAllocation

USER = {"sub": "1", "roles": ["super_admin"], "permissions": []}


@pytest.fixture(scope="session")
def funding_schema(mysql_engine):
    metadata = MetaData()
    for model in (Invoice, InvoiceItem, Receipt, ReceiptIntent, ReceiptLog, ReceiptAttachment,
            InvoiceAllocation, ShipmentSettlement, SettlementItem, SettlementApplication,
            SettlementEvent, ShipmentOutbound, Receivable, ReceiptBatch, BatchAttachment):
        columns = [Column(column.name, column.type, primary_key=column.primary_key,
            nullable=column.nullable, autoincrement=column.autoincrement, default=column.default,
            server_default=column.server_default, onupdate=column.onupdate)
            for column in model.__table__.columns]
        unique = [UniqueConstraint(*(column.name for column in constraint.columns), name=constraint.name)
            for constraint in model.__table__.constraints if isinstance(constraint, UniqueConstraint)]
        Table(model.__tablename__, metadata, *columns, *unique)
    metadata.create_all(mysql_engine)
    with mysql_engine.connect() as connection:
        assert connection.scalar(text("SELECT @@transaction_isolation")) == "REPEATABLE-READ"
        assert connection.scalar(text("SELECT ENGINE FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ark_settlement_applications'")) == "InnoDB"
    return mysql_engine


@pytest.fixture
def funds(funding_schema, monkeypatch):
    monkeypatch.setattr(shipments, "require_enabled", lambda: None)
    slug = uuid4().hex
    with Session(funding_schema) as db:
        invoice = Invoice(invoice_no="MYSQL-" + slug, order_type="presale", customer_id="C1",
            customer_name="Veronika", sales_user_id=1, invoice_date=date(2026, 10, 9), currency="USD",
            product_amount=627, total_amount=627, surcharge_amount=0, internal_accessory=0, shipping_fee=0,
            sync_status="synced", xiaoman_order_id=str(int(slug[:12], 16)))
        invoice.items = [InvoiceItem(product_id=1, sku_id=2, product_name="Hair", product_display="Hair",
            color="Black", quantity=3, price_per_piece=209, total_price=627, xiaoman_unique_id="11")]
        db.add(invoice); db.flush()
        receipt = Receipt(invoice_id=invoice.id, receipt_no="PAY-" + slug, source="manual",
            purpose="presale_advance", request_key="pool_" + slug, request_hash="a"*64,
            amount=1077, bank_charge=0, currency="USD", customer_id="C1", collection_date=date(2026, 10, 8),
            payment_type="TT", attachment_ids=[], xiaoman_order_id=invoice.xiaoman_order_id,
            xiaoman_receipt_id=str(int(slug[12:24], 16)), collect_status=1, sync_status="synced", created_by=1)
        db.add(receipt); db.flush()
        values = SimpleNamespace(engine=funding_schema, invoice=invoice.id, item=invoice.items[0].id,
            receipt=receipt.id, evidence={"receipt": {"rows": [{"cash_collection_id": receipt.xiaoman_receipt_id,
                "amount": "1077.00", "currency": "USD", "collect_status": 1}]}, "outbounds": [],
                "order": {"order_id": invoice.xiaoman_order_id}, "freight": {}})
        db.commit()
    return values


def lock_invoice(db, values):
    invoice = db.scalar(select(Invoice).where(Invoice.id == values.invoice).with_for_update()
        .execution_options(populate_existing=True))
    items = db.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id).order_by(InvoiceItem.id)
        .with_for_update().execution_options(populate_existing=True)).all()
    set_committed_value(invoice, "items", items)
    return invoice


def wait_for_lock(engine, connection_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with engine.connect() as observer:
            waiting = observer.scalar(text("SELECT COUNT(*) FROM performance_schema.data_lock_waits w "
                "JOIN performance_schema.threads t ON t.THREAD_ID=w.REQUESTING_THREAD_ID "
                "WHERE t.PROCESSLIST_ID=:identity"), {"identity": connection_id})
        if waiting:
            return
        time.sleep(.025)
    pytest.fail("Second independent connection did not enter an observed InnoDB lock wait")


def body_for(values, quote, *, freight="38", final=False):
    return ShipmentCreate(items=[{"invoice_item_id": values.item, "quantity": 3}],
        freight_amount=freight, is_final=final, quote_hash=quote["quote_hash"], request_key=uuid4().hex)


def test_quote_creation_waits_for_invoice_then_rejects_double_reservation(funds):
    with Session(funds.engine, autoflush=False) as db:
        invoice = lock_invoice(db, funds)
        draft = ShipmentQuote(items=[{"invoice_item_id": funds.item, "quantity": 3}], freight_amount="38")
        quote = shipments.build_quote(db, invoice, draft, funds.evidence, current=True)
        db.rollback()
    bodies = [body_for(funds, quote) for _ in range(2)]
    held, release = threading.Event(), threading.Event()
    second_connection = queue.Queue()
    start = threading.Barrier(2)
    def first():
        with Session(funds.engine, autoflush=False) as db:
            invoice = lock_invoice(db, funds)
            row = shipments._create_verified(db, invoice, bodies[0], USER, funds.evidence, None)
            db.flush(); held.set()
            assert release.wait(10)
            db.commit()
            return row.id
    def second():
        with Session(funds.engine, autoflush=False) as db:
            second_connection.put(db.scalar(text("SELECT CONNECTION_ID()")))
            start.wait(timeout=5)
            invoice = lock_invoice(db, funds)
            with pytest.raises(ValueError, match="活动发货结算"):
                shipments._create_verified(db, invoice, bodies[1], USER, funds.evidence, None)
            db.rollback()
            return "rejected"
    with ThreadPoolExecutor(max_workers=2) as executor:
        winner = executor.submit(first)
        assert held.wait(5)
        loser = executor.submit(second)
        start.wait(timeout=5)
        try:
            wait_for_lock(funds.engine, second_connection.get(timeout=5))
            assert not loser.done()
        finally:
            release.set()
        identity = winner.result(timeout=5)
        assert loser.result(timeout=5) == "rejected"
    with Session(funds.engine) as db:
        assert db.query(ShipmentSettlement).filter_by(invoice_id=funds.invoice).count() == 1
        applications = db.query(SettlementApplication).filter_by(settlement_id=identity).all()
        assert sorted((app.component, app.amount) for app in applications) == [
            ("freight", Decimal("38")), ("goods", Decimal("627"))]
        assert sum(app.amount for app in applications) == 665
        assert db.query(Receipt).filter_by(invoice_id=funds.invoice).count() == 1
        row = db.get(ShipmentSettlement, identity)
        assert row.quote["pool_balances"][0]["remaining_amount"] == "412.00"


def test_independent_session_current_reservation_cap_sees_winner_commit(funds):
    with Session(funds.engine) as db:
        rows = [ShipmentSettlement(invoice_id=funds.invoice, sequence=index + 1, settlement_no="CAP-" + uuid4().hex,
            is_final=0, quote={"currency": "USD"}, quote_hash="a"*64, request_key=uuid4().hex,
            request_hash="b"*64, created_by=1) for index in range(2)]
        db.add_all(rows); db.flush(); identities = [row.id for row in rows]; db.commit()
    held, release = threading.Event(), threading.Event()
    connection = queue.Queue()
    start = threading.Barrier(2)
    def reserve(index):
        with Session(funds.engine, autoflush=False) as db:
            if index:
                # Establish an older RR snapshot to prove current locking reads
                # observe the committed reservation after waiting on invoice.
                assert db.query(SettlementApplication).filter_by(receipt_id=funds.receipt).count() == 0
                connection.put(db.scalar(text("SELECT CONNECTION_ID()")))
                start.wait(timeout=5)
            lock_invoice(db, funds)
            receipt = db.scalar(select(Receipt).where(Receipt.id == funds.receipt).with_for_update()
                .execution_options(populate_existing=True))
            row = db.get(ShipmentSettlement, identities[index])
            if index:
                with pytest.raises(ValueError, match="其他结算占用"):
                    shipments.application(db, row, receipt, "goods", Decimal("700"), Decimal("0"))
                db.rollback()
                return "rejected"
            shipments.application(db, row, receipt, "goods", Decimal("700"), Decimal("0"))
            held.set(); assert release.wait(10); db.commit()
            return "reserved"
    with ThreadPoolExecutor(max_workers=2) as executor:
        winner = executor.submit(reserve, 0); assert held.wait(5)
        loser = executor.submit(reserve, 1); start.wait(timeout=5)
        try:
            wait_for_lock(funds.engine, connection.get(timeout=5)); assert not loser.done()
        finally:
            release.set()
        assert winner.result(timeout=5) == "reserved"
        assert loser.result(timeout=5) == "rejected"
    with Session(funds.engine) as db:
        applications = db.query(SettlementApplication).filter_by(receipt_id=funds.receipt).all()
        assert len(applications) == 1 and applications[0].amount == 700


def test_cancel_release_purpose_correction_and_original_result_replay(funds):
    with Session(funds.engine, autoflush=False) as db:
        invoice = lock_invoice(db, funds)
        draft = ShipmentQuote(items=[{"invoice_item_id": funds.item, "quantity": 3}], freight_amount="38")
        quote = shipments.build_quote(db, invoice, draft, funds.evidence, current=True)
        body = body_for(funds, quote)
        row = shipments._create_verified(db, invoice, body, USER, funds.evidence, None)
        identity, frozen = row.id, deepcopy(row.quote)
        original = db.get(Receipt, funds.receipt)
        facts = (original.amount, original.bank_charge, original.collection_date, original.xiaoman_receipt_id,
            original.xiaoman_order_id, deepcopy(original.attachment_ids))
        db.commit()
    with Session(funds.engine, autoflush=False) as db:
        invoice = lock_invoice(db, funds)
        row, graph = shipment_state_service._capture(db, invoice, identity, "cancel")
        shipments._change_state_verified(db, row, USER, "cancel", row.version, "Change shipment intent", graph)
        db.flush(); db.commit()
    with Session(funds.engine, autoflush=False) as db:
        invoice = lock_invoice(db, funds)
        receipt = db.scalar(select(Receipt).where(Receipt.id == funds.receipt).with_for_update())
        purpose_service.apply(db, receipt, invoice, PresalePurposeUpdate(version=receipt.version,
            purpose="presale_deposit", reason="Correct original intent"), 1)
        db.commit()
    with Session(funds.engine, autoflush=False) as db:
        invoice = lock_invoice(db, funds)
        previous = db.get(ShipmentSettlement, identity)
        shipment_create_service._replay(db, invoice, previous, invoice.id, body, USER)
        assert previous.quote == frozen
        assert all(app.status == "released" for app in db.query(SettlementApplication).filter_by(settlement_id=identity))
        draft = ShipmentQuote(items=[{"invoice_item_id": funds.item, "quantity": 3}], is_final=True)
        final_quote = shipments.build_quote(db, invoice, draft, funds.evidence, current=True)
        assert final_quote["deposit_applied"] == "627.00" and final_quote["new_payment_due"] == "0.00"
        new_body = body_for(funds, final_quote, freight="0", final=True)
        row = shipments._create_verified(db, invoice, new_body, USER, funds.evidence, None)
        db.commit(); replacement = row.id
    with Session(funds.engine, autoflush=False) as db:
        invoice = lock_invoice(db, funds)
        previous = db.get(ShipmentSettlement, identity)
        shipment_create_service._replay(db, invoice, previous, invoice.id, body, USER)
        assert previous.quote == frozen
        current = db.get(ShipmentSettlement, replacement)
        summary = shipments.funding_balance(db, current, current=True)
        assert Decimal(summary["remaining_amount"]) == 0 and summary["funding_version"] == 2
        receipt = db.get(Receipt, funds.receipt)
        assert (receipt.amount, receipt.bank_charge, receipt.collection_date, receipt.xiaoman_receipt_id,
            receipt.xiaoman_order_id, receipt.attachment_ids) == facts
        assert receipt.purpose == "presale_deposit"
        live = db.query(SettlementApplication).filter(SettlementApplication.receipt_id == receipt.id,
            SettlementApplication.status != "released").all()
        assert sum(app.amount for app in live) == 627
        assert db.query(Receipt).filter_by(invoice_id=funds.invoice).count() == 1
        assert db.query(ReceiptLog).filter_by(receipt_id=receipt.id, action="purpose_changed").count() == 1


def test_legacy_cancel_correction_allows_v2_state_and_strict_original_replay(funds):
    with Session(funds.engine, autoflush=False) as db:
        invoice = lock_invoice(db, funds)
        receipt = db.get(Receipt, funds.receipt)
        receipt.amount = Decimal("200"); receipt.purpose = "presale_deposit"
        funds.evidence["receipt"]["rows"][0]["amount"] = "200.00"
        quote = {"currency": "USD", "goods_payment_due": "427.00", "freight_amount": "0.00",
            "goods_payment_charge": "0.00", "new_payment_due": "427.00", "deposit_applied": "200.00",
            "deposit_charge_applied": "0.00", "deposit_receipt_id": receipt.id}
        body = body_for(funds, {"quote_hash": "a"*64}, freight="0")
        legacy = ShipmentSettlement(invoice_id=invoice.id, sequence=1, settlement_no="V1-" + uuid4().hex,
            is_final=1, quote=quote, quote_hash=body.quote_hash, request_key=body.request_key,
            request_hash=shipments.digest(body.model_dump(mode="json", exclude={"is_final"})), created_by=1)
        db.add(legacy); db.flush()
        shipments.application(db, legacy, receipt, "deposit", Decimal("200"), Decimal("0"))
        db.add(SettlementItem(settlement_id=legacy.id, invoice_item_id=funds.item,
            quantity=3, line_amount=627, snapshot={}))
        identity, frozen = legacy.id, deepcopy(legacy.quote)
        facts = (receipt.amount, receipt.bank_charge, receipt.collection_date, receipt.xiaoman_receipt_id,
            receipt.xiaoman_order_id, deepcopy(receipt.attachment_ids))
        db.commit()
    with Session(funds.engine, autoflush=False) as db:
        invoice = lock_invoice(db, funds)
        legacy, graph = shipment_state_service._capture(db, invoice, identity, "cancel")
        shipments._change_state_verified(db, legacy, USER, "cancel", legacy.version, "Cancel legacy intent", graph)
        db.flush(); db.commit()
    with Session(funds.engine, autoflush=False) as db:
        invoice = lock_invoice(db, funds)
        receipt = db.scalar(select(Receipt).where(Receipt.id == funds.receipt).with_for_update())
        purpose_service.apply(db, receipt, invoice, PresalePurposeUpdate(version=receipt.version,
            purpose="presale_advance", reason="Correct legacy deposit intent"), 1)
        db.commit()
    with Session(funds.engine, autoflush=False) as db:
        invoice = lock_invoice(db, funds)
        legacy = db.get(ShipmentSettlement, identity)
        shipment_create_service._replay(db, invoice, legacy, invoice.id, body, USER)
        draft = ShipmentQuote(items=[{"invoice_item_id": funds.item, "quantity": 3}])
        quote = shipments.build_quote(db, invoice, draft, funds.evidence, current=True)
        assert quote["funding_version"] == 2 and quote["advance_applied"] == "200.00"
        current = shipments._create_verified(db, invoice, body_for(funds, quote, freight="0"), USER,
            funds.evidence, None)
        replacement = current.id
        db.commit()
    for command in ("pause", "resume", "cancel"):
        with Session(funds.engine, autoflush=False) as db:
            invoice = lock_invoice(db, funds)
            current, graph = shipment_state_service._capture(db, invoice, replacement, command)
            shipments._change_state_verified(db, current, USER, command, current.version,
                "Change replacement intent", graph)
            db.flush(); db.commit()
    with Session(funds.engine, autoflush=False) as db:
        invoice = lock_invoice(db, funds)
        legacy = db.get(ShipmentSettlement, identity)
        shipment_create_service._replay(db, invoice, legacy, invoice.id, body, USER)
        assert legacy.quote == frozen
        receipt = db.get(Receipt, funds.receipt)
        assert (receipt.amount, receipt.bank_charge, receipt.collection_date, receipt.xiaoman_receipt_id,
            receipt.xiaoman_order_id, receipt.attachment_ids) == facts
        assert receipt.purpose == "presale_advance"
        applications = db.query(SettlementApplication).filter_by(receipt_id=receipt.id).all()
        assert len(applications) == 2 and all(app.status == "released" for app in applications)
        assert db.get(ShipmentSettlement, replacement).state == "cancelled"
        old_app = next(app for app in applications if app.settlement_id == identity)
        old_app.amount = Decimal("199"); db.commit()
    with Session(funds.engine, autoflush=False) as db:
        invoice = lock_invoice(db, funds)
        with pytest.raises(ValueError, match="历史已释放预付款"):
            shipment_state_service._capture(db, invoice, replacement, "pause")
        with pytest.raises(HTTPException) as rejected:
            shipment_create_service._replay(db, invoice, db.get(ShipmentSettlement, identity), invoice.id, body, USER)
        assert rejected.value.status_code == 409
