"""Owned MySQL + actual JWT/API locks; supplier observations are synthetic."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
import threading
from uuid import uuid4

import pytest
from sqlalchemy import Column, MetaData, Table, select
from sqlalchemy.orm import Session

from app.invoice import shipment_delivery, settlement_service
from app.invoice.settlement_models import ShipmentSettlement, ShipmentOutbound, SettlementApplication, ReceiptBatch
from app.receipt import remote, service as receipt_service
from app.receipt.models import Receipt, ReceiptLog
from app.invoice.models import Invoice
from test_mysql_shipment_create import (shipment_app, batch_create_app, read_app, receipt_app,
    assembled, boot, authorize, login)  # noqa: F401
from test_mysql_receipt_batch_presale import separate_proof


@pytest.fixture
def credit_app(shipment_app):
    from app.auth.models import ArkAccountUnlockAudit
    c = shipment_app
    metadata = MetaData()
    Table(ArkAccountUnlockAudit.__tablename__, metadata, *(Column(column.name, column.type,
        primary_key=column.primary_key, nullable=column.nullable)
        for column in ArkAccountUnlockAudit.__table__.columns))
    metadata.create_all(c.ctx.engine)
    return c


def create_body(client, c, owner):
    draft = {"items": [{"invoice_item_id": c.item_id, "quantity": 4}],
        "freight_amount": "0", "payment_term": "ship_first"}
    result = client.post(f"/api/invoices/{c.invoice_id}/shipment-quotes", headers=owner, json=draft)
    assert result.status_code == 200, result.text
    return {**draft, "quote_hash": result.json()["data"]["quote_hash"], "request_key": uuid4().hex}


def create(client, c, owner):
    body = create_body(client, c, owner)
    result = client.post(f"/api/invoices/{c.invoice_id}/shipment-settlements", headers=owner, json=body)
    assert result.status_code == 200, result.text
    return result.json()["data"], body


def payment_body(client, c, owner, identity, amount="20"):
    result = client.get(f"/api/receipts/order-balance/{c.invoice_id}", headers=owner)
    assert result.status_code == 200, result.text
    candidate = next(row for row in result.json()["data"]["payment_settlements"]
        if row["settlement_id"] == identity)
    return {"request_key": uuid4().hex, "amount": amount, "bank_charge": "0",
        "collection_date": "2026-10-06", "payment_type": "T/T", "remark": "Credit batch payment",
        "attachment_ids": [c.proofs["unbound"]], "allocations": [{
            "invoice_id": c.invoice_id, "settlement_id": identity, "amount": amount,
            "bank_charge": "0", "purpose": "ordinary", "balance_version": candidate["version"]}]}


def credentials(client, c):
    root = login(client, c, c.root_name)
    authorize(client, c, root)
    return login(client, c, c.owner_name)


def test_api_credit_queues_once_without_money_and_term_cannot_be_replayed(credit_app, monkeypatch):
    c = credit_app
    with c.app.client() as client:
        owner = credentials(client, c)
        result, body = create(client, c, owner)
        assert result["payment_term"] == "ship_first"
        assert Decimal(result["balance"]["outstanding_amount"]) == 44
        monkeypatch.setattr(shipment_delivery, "require_delivery", lambda: None)
        monkeypatch.setattr(shipment_delivery, "_live_candidate", lambda *args, **kwargs: {
            "serial_id": result["settlement_no"], "status": 1, "record_list": [{
                "order_id": 100, "order_record_id": 101, "product_id": 1, "sku_id": 2, "outbound_count": 4}]})
        with Session(c.ctx.engine) as db:
            identity = shipment_delivery.queue_ready(db, result["id"])
            assert identity and db.get(ShipmentSettlement, result["id"]).state == "outbound_pending"
            assert shipment_delivery.queue_ready(db, result["id"]) is None
            assert db.query(ShipmentOutbound).filter_by(invoice_id=c.invoice_id).count() == 1
            assert db.query(ReceiptBatch).filter_by(request_key=body["request_key"]).count() == 0
        replay = client.post(f"/api/invoices/{c.invoice_id}/shipment-settlements", headers=owner, json=body)
        assert replay.status_code == 200 and replay.json()["data"]["id"] == result["id"]
        changed = client.post(f"/api/invoices/{c.invoice_id}/shipment-settlements",
            headers=owner, json={**body, "payment_term": "pay_first"})
        assert changed.status_code == 409
        assert c.calls == []


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_credit_creation_keeps_one_batch(credit_app, monkeypatch, same_key):
    c = credit_app
    with c.app.client() as client:
        owner = credentials(client, c)
        first = create_body(client, c, owner)
        second = deepcopy(first)
        if not same_key:
            second["request_key"] = uuid4().hex
        original = remote.order_snapshot
        gate = threading.Barrier(2)
        def together(*args):
            gate.wait(timeout=15)
            return original(*args)
        monkeypatch.setattr(remote, "order_snapshot", together)
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(client.post, f"/api/invoices/{c.invoice_id}/shipment-settlements",
                headers=owner, json=body) for body in (first, second)]
            results = [job.result(timeout=30) for job in jobs]
        assert sorted(response.status_code for response in results) == ([200, 200] if same_key else [200, 409]), [r.text for r in results]
        with Session(c.ctx.engine) as db:
            rows = db.query(ShipmentSettlement).filter_by(invoice_id=c.invoice_id).all()
            assert len(rows) == 1
            assert db.query(SettlementApplication).filter_by(settlement_id=rows[0].id).count() == 0
        assert c.calls == []


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_postshipment_payments_cannot_overallocate_or_recall_goods(credit_app, monkeypatch, same_key):
    c = credit_app
    with c.app.client() as client:
        owner = credentials(client, c)
        result, _ = create(client, c, owner)
        with Session(c.ctx.engine) as db:
            # Financial state fixture: no real goods or supplier writes in this suite.
            row = db.get(ShipmentSettlement, result["id"]); row.state = "shipped"; db.commit()
        first = payment_body(client, c, owner, result["id"], "30")
        second = deepcopy(first)
        if not same_key:
            second.update(request_key=uuid4().hex, attachment_ids=[separate_proof(c)])
        original = remote.order_snapshot
        gate = threading.Barrier(2)
        def together(*args):
            gate.wait(timeout=15)
            return original(*args)
        monkeypatch.setattr(remote, "order_snapshot", together)
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(client.post, "/api/receipts/batches", headers=owner, json=body)
                for body in (first, second)]
            results = [job.result(timeout=30) for job in jobs]
        assert sorted(response.status_code for response in results) == ([200, 200] if same_key else [200, 409]), [r.text for r in results]
        with Session(c.ctx.engine) as db:
            row = db.get(ShipmentSettlement, result["id"])
            assert row.state == "shipped"
            assert db.query(ReceiptBatch).filter_by(request_key=first["request_key"]).count() == 1
            apps = db.scalars(select(SettlementApplication).where(SettlementApplication.settlement_id == row.id)).all()
            assert len(apps) == 1 and apps[0].amount == 30
            funds = settlement_service.funding_balance(db, row)
            assert Decimal(funds["outstanding_amount"]) == 44 and Decimal(funds["remaining_amount"]) == 14
            receipt = db.get(Receipt, apps[0].receipt_id)
            assert receipt.batch_id and receipt.purpose == "presale_goods"
        assert c.calls == []


def test_current_credit_fence_sees_effective_fact_after_repeatable_read_snapshot(credit_app):
    c = credit_app
    with c.app.client() as client:
        owner = credentials(client, c)
        result, _ = create(client, c, owner)
        with Session(c.ctx.engine) as db:
            db.get(ShipmentSettlement, result["id"]).state = "shipped"; db.commit()
        body = payment_body(client, c, owner, result["id"])
        response = client.post("/api/receipts/batches", headers=owner, json=body)
        assert response.status_code == 200, response.text
        with Session(c.ctx.engine) as reader:
            row = reader.get(ShipmentSettlement, result["id"])
            app = reader.scalar(select(SettlementApplication).where(SettlementApplication.settlement_id == row.id))
            receipt_id = app.receipt_id
            assert reader.query(ReceiptLog).filter_by(receipt_id=receipt_id, action="credit_effective").count() == 0
            with Session(c.ctx.engine) as writer:
                receipt = writer.get(Receipt, receipt_id)
                receipt.sync_status = "synced"; receipt.collect_status = 0
                receipt.xiaoman_receipt_id = str(700000000 + receipt_id); receipt.last_error = None
                receipt_service.log(writer, receipt, "credit_effective",
                    "Synthetic prior effective fact", c.ctx.actor)
                writer.commit()
            # A stale ordinary read still misses the fact. The invoice/current
            # funding fence must see it and reject revoked cash as ordinary debt.
            assert reader.query(ReceiptLog).filter_by(receipt_id=receipt_id, action="credit_effective").count() == 0
            reader.scalar(select(Invoice).where(Invoice.id == c.invoice_id).with_for_update())
            assert not shipment_delivery._dispatchable(reader, row, current=True)
            reader.rollback()
        assert c.calls == []
