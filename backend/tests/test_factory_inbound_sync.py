from copy import deepcopy
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.commerce_transition import service as transition
from app.core.config import get_settings
from app.core.database import get_db
from app.factory_inbound import matching_service, sync_service, writeback_service
from app.factory_inbound.batch_models import Allocation, Batch
from app.factory_inbound.linked_purchase import LinkedPurchaseBatch, LinkedPurchaseLine, build_purchase_order
from app.factory_inbound.matching_rules import Candidate
from app.factory_inbound.okki_transport import INBOUND_PATH, PURCHASE_PATH, OkkiOutcomeUncertainError
from app.factory_inbound.router import router
from app.factory_inbound.sync_service import (
    SyncConflict, _linked_batch, _new_attempt, advance_batch, batch_status, initialize_batch,
)
from app.stock.models import ProductionAuditLog
from tests.test_factory_inbound_batch_prepare import _approve, reviewed_note
from tests.test_factory_inbound_writeback import build_batch


class MockOkki:
    """Simulate a request committing remotely before the caller receives a response."""

    def __init__(self, db, batch_id):
        self.db = db
        self.batch_id = batch_id
        self.purchase = None
        self.receipt = None
        self.mutations = []
        self.timeouts = set()
        self.uncommitted = set()
        self.hidden = set()
        self.inventory_delta = 0

    def factory(self, *, before_send=None):
        return MockClient(self, before_send)


class MockClient:
    def __init__(self, provider, before_send):
        self.provider = provider
        self.before_send = before_send

    def find_purchase(self, number):
        return (deepcopy(self.provider.purchase) if self.provider.purchase and
                self.provider.purchase["purchase_order_no"] == number and "purchase" not in self.provider.hidden else None)

    def find_inbound(self, number):
        receipt = self.provider.receipt
        if not receipt or receipt["serial_id"] != number:
            return None
        if ("draft" if receipt["status"] == 1 else "complete") in self.provider.hidden:
            return None
        return deepcopy(receipt)

    def _send(self, stage, path, body):
        self.before_send(path, body)
        provider = self.provider
        with Session(provider.db.get_bind()) as observer:
            if provider.batch_id is None:
                batch = observer.scalar(select(Batch).order_by(Batch.id.desc()).limit(1))
            else:
                batch = observer.get(Batch, provider.batch_id)
            checkpoint = batch.sync_checkpoint
        assert checkpoint["stage"] == stage and checkpoint["attempt"]["body"] == body
        assert checkpoint["attempt"]["dispatch_started"]
        provider.mutations.append(stage)
        if stage in provider.uncommitted:
            raise OkkiOutcomeUncertainError("timeout before applying mutation")

    def create_purchase(self, body):
        self._send("purchase", f"{PURCHASE_PATH}/push", body)
        provider = self.provider
        assert provider.purchase is None
        provider.purchase = {
            **body, "purchase_order_id": 802,
            "supplier_info": {"supplier_id": body["supplier_id"]},
            "status_info": {"id": body["status"]},
            "product_list": [{**row, "purchase_order_product_id": 810 + pos, "to_inbound_count": row["count"]}
                             for pos, row in enumerate(reversed(body["product_list"]))],
        }
        if "purchase" in provider.timeouts:
            raise OkkiOutcomeUncertainError("purchase committed before timeout")
        return 802

    def push_inbound(self, body):
        stage = "draft" if body["status"] == 1 else "complete"
        self._send(stage, f"{INBOUND_PATH}/push", body)
        provider = self.provider
        expected = {(row["product_id"], row["sku_id"]): row["purchase_order_product_id"]
                    for row in provider.purchase["product_list"]}
        assert body["record_list"] and len(body["record_list"]) == len(expected)
        for row in body["record_list"]:
            assert row["purchase_order_id"] == 802
            assert expected[row["product_id"], row["sku_id"]] == row["purchase_order_product_id"]
        if stage == "draft":
            assert provider.receipt is None and "inbound_id" not in body
        else:
            assert provider.receipt["status"] == 1 and body["inbound_id"] == 902
            provider.inventory_delta += sum(row["inbound_count"] for row in body["record_list"])
        provider.receipt = {
            **body, "inbound_invoice_id": 902, "delete_flag": 0, "type": 28,
            "record_list": [{**row, "warehouse_id": body["invoice_warehouse_id"]}
                            for row in body["record_list"]],
        }
        if stage in provider.timeouts:
            raise OkkiOutcomeUncertainError(f"{stage} committed before timeout")
        return 902


@pytest.fixture
def scenario(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "FACTORY_INBOUND_SYNC_ENABLED", True)
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "legacy")
    catalog = [Candidate(100 + i, 200 + i, "Fixture", "22", "#4", "20g") for i in (1, 2)]
    monkeypatch.setattr("app.factory_inbound.writeback_service.load_catalog", lambda db: catalog)
    batch, order, items = build_batch(db, quantities=(2, 3))
    initialize_batch(batch, LinkedPurchaseBatch(
        purchase_order_no="FI-FIXTURE-1-P", inbound_serial_id="FI-FIXTURE-1-I",
        supplier_id=33, warehouse_id=12, handler_id=14, purchasing_status_id=15,
        business_date=date(2026, 11, 18), remark="FI-FIXTURE-1",
        lines=(LinkedPurchaseLine(101, 201, 2, 6), LinkedPurchaseLine(102, 202, 3, 7)),
    ), operator_name="Mock operator")
    batch.sync_status = "confirmed"
    db.commit()
    return batch.id, order, items, MockOkki(db, batch.id)


def assert_done(db, batch_id, order, items, mock):
    batch = advance_batch(db, batch_id, transport_factory=mock.factory)
    assert batch_status(batch) == {
        "id": str(batch_id), "batch_no": "FI-FIXTURE-1", "sync_status": "synced", "writeback_status": "done",
        "stage": "done", "message": None, "purchase_order_no": "FI-FIXTURE-1-P",
        "xiaoman_serial_id": "FI-FIXTURE-1-I", "xiaoman_inbound_id": "902", "can_resume": False,
    }
    assert {stage: log["verified_id"] for stage, log in batch.sync_checkpoint["history"].items()} == {
        "purchase": 802, "draft": 902, "complete": 902,
    }
    assert order.status == 2 and [item.received_qty for item in items] == [2, 3]
    assert db.scalar(select(func.count(ProductionAuditLog.id))) == 2
    assert list(db.scalars(select(Allocation.status))) == ["applied", "applied"]
    assert mock.mutations == ["purchase", "draft", "complete"]
    assert mock.inventory_delta == 5
    assert mock.purchase["amount"] == 33
    assert [row["to_inbound_count"] for row in mock.purchase["product_list"]] == [3, 2]


def test_multiple_products_share_one_purchase_one_receipt_and_repeat_is_a_noop(db, scenario):
    assert_done(db, *scenario)
    assert_done(db, *scenario)


@pytest.mark.parametrize("stage", ["purchase", "draft", "complete"])
def test_timeout_reconciles_the_exact_original_before_advancing(db, scenario, stage):
    batch_id, _, items, mock = scenario
    mock.timeouts.add(stage)
    mock.hidden.add(stage)
    batch = advance_batch(db, batch_id, transport_factory=mock.factory)
    assert batch.sync_status == "uncertain" and batch.sync_checkpoint["stage"] == stage
    assert batch.sync_checkpoint["attempt"]["body"]
    assert [item.received_qty for item in items] == [0, 0]
    before = list(mock.mutations)
    advance_batch(db, batch_id, transport_factory=mock.factory)
    assert mock.mutations == before
    mock.hidden.clear()
    assert_done(db, *scenario)


def test_a_still_draft_receipt_cannot_retry_an_ambiguous_completion(db, scenario):
    batch_id, _, items, mock = scenario
    mock.uncommitted.add("complete")
    for _ in range(3):
        batch = advance_batch(db, batch_id, transport_factory=mock.factory)
        assert batch.sync_status == "uncertain" and batch.sync_checkpoint["stage"] == "complete"
    assert mock.mutations == ["purchase", "draft", "complete"]
    assert mock.receipt["status"] == 1 and mock.inventory_delta == 0
    assert [item.received_qty for item in items] == [0, 0]
    with pytest.raises(transition.TransitionError, match="工厂到货"):
        transition.require_no_legacy_physical_inflight(db)
    db.rollback()


def test_wrong_purchase_recovery_cannot_create_an_inbound(db, scenario):
    batch_id, _, _, mock = scenario
    mock.hidden.add("purchase")
    advance_batch(db, batch_id, transport_factory=mock.factory)
    mock.hidden.clear()
    mock.purchase["product_list"][0]["count"] += 1
    batch = advance_batch(db, batch_id, transport_factory=mock.factory)
    assert batch.sync_status == "uncertain" and batch.sync_checkpoint["stage"] == "purchase"
    assert mock.mutations == ["purchase"]


def test_preexisting_order_cannot_be_adopted_without_a_committed_attempt(db, scenario):
    batch_id, _, _, mock = scenario
    mock.purchase = {"purchase_order_no": "FI-FIXTURE-1-P", "purchase_order_id": 802}
    batch = advance_batch(db, batch_id, transport_factory=mock.factory)
    assert batch.sync_status == "blocked" and not batch_status(batch)["can_resume"]
    assert not mock.mutations


def test_writeback_failure_persists_completion_and_only_retries_local_work(db, scenario):
    batch_id, _, items, mock = scenario
    items[1].status = 1
    db.commit()
    batch = advance_batch(db, batch_id, transport_factory=mock.factory)
    assert batch.sync_status == "synced" and batch.writeback_status == "failed"
    assert batch.completion_evidence["inbound_invoice_id"] == 902
    assert [item.received_qty for item in items] == [0, 0]
    items[1].status = 0
    db.commit()
    assert_done(db, *scenario)


def test_disabled_workflow_never_reads_or_posts_to_provider(db, scenario, monkeypatch):
    batch_id, _, _, mock = scenario
    monkeypatch.setattr(get_settings(), "FACTORY_INBOUND_SYNC_ENABLED", False)
    with pytest.raises(SyncConflict, match="尚未开启"):
        advance_batch(db, batch_id, transport_factory=mock.factory)
    assert not mock.mutations


def test_resume_committed_intent_that_never_received_a_send_permit(db, scenario):
    batch_id, _, _, _ = scenario
    batch = db.get(Batch, batch_id)
    linked = batch.purchase_intent
    intent = _new_attempt(batch, build_purchase_order(_linked_batch(linked)))
    db.commit()
    assert_done(db, *scenario)
    saved = db.get(Batch, batch_id).sync_checkpoint["history"]["purchase"]["intent"]
    assert saved["token"] == intent["token"] and saved["dispatch_started"]


def test_changed_okki_tenant_never_uses_the_saved_intent(db, scenario, monkeypatch):
    batch_id, _, _, mock = scenario
    monkeypatch.setattr(get_settings(), "OKKI_CLIENT_ID", "mock-other-tenant")

    def forbid_lookup(*args):
        pytest.fail("Frozen batch cannot read data from another tenant")

    monkeypatch.setattr(MockClient, "find_purchase", forbid_lookup)
    with pytest.raises(SyncConflict, match="租户"):
        advance_batch(db, batch_id, transport_factory=mock.factory)
    assert not mock.mutations


def test_note_preview_submit_and_replay_via_normal_api(db, reviewed_note, monkeypatch):
    note, _, _, items, actor = reviewed_note
    _, body = _approve(db, reviewed_note)
    note_id = note.id
    engine = db.get_bind()
    db.rollback()
    provider = MockOkki(db, None)
    monkeypatch.setattr(get_settings(), "FACTORY_INBOUND_ENABLED", True)
    monkeypatch.setattr(sync_service, "OkkiTransport", provider.factory)
    monkeypatch.setattr(writeback_service, "load_catalog", matching_service.load_catalog)
    app = FastAPI()
    app.include_router(router)

    def session():
        with Session(engine) as db_session:
            yield db_session

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = lambda: actor
    path = f"/notes/{note_id}/batches"
    payload = body.model_dump(mode="json")
    with TestClient(app) as client:
        latest = client.post(path + "/preview", json={"version": body.version, "line_ids": body.line_ids})
        assert latest.status_code == 200 and latest.json()["data"]["preview_digest"] == body.preview_digest
        first = client.post(path, json=payload)
        assert first.status_code == 200, first.text
        completed = first.json()["data"]
        assert completed["sync_status"] == "synced" and completed["writeback_status"] == "done"
        assert client.post(path, json=payload).json()["data"] == completed
        assert client.post(f'{path}/{completed["id"]}/resume').json()["data"] == completed
        assert client.get(path).json()["data"]["items"] == [completed]
    assert provider.mutations == ["purchase", "draft", "complete"]
    db.expire_all()
    assert [item.received_qty for item in items] == [3, 2]
