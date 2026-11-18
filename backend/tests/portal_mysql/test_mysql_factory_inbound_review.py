"""Exercise migration and concurrent uniqueness on a test-owned MySQL process."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from threading import Barrier

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.commerce_transition import service as transition
from app.commerce_transition.models import PlatformPolicy, ResourceScope
from app.core.config import get_settings
from app.factory_inbound.batch_models import Batch
from app.factory_inbound.linked_purchase import LinkedPurchaseBatch, LinkedPurchaseLine, build_purchase_order
from app.factory_inbound.models import Alias, LineType, Note
from app.factory_inbound.okki_transport import PURCHASE_PATH
from app.factory_inbound.recognition_service import queue_values
from app.factory_inbound.service import _next_number
from app.factory_inbound.sync_service import _dispatch, _new_attempt, initialize_batch


def test_review_migration_and_concurrent_numbering(mysql_engine, monkeypatch):
    directory = Path(__file__).resolve().parents[2] / "alembic/versions"
    for revision in ("274_factory_inbound_review", "275_factory_inbound_batch"):
        spec = spec_from_file_location(revision, directory / (revision + ".py"))
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with mysql_engine.begin() as conn:
            conn.exec_driver_sql("SET time_zone = '+08:00'")
            migration.op = Operations(MigrationContext.configure(conn))
            migration.upgrade()

    start = Barrier(2)
    today = date(2026, 11, 18)

    def create(actor):
        with Session(mysql_engine) as db:
            start.wait(timeout=10)
            row = Note(inbound_no=_next_number(db, today), factory_code="fixture", scan_path="synthetic.jpg",
                       created_by=actor, **queue_values())
            db.add(row)
            db.flush()
            result = row.id, row.inbound_no
            db.commit()
            return result

    with ThreadPoolExecutor(2) as pool:
        notes = list(pool.map(create, [1, 2]))
    assert {number for _, number in notes} == {"FI20261118-001", "FI20261118-002"}

    with Session(mysql_engine) as db:
        assert {row.code for row in db.scalars(select(LineType))} >= {"inbound", "crossed_out", "unclear"}
        assert db.scalar(select(Alias.target).where(Alias.kind == "color", Alias.factory_term == "GC")) == "Cookies Cream"

    def set_number(note):
        with Session(mysql_engine) as db:
            row = db.get(Note, note[0])
            row.delivery_no = "7085384"
            start.wait(timeout=10)
            try:
                db.commit()
                return row.id
            except IntegrityError:
                db.rollback()
                return None

    with ThreadPoolExecutor(2) as pool:
        confirmed = list(pool.map(set_number, notes))
    assert confirmed.count(None) == 1
    winner = next(value for value in confirmed if value is not None)
    loser = next(note_id for note_id, _ in notes if note_id != winner)
    with Session(mysql_engine) as db:
        db.get(Note, winner).status = "voided"
        db.commit()
        db.get(Note, loser).delivery_no = "7085384"
        db.commit()
        assert db.get(Note, loser).delivery_key == "fixture:7085384"

    def claim_same_remote(index):
        with Session(mysql_engine) as db:
            row = Batch(note_id=notes[index][0], batch_no=f"FI-FIXTURE-{index}",
                        idempotency_key=f"batch-key-{index}", confirmed_by=1, request_snapshot={}, plan_snapshot=[],
                        xiaoman_inbound_id=710487, xiaoman_serial_id="CGRK710487", sync_status="synced")
            db.add(row)
            start.wait(timeout=10)
            try:
                db.commit()
                return row.id
            except IntegrityError:
                db.rollback()
                return None

    with ThreadPoolExecutor(2) as pool:
        bindings = list(pool.map(claim_same_remote, [0, 1]))
    assert bindings.count(None) == 1

    monkeypatch.setattr(get_settings(), "FACTORY_INBOUND_SYNC_ENABLED", True)
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "legacy")
    with mysql_engine.begin() as conn:
        PlatformPolicy.__table__.create(conn)
        ResourceScope.__table__.create(conn)
        conn.execute(PlatformPolicy.__table__.insert().values(id=1, phase="legacy_only"))

    linked = LinkedPurchaseBatch(
        purchase_order_no="MOCK-PO", inbound_serial_id="MOCK-RECEIPT", supplier_id=123, warehouse_id=124,
        handler_id=125, purchasing_status_id=126, business_date=today, remark="concurrency test",
        lines=(LinkedPurchaseLine(600, 601, 1, 5),),
    )
    with Session(mysql_engine) as db:
        batch = Batch(note_id=loser, batch_no="MOCK-BATCH", idempotency_key="mock-batch", confirmed_by=1, plan_snapshot=[])
        initialize_batch(batch, linked, operator_name="Fixture")
        attempt = _new_attempt(batch, build_purchase_order(linked))
        db.add(batch)
        db.flush()
        batch_id = batch.id
        db.commit()

    posts = []
    senders = Barrier(2)

    class MockTransport:
        def __init__(self, *, before_send):
            self.before_send = before_send

        def create_purchase(self, body):
            senders.wait(timeout=10)
            self.before_send(f"{PURCHASE_PATH}/push", body)
            with Session(mysql_engine) as observer:
                # The business POST must not hold the global commerce row lock.
                observer.connection().exec_driver_sql("SET SESSION innodb_lock_wait_timeout = 2")
                transition.lock_policy(observer)
                saved = observer.get(Batch, batch_id)
                assert saved.sync_checkpoint["attempt"]["dispatch_started"]
            posts.append(body)
            return 881

    def dispatch(_):
        with Session(mysql_engine) as db:
            _dispatch(db, batch_id, "purchase", attempt, MockTransport)

    with ThreadPoolExecutor(2) as pool:
        list(pool.map(dispatch, [0, 1]))
    assert posts == [build_purchase_order(linked)]
    with Session(mysql_engine) as db:
        saved = db.get(Batch, batch_id).sync_checkpoint["attempt"]
        assert saved["remote_id"] == 881 and saved["token"] == attempt["token"]
