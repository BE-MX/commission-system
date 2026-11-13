"""Owned MySQL only: followup migrations and real edit/assignment lock races."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, inspect, text
from sqlalchemy.dialects.mysql import INTEGER
from sqlalchemy.orm import Session

from app.auth import models as auth
from app.domestic.models import DomesticCustomer, DomesticCustomerCommission
from app.domestic_decision.models import DecisionEvent
from app.domestic_followup import attachment_service, edit_service, followup_service
from app.domestic_followup import models as followup
from app.domestic_followup.collaboration_access import create_initial_responsibility, lock_customer
from app.domestic_followup.collaboration_models import FollowupCollaborationEvent, FollowupResponsibility, FollowupScope
from app.domestic_followup.collaboration_schemas import CollaborationActionIn
from app.domestic_followup.collaboration_service import apply_action
from app.domestic_followup.collaboration_tasks import ConflictError as CollaborationConflict
from app.domestic_followup.schemas import DirectSaveIn, EditFollowupIn
from app.system.models import SysDict
from tests.domestic_followup_helpers import ALL_PERMS, grant, seed_dicts
from test_mysql_concurrency import wait_for_lock


@pytest.fixture(scope="module")
def followup_db(mysql_engine):
    metadata = MetaData()
    for model in (auth.ArkUser, auth.ArkRole, auth.ArkPermission, auth.ArkRolePermission, auth.ArkUserRole,
                  DomesticCustomer, DomesticCustomerCommission, SysDict, DecisionEvent,
                  followup.DomesticFollowup, followup.DomesticFollowupItem, followup.DomesticFollowupAttachment,
                  followup.DomesticFollowupTask, followup.DomesticFollowupDigest, followup.DomesticFollowupConfig,
                  followup.DomesticCustomerAlias):
        table = model.__table__.to_metadata(metadata)
        if model is auth.ArkUser:
            table.c.id.type = INTEGER(unsigned=True)
    # Published auth DDL uses unsigned user keys; several legacy ORM columns remain generic.
    for table in metadata.tables.values():
        for column in table.c:
            if any(foreign.target_fullname == "ark_users.id" for foreign in column.foreign_keys):
                column.type = INTEGER(unsigned=True)
    for name, column in (
        ("ark_domestic_followup_attachments", "archived_at"),
        ("ark_domestic_followup_digests", "send_claimed_at"),
        ("ark_domestic_followup_tasks", "purpose"),
        *(("ark_domestic_followups", column) for column in (
            "result_code", "obstacles", "evidence_kind", "shared_summary", "effective_progress", "responsibility_version",
        )),
    ):
        table = metadata.tables[name]
        table._columns.remove(table.c[column])
    metadata.create_all(mysql_engine)
    def apply_revision(name):
        migration_file = Path(__file__).resolve().parents[2] / f"alembic/versions/{name}.py"
        spec = spec_from_file_location(name, migration_file)
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with mysql_engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
        return migration

    with Session(mysql_engine) as db:
        seed_dicts(db)
        db.commit()
    migration = apply_revision("249_followup_revisions")
    collaboration = apply_revision("255_followup_collaboration")
    assert {"ark_domestic_followup_revisions", "ark_dom_followup_responsibilities"} <= set(
        inspect(mysql_engine).get_table_names()
    )
    yield mysql_engine
    # Immutable history must block destructive downgrade.
    with mysql_engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        with pytest.raises(RuntimeError, match="history"):
            migration.downgrade()
        collaboration.op = Operations(MigrationContext.configure(connection))
        collaboration.context = SimpleNamespace(is_offline_mode=lambda: False)
        with pytest.raises(RuntimeError, match="collaboration"):
            collaboration.downgrade()


def seed(engine):
    with Session(engine) as db:
        user = auth.ArkUser(username=uuid4().hex, password_hash="test-only", real_name="Test author", is_active=True)
        db.add(user); db.flush()
        customer = DomesticCustomer(shop_name=uuid4().hex, owner_user_id=user.id, created_by=user.id, status=1, balance=0)
        db.add(customer); db.flush()
        row = followup.DomesticFollowup(author_user_id=user.id, customer_id=customer.id, followup_date=date(2026, 11, 1),
                                        raw_text="before", status="confirmed", version=2, request_id=uuid4().hex)
        db.add(row); db.flush()
        draft = followup.DomesticFollowup(author_user_id=user.id, followup_date=date(2026, 11, 1), status="draft", request_id=uuid4().hex)
        attachment = followup.DomesticFollowupAttachment(uploader_user_id=user.id, file_path="synthetic.png", ocr_status="done")
        db.add_all([draft, attachment]); db.flush()
        values = user.id, row.id, draft.id, attachment.id
        db.commit()
        return values


def ctx(user_id):
    return {"sub": str(user_id), "roles": [], "permissions": ["domestic_followup:read", "domestic_followup:write"]}


def command(**changes):
    return EditFollowupIn(version=2, request_id=uuid4().hex, reason="test correction", result_code="有效沟通",
                           followup_date=date(2026, 11, 1), raw_text="after", **changes)


def test_concurrent_edit_waits_and_rejects_stale_snapshot(followup_db):
    engine = followup_db
    user_id, record_id, _, _ = seed(engine)
    started = Queue()
    def second():
        with Session(engine) as db:
            db.get(followup.DomesticFollowup, record_id)  # Prime RR snapshot before first commits.
            started.put(db.scalar(text("SELECT CONNECTION_ID()")))
            with pytest.raises(followup_service.ConflictError):
                edit_service.update(db, ctx(user_id), record_id, command())
    with Session(engine) as first, ThreadPoolExecutor(max_workers=1) as pool:
        customer_id = first.get(followup.DomesticFollowup, record_id).customer_id
        lock_customer(first, customer_id)
        edit_service._record(first, ctx(user_id), record_id, lock=True)
        future = pool.submit(second)
        wait_for_lock(engine, started.get(timeout=3))
        edit_service.update(first, ctx(user_id), record_id, command())
        future.result(timeout=8)
    with Session(engine) as db:
        assert db.query(followup.DomesticFollowupRevision).filter_by(followup_id=record_id).count() == 1
        assert db.get(followup.DomesticFollowup, record_id).version == 3


@pytest.mark.parametrize("edit_first", [True, False])
def test_draft_and_edit_cannot_steal_the_same_unbound_attachment(followup_db, edit_first):
    engine = followup_db
    user_id, record_id, draft_id, attachment_id = seed(engine)
    started = Queue()
    def second():
        with Session(engine) as db:
            started.put(db.scalar(text("SELECT CONNECTION_ID()")))
            with pytest.raises(PermissionError):
                if edit_first:
                    attachment_service.bind(db, user_id, draft_id, [attachment_id])
                else:
                    edit_service.update(db, ctx(user_id), record_id, command(attachment_ids=[attachment_id]))
            db.rollback()
    with Session(engine) as first, ThreadPoolExecutor(max_workers=1) as pool:
        first.query(followup.DomesticFollowupAttachment).filter_by(id=attachment_id).with_for_update().one()
        future = pool.submit(second)
        wait_for_lock(engine, started.get(timeout=3))
        if edit_first:
            edit_service.update(first, ctx(user_id), record_id, command(attachment_ids=[attachment_id]))
        else:
            attachment_service.bind(first, user_id, draft_id, [attachment_id])
            first.commit()
        future.result(timeout=8)
    with Session(engine) as db:
        expected = record_id if edit_first else draft_id
        assert db.get(followup.DomesticFollowupAttachment, attachment_id).followup_id == expected


def test_two_claims_with_stale_snapshots_cannot_both_win(followup_db):
    engine = followup_db
    with Session(engine) as db:
        users = [auth.ArkUser(username=uuid4().hex, password_hash="test-only", real_name=f"Claimant {i}", is_active=True)
                 for i in range(2)]
        db.add_all(users)
        db.flush()
        customer = DomesticCustomer(shop_name=uuid4().hex, created_by=users[0].id, status=1, balance=0)
        db.add(customer)
        db.flush()
        for user in users:
            grant(db, user, *ALL_PERMS)
            db.add(FollowupScope(user_id=user.id, customer_id=customer.id, scope_key=f"c:{customer.id}",
                                 added_by_user_id=user.id))
        db.add(FollowupResponsibility(customer_id=customer.id, status="open", version=1))
        customer_id, first_id, second_id = customer.id, users[0].id, users[1].id
        db.commit()
    started = Queue()

    def claim_second():
        with Session(engine) as db:
            assert db.get(FollowupResponsibility, customer_id).owner_user_id is None
            started.put(db.scalar(text("SELECT CONNECTION_ID()")))
            with pytest.raises(CollaborationConflict):
                apply_action(db, ctx(second_id), customer_id,
                             CollaborationActionIn(action="claim", version=1, idempotency_key="claim-other"))

    with Session(engine) as first, ThreadPoolExecutor(max_workers=1) as pool:
        apply_action(first, ctx(first_id), customer_id,
                     CollaborationActionIn(action="claim", version=1, idempotency_key="claim-winner"))
        future = pool.submit(claim_second)
        wait_for_lock(engine, started.get(timeout=3))
        first.commit()
        future.result(timeout=8)
    with Session(engine) as db:
        assert db.get(FollowupResponsibility, customer_id).owner_user_id == first_id
        assert db.query(FollowupCollaborationEvent).filter_by(customer_id=customer_id, action="claim").count() == 1


def test_waiting_legacy_writer_sees_new_responsibility(followup_db):
    engine = followup_db
    original_id, record_id, _, _ = seed(engine)
    with Session(engine) as db:
        current = auth.ArkUser(username=uuid4().hex, password_hash="test-only", real_name="Incoming", is_active=True)
        db.add(current)
        db.flush()
        grant(db, current, *ALL_PERMS)
        grant(db, db.get(auth.ArkUser, original_id), *ALL_PERMS)
        customer_id, current_id = db.get(followup.DomesticFollowup, record_id).customer_id, current.id
        db.commit()
    started = Queue()

    def old_window_save():
        with Session(engine) as db:
            assert db.get(FollowupResponsibility, customer_id) is None
            started.put(db.scalar(text("SELECT CONNECTION_ID()")))
            with pytest.raises(PermissionError, match="当前跟进安排"):
                followup_service.direct_save(db, ctx(original_id), DirectSaveIn(
                    result_code="有效沟通",
                    request_id="old-window-save", customer_id=customer_id, raw_text="stale legacy write",
                ))

    with Session(engine) as first, ThreadPoolExecutor(max_workers=1) as pool:
        lock_customer(first, customer_id)
        create_initial_responsibility(first, customer_id, current_id)
        future = pool.submit(old_window_save)
        wait_for_lock(engine, started.get(timeout=3))
        first.commit()
        future.result(timeout=8)
    with Session(engine) as db:
        assert db.query(followup.DomesticFollowup).filter_by(request_id="old-window-save").count() == 0
