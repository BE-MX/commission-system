"""Owned loopback MySQL: migration 261, queue admission, leases and task replay."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from queue import Queue
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, inspect, text
from sqlalchemy.dialects.mysql import INTEGER
from sqlalchemy.orm import Session

from app.auth import models as auth
from app.core.time import beijing_now, beijing_today
from app.domestic.models import DomesticCustomer, DomesticCustomerCommission
from app.domestic_decision.models import DecisionEvent
from app.domestic_followup import insight_queue, insight_service, models as followup
from app.domestic_followup.collaboration_models import (
    FollowupCollaborator, FollowupHandoff, FollowupResponsibility, FollowupScope,
)
from app.domestic_followup.insight_models import DomesticFollowupInsight, DomesticFollowupInsightSnapshot
from test_mysql_concurrency import wait_for_lock


@pytest.fixture(scope="module")
def stats_db(mysql_engine):
    metadata = MetaData()
    for model in (auth.ArkUser, auth.ArkRole, auth.ArkPermission, auth.ArkRolePermission, auth.ArkUserRole,
                  DomesticCustomer, DomesticCustomerCommission, followup.DomesticFollowup,
                  followup.DomesticFollowupItem, followup.DomesticFollowupTask, followup.DomesticFollowupConfig,
                  FollowupResponsibility, FollowupCollaborator, FollowupScope, FollowupHandoff, DecisionEvent):
        table = model.__table__.to_metadata(metadata)
        if model is auth.ArkUser:
            table.c.id.type = INTEGER(unsigned=True)
    for table in metadata.tables.values():
        for column in table.c:
            if any(key.target_fullname == "ark_users.id" for key in column.foreign_keys):
                column.type = INTEGER(unsigned=True)
    metadata.create_all(mysql_engine)
    path = Path(__file__).resolve().parents[2] / "alembic/versions/261_followup_insights.py"
    spec = spec_from_file_location("followup_insights_migration", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    with mysql_engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
    inspector = inspect(mysql_engine)
    columns = {row["name"] for row in inspector.get_columns("ark_dom_followup_insights")}
    assert {"evidence_versions", "public_summary", "sample_customer_ids", "task_id"} <= columns
    with Session(mysql_engine) as db:
        insight_queue.lock_admission(db)
        db.commit()
    return mysql_engine


def seed_user(engine):
    with Session(engine) as db:
        user = auth.ArkUser(username=uuid4().hex, password_hash="test-only", real_name="Synthetic", is_active=True)
        db.add(user); db.flush()
        identifier = user.id
        db.commit()
        return identifier


def claims(identifier, manager=True):
    return {"sub": str(identifier), "permissions": ["domestic_followup:read", "domestic_followup:write"]
            + (["domestic_followup:read_all"] if manager else [])}


def test_concurrent_refresh_waits_and_observes_daily_quota(stats_db):
    actor = seed_user(stats_db)
    targets = [seed_user(stats_db) for _ in range(3)]
    with Session(stats_db) as db:
        earlier = DomesticFollowupInsightSnapshot(scope="personal", user_id=targets[0], status="done",
            trigger="manual", period_start=beijing_today(), period_end=beijing_today(),
            requested_by_user_id=actor, request_day=beijing_today())
        db.add(earlier); db.commit()
    started = Queue()
    def competing():
        with Session(stats_db) as db:
            started.put(db.scalar(text("SELECT CONNECTION_ID()")))
            with pytest.raises(ValueError, match="每天"):
                insight_service.refresh(db, claims(actor), user_id=targets[2])
            db.rollback()
    with Session(stats_db) as first, ThreadPoolExecutor(max_workers=1) as executor:
        admitted = insight_service.refresh(first, claims(actor), user_id=targets[1])
        future = executor.submit(competing)
        try:
            wait_for_lock(stats_db, started.get(timeout=3))
            assert not future.done()
            first.commit()
        finally:
            first.rollback()
        future.result(timeout=6)
    with Session(stats_db) as db:
        assert db.query(DomesticFollowupInsightSnapshot).filter_by(
            requested_by_user_id=actor, trigger="manual").count() == 2
        for identifier in admitted["snapshot_ids"]:
            db.get(DomesticFollowupInsightSnapshot, identifier).status = "failed"
        db.commit()


def test_same_target_concurrent_admission_reuses_queue_entry(stats_db):
    actor, other, target = [seed_user(stats_db) for _ in range(3)]
    started = Queue()
    def competing():
        with Session(stats_db) as db:
            started.put(db.scalar(text("SELECT CONNECTION_ID()")))
            result = insight_service.refresh(db, claims(other), user_id=target)
            db.commit()
            return result
    with Session(stats_db) as first, ThreadPoolExecutor(max_workers=1) as executor:
        admitted = insight_service.refresh(first, claims(actor), user_id=target)
        future = executor.submit(competing)
        try:
            wait_for_lock(stats_db, started.get(timeout=3))
            first.commit()
        finally:
            first.rollback()
        second = future.result(timeout=6)
        assert second["started"] is False
        assert second["snapshot_ids"] == admitted["snapshot_ids"][:1]


def test_snapshot_execution_can_only_be_claimed_once(stats_db):
    actor = seed_user(stats_db)
    with Session(stats_db) as db:
        result = insight_service.refresh(db, claims(actor))
        db.commit()
        identifier = result["snapshot_ids"][0]
    with ThreadPoolExecutor(max_workers=2) as executor:
        def claim():
            with Session(stats_db) as db:
                return insight_queue.claim(db, identifier)
        results = list(executor.map(lambda _: claim(), range(2)))
    assert sum(value is not None for value in results) == 1


def test_concurrent_task_creation_is_idempotent_and_replay_does_not_leak(stats_db):
    actor, stranger = seed_user(stats_db), seed_user(stats_db)
    with Session(stats_db) as db:
        customer = DomesticCustomer(shop_name="Synthetic task customer", owner_user_id=actor,
                                    created_by=actor, status=1, balance=0)
        db.add(customer); db.flush()
        record = followup.DomesticFollowup(author_user_id=actor, customer_id=customer.id,
            followup_date=beijing_today(), status="confirmed", version=2, raw_text="Synthetic evidence", request_id=uuid4().hex)
        db.add(record); db.flush()
        snapshot = DomesticFollowupInsightSnapshot(scope="personal", user_id=actor, status="done", trigger="test",
            period_start=beijing_today()-timedelta(days=30), period_end=beijing_today(), generated_at=beijing_now())
        db.add(snapshot); db.flush()
        item = DomesticFollowupInsight(snapshot_id=snapshot.id, category="deal", customer_id=customer.id,
            title="Synthetic quote", body="Synthetic signal", evidence_followup_ids=[record.id],
            evidence_versions={str(record.id): record.version})
        db.add(item); db.flush(); identifier = item.id; db.commit()
    started = Queue()
    def competing():
        with Session(stats_db) as db:
            started.put(db.scalar(text("SELECT CONNECTION_ID()")))
            return insight_service.to_task(db, claims(actor, False), identifier, beijing_today(), "Synthetic plan")
    with Session(stats_db) as lock, ThreadPoolExecutor(max_workers=2) as executor:
        lock.query(DomesticFollowupInsight).filter_by(id=identifier).with_for_update().one()
        futures = [executor.submit(competing) for _ in range(2)]
        try:
            for _ in futures:
                wait_for_lock(stats_db, started.get(timeout=3))
            lock.commit()
        finally:
            lock.rollback()
        results = [future.result(timeout=6) for future in futures]
    assert len({row["task_id"] for row in results}) == 1
    assert sum(row["created"] for row in results) == 1
    with Session(stats_db) as db:
        assert db.query(followup.DomesticFollowupTask).filter_by(source_key=f"insight:{identifier}").count() == 1
        with pytest.raises(PermissionError):
            insight_service.to_task(db, claims(stranger, False), identifier, beijing_today(), "Unauthorized")
