"""Exercise B-track admission and linking through the existing feed fixtures."""
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from app.alibaba_feed.models import AlibabaFeedItem, AlibabaFeedLink, AlibabaFeedPilot, AlibabaFeedSource
from app.alibaba_feed import pilot_service
from app.alibaba_feed.worker import process_next_batch
from app.auth.models import ArkPermission, ArkRolePermission
from app.client_desk import private_scope
from app.client_desk.models import ClientDeskUnlinkedReview, ClientDeskUnlinkedRun, ClientDeskUnlinkedThread
from app.client_desk.unlinked import service, worker
from tests.test_alibaba_feed_auth import feed  # noqa: F401
from tests.test_alibaba_feed_business import business  # noqa: F401
from tests.test_alibaba_feed_pilot import collector, jwt, payload, pilot_api, raw  # noqa: F401
from tests.test_client_desk_unlinked import GOOD, USER, _settings


def create_b_tables(db):
    for model in (ClientDeskUnlinkedThread, ClientDeskUnlinkedRun, ClientDeskUnlinkedReview):
        model.__table__.create(db.get_bind())


def test_pilot_can_authorize_b_track_without_a_track_source_flags(pilot_api, monkeypatch):
    client, db, issued, draft, _, _ = pilot_api
    create_b_tables(db)
    monkeypatch.setattr(service, "get_settings", _settings)
    monkeypatch.setattr(pilot_service, "get_settings", _settings)
    monkeypatch.setattr(worker, "get_settings", _settings)
    monkeypatch.setattr(worker, "prepare_text_chat", lambda *args, **kwargs: SimpleNamespace(
        provider=SimpleNamespace(id=7), preset=SimpleNamespace(system_prompt=None),
    ))
    monkeypatch.setattr(worker, "chat", lambda *args, **kwargs: {
        "content": json.dumps({**GOOD, "cites": ["M-1"]}), "finish_reason": "stop",
    })

    def missing_okki(db, user):
        raise HTTPException(409, {"code": "OKKI_BINDING_REQUIRED"})

    monkeypatch.setattr(private_scope, "list_private_companies", missing_okki)
    auth = jwt(99)
    assert client.put("/pilot", headers=auth, json=draft).status_code == 200
    activation = {"enabled": True, "expected_version": 2, "consent_confirmed": True}
    assert client.post("/pilot/activation", headers=auth, json=activation).status_code == 200
    detail = payload()
    detail["records"][0]["assignee_name"] = detail["by_assignee"][0]["assignee_name"] = draft["owner_alias"]
    assert client.post("/v1/batches", headers=collector(issued), content=raw(detail)).status_code == 202
    assert process_next_batch(db, pilot_only=True)
    assert worker._pilot_scope(db) is None
    requested = {"enabled": True, "expected_version": 3, "unlinked_ai_allowed": True}
    assert client.post("/pilot/activation", headers=auth, json=requested).status_code == 422

    enrolled = client.post("/pilot/activation", headers=auth, json={**requested, "consent_confirmed": True})
    assert enrolled.status_code == 200
    data = enrolled.json()["data"]
    assert data["unlinked_ai_allowed"]
    assert not data["source"]["private_feed_enabled"] and not data["source"]["ai_egress_allowed"]
    assert service.list_threads(db, USER)["total"] == 1
    [(run_id, token)] = worker._claim(db, worker.beijing_now(), 1)
    assert worker.analyze_run(db, run_id, token).status == "succeeded"
    assert service.list_threads(db, USER)["items"][0]["run"]["cites"] == ["M-1"]

    revoked = client.post("/pilot/activation", headers=auth, json={
        "enabled": True, "expected_version": data["version"], "unlinked_ai_allowed": False,
    })
    assert revoked.status_code == 200 and not revoked.json()["data"]["unlinked_ai_allowed"]
    assert worker._pilot_scope(db) is None
    with pytest.raises(HTTPException) as exc:
        service.list_threads(db, USER)
    assert exc.value.status_code == 403
    assert client.get("/business/records", headers=jwt(1)).json()["data"]["total"] == 1

    reenabled = client.post("/pilot/activation", headers=auth, json={
        "enabled": True, "expected_version": revoked.json()["data"]["version"],
        "unlinked_ai_allowed": True, "consent_confirmed": True,
    })
    assert reenabled.status_code == 200
    card = service.list_threads(db, USER)["items"][0]
    assert card["run"] is None and card["analysis_stale"]


@pytest.fixture
def authorized_track(business, monkeypatch):
    client, db, headers, _, _ = business
    create_b_tables(db)
    monkeypatch.setattr(service, "get_settings", _settings)
    pilot = db.get(AlibabaFeedPilot, 1)
    pilot.unlinked_ai_allowed = True
    db.commit()
    worker.sync_threads(db, 1, pilot.source_id)
    db.commit()
    thread = db.scalars(select(ClientDeskUnlinkedThread)).one()
    return client, db, headers, thread.id, pilot.source_id


def test_role_revocation_blocks_b_track_access_and_worker(authorized_track):
    client, db, headers, thread_id, _ = authorized_track
    old_token = headers()
    assert client.get("/business/records", headers=old_token).status_code == 200
    permission = db.query(ArkPermission).filter_by(code="client_desk:read").one()
    db.query(ArkRolePermission).filter_by(permission_id=permission.id).delete()
    db.commit()
    assert client.get("/business/records", headers=old_token).status_code == 403
    assert worker._pilot_scope(db) is None
    with pytest.raises(HTTPException) as exc:
        service.list_threads(db, USER)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        service.handled(db, USER, thread_id)
    assert exc.value.status_code == 403


def test_can_rebind_same_customer_and_replay_a_live_binding(authorized_track):
    client, db, headers, thread_id, _ = authorized_track
    first = service.bind(db, USER, thread_id, 101)["link"]
    assert service.bind(db, USER, thread_id, 101)["link"] == {**first, "replayed": True}
    deletion = client.delete(
        f"/business/links/{first['id']}?expected_version={first['version']}", headers=headers(),
    )
    assert deletion.status_code == 200
    assert db.get(ClientDeskUnlinkedThread, thread_id).status == "active"
    assert service.list_threads(db, USER)["items"][0]["id"] == thread_id
    second = service.bind(db, USER, thread_id, 101)["link"]
    assert second["id"] != first["id"] and not second["replayed"]
    assert db.get(ClientDeskUnlinkedThread, thread_id).status == "linked"


def test_link_and_thread_state_rollback_together(authorized_track):
    _, db, _, thread_id, _ = authorized_track

    def fail_thread_update(connection, cursor, statement, *args):
        if statement.startswith("UPDATE ark_client_desk_unlinked_threads "):
            raise SQLAlchemyError("simulated thread update failure")

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", fail_thread_update)
    try:
        with pytest.raises(SQLAlchemyError):
            service.bind(db, USER, thread_id, 101)
        db.rollback()
    finally:
        event.remove(engine, "before_cursor_execute", fail_thread_update)
    assert db.scalars(select(AlibabaFeedLink)).all() == []
    assert db.get(ClientDeskUnlinkedThread, thread_id).status == "active"


def test_migration_refuses_to_drop_a_review_without_threads_or_runs():
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text

    path = Path(__file__).resolve().parents[1] / "alembic/versions/282_client_desk_unlinked.py"
    spec = spec_from_file_location("unlinked_migration", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        conn.execute(text("CREATE TABLE ark_users (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO ark_users VALUES (1)"))
        conn.execute(text("CREATE TABLE ark_alibaba_feed_pilot (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO ark_alibaba_feed_pilot VALUES (1)"))
        migration.upgrade()
        assert conn.execute(text("SELECT unlinked_ai_allowed FROM ark_alibaba_feed_pilot")).scalar() == 0
        conn.execute(text(
            "INSERT INTO ark_client_desk_unlinked_reviews "
            "(id, user_id, week_start_date, window_start, window_end, created_at, updated_at, overview_md) "
            "VALUES (1, 1, '2026-11-16', '2026-11-16', '2026-11-23', '2026-11-25', '2026-11-25', 'Report')"
        ))
        with pytest.raises(RuntimeError, match="B-track data exists"):
            migration.downgrade()
        assert conn.execute(text("SELECT overview_md FROM ark_client_desk_unlinked_reviews")).scalar() == "Report"
        conn.execute(text("DELETE FROM ark_client_desk_unlinked_reviews"))
        migration.downgrade()
        assert not inspect(conn).has_table("ark_client_desk_unlinked_reviews")
        assert [column["name"] for column in inspect(conn).get_columns("ark_alibaba_feed_pilot")] == ["id"]
    engine.dispose()


def test_in_flight_manual_run_rechecks_write_permission(authorized_track, monkeypatch):
    _, db, _, thread_id, _ = authorized_track
    monkeypatch.setattr(worker, "get_settings", _settings)
    monkeypatch.setattr(worker, "prepare_text_chat", lambda *args, **kwargs: SimpleNamespace(
        provider=SimpleNamespace(id=7), preset=SimpleNamespace(system_prompt=None),
    ))

    def revoke_during_chat(db, **kwargs):
        permission = db.query(ArkPermission).filter_by(code="client_desk:write").one()
        db.query(ArkRolePermission).filter_by(permission_id=permission.id).delete()
        db.commit()
        return {"content": json.dumps(GOOD), "finish_reason": "stop"}

    monkeypatch.setattr(worker, "chat", revoke_during_chat)
    assert service.request_analysis(db, USER, thread_id)["status"] == "queued"
    [(run_id, token)] = worker._claim(db, worker.beijing_now(), 1)
    run = worker.analyze_run(db, run_id, token)
    assert run.status == "discarded_stale" and run.one_line_summary is None
    assert worker._pilot_scope(db) is not None


def test_new_collection_generation_does_not_reuse_an_old_handled_watermark(authorized_track):
    _, db, _, thread_id, source_id = authorized_track
    service.handled(db, USER, thread_id)
    source = db.get(AlibabaFeedSource, source_id)
    old = db.get(AlibabaFeedItem, 1)
    source.collection_generation += 1
    new_item = AlibabaFeedItem(
        batch_id=old.batch_id, record_index=1, source_account_uid=old.source_account_uid,
        collection_generation=source.collection_generation, record_type=old.record_type, inquiry_id=old.inquiry_id,
        observed_at=old.observed_at, snapshot_hash="new", snapshot={**old.snapshot, "messages": old.snapshot["messages"][:1]},
        outcome=old.outcome, is_current=True, window_result=old.window_result, issues=old.issues,
    )
    db.add(new_item)
    db.commit()
    assert old.is_current
    worker.sync_threads(db, 1, source_id)
    db.commit()
    thread = db.get(ClientDeskUnlinkedThread, thread_id)
    assert thread.item_id == new_item.id and thread.seen_watermark == [1, 0]
    assert thread.handled_at is None and thread.done_watermark is None
    assert service.list_threads(db, USER)["total"] == 1
