from datetime import datetime, timezone
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.core import time as business_time
from app.core.time import beijing_today
from app.factory_inbound import jobs, recognition_service, sync_service
from app.factory_inbound.batch_models import Batch
from app.factory_inbound.models import Alias, Line, LineType, Note
from app.factory_inbound.router import ADMIN, READ, WRITE, router
from app.invoice.models import Invoice
from app.invoice import product_service


@pytest.fixture
def system(engine, tmp_path, monkeypatch):
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(get_settings(), "FACTORY_INBOUND_ENABLED", True)
    monkeypatch.setattr(get_settings(), "FACTORY_INBOUND_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(product_service, "_schema", lambda: "lsordertest")
    monkeypatch.setattr(recognition_service, "SessionLocal", factory)
    queue = []
    monkeypatch.setattr(jobs, "submit", lambda *args: queue.append(args))
    with engine.begin() as db:
        db.exec_driver_sql("""CREATE TABLE lsordertest.okki_products (
            product_id INTEGER PRIMARY KEY, product_name VARCHAR, size VARCHAR, color VARCHAR,
            unit VARCHAR, disable_flag INTEGER
        )""")
        db.exec_driver_sql("""CREATE TABLE lsordertest.okki_product_skus (
            sku_id INTEGER PRIMARY KEY, product_id INTEGER, disable_flag INTEGER
        )""")
        db.exec_driver_sql("INSERT INTO lsordertest.okki_products VALUES (1, 'Super Genius Weft', '22', '#8TP8/18', '20g', 0)")
        db.exec_driver_sql("INSERT INTO lsordertest.okki_product_skus VALUES (71, 1, 0)")
    with factory.begin() as db:
        db.add(LineType(code="inbound", label="到货", is_inbound=True))
        db.add(LineType(code="sample", label="色样", is_inbound=False))
        db.add(Alias(kind="process", factory_term="PU", target="Genius Weft", source="seed"))
    app = FastAPI()
    app.include_router(router, prefix="/api/factory-inbound")

    def session():
        with factory() as db:
            yield db

    actor = {"sub": "1", "permissions": [WRITE], "roles": []}
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = lambda: actor
    with TestClient(app, base_url="http://testserver/api/factory-inbound/") as client:
        yield client, actor, factory, queue


def _jpeg():
    buf = BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="JPEG")
    return buf.getvalue()


def upload(client):
    photo = _jpeg()
    response = client.post("notes", files={"scan": ("scan.jpg", photo), "original": ("source.jpg", photo)})
    assert response.status_code == 201, response.text
    assert response.json()["code"] == 201
    return response.json()["data"]


def result(number="7085384", ref=None):
    payload = {
        "delivery_no": number, "month": 11, "day": 11, "lines": [{
            "row": 1, "raw": "PU 22 878-18 20g 90条",
            "order_ref": ref, "grade": None, "process": "PU",
            "length": "22", "color": "878-18", "weight": "20g",
            "quantity": 90, "unit": "条", "line_type": "inbound", "inherited": [], "doubts": [],
        }],
    }
    return recognition_service.RecognitionResult.model_validate(payload)


def recognize(client, monkeypatch, queue, number, ref=None):
    note = upload(client)
    monkeypatch.setattr(recognition_service, "_recognize", lambda *_: result(number, ref))
    recognition_service.run(*queue.pop())
    return client.get("notes/" + str(note["id"])).json()["data"]


def test_server_matches_then_requires_choice_and_retains_audited_edits(system, monkeypatch):
    client, actor, factory, queue = system
    note = recognize(client, monkeypatch, queue, "7085384")
    line = note["lines"][0]
    assert line["match_status"] == "confirm"
    assert line["selected"] is False
    path = f"notes/{note['id']}/lines/{line['id']}"
    assert client.patch(path, json={"version": note["version"], "selected": True}).status_code == 422
    assert client.patch(path, json={"version": note["version"], "select": {"sku_id": 100}}).status_code == 409
    response = client.patch(path, json={"version": note["version"], "select": {"sku_id": 71, "suggest_color_alias": True}})
    assert response.status_code == 200, response.text
    current = response.json()["data"]
    assert current["lines"][0]["selected"] is True
    assert current["lines"][0]["match"]["product"]["sku_id"] == 71
    assert client.patch(path, json={"version": note["version"], "selected": False}).status_code == 409
    fresh = client.patch(path, json={"version": current["version"], "patch": {"quantity": 75}}).json()["data"]
    assert fresh["lines"][0]["match_status"] == "confirm"
    assert fresh["lines"][0]["values"]["quantity"] == 75
    assert fresh["lines"][0]["raw"]["quantity"] == 90
    assert fresh["logs"][0]["before"]["decision"]["sku_id"] == 71
    assert fresh["logs"][0]["after"]["decision"] == {}
    actor["permissions"] = [ADMIN]
    suggestion = client.get("aliases/suggestions").json()["data"][0]
    assert client.patch(f"aliases/suggestions/{suggestion['id']}", json={"accept": True}).json()["data"] == []


def test_exact_color_with_no_grade_and_stale_choice_require_manual_confirmation(system, monkeypatch):
    client, _, factory, queue = system
    note = recognize(client, monkeypatch, queue, "7085384")
    path = f"notes/{note['id']}/lines/{note['lines'][0]['id']}"
    exact = client.patch(path, json={"version": note["version"], "patch": {"color_raw": "#8TP8/18"}}).json()["data"]
    assert exact["lines"][0]["match_status"] == "confirm"
    assert not exact["lines"][0]["selected"]
    chosen = client.patch(path, json={"version": exact["version"], "select": {"sku_id": 71}}).json()["data"]
    assert chosen["lines"][0]["match_status"] == "matched"
    with factory.begin() as db:
        db.connection().exec_driver_sql("UPDATE lsordertest.okki_product_skus SET sku_id = 72")
    checked = client.patch(path, json={"version": chosen["version"], "select": {}}).json()["data"]
    assert checked["lines"][0]["match_status"] == "choose"
    assert not checked["lines"][0]["selected"]
    assert checked["lines"][0]["match"]["candidates"][0]["sku_id"] == 72


def test_permissions_and_protected_photo(system, monkeypatch):
    client, actor, factory, queue = system
    note = recognize(client, monkeypatch, queue, "7085384")
    path = f"notes/{note['id']}"
    response = client.get(path + "/image?original=true")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.content == _jpeg()
    actor["sub"] = "2"
    assert client.get(path + "/image").status_code == 404
    assert client.get("notes").json()["data"]["total"] == 0
    actor["permissions"] = [READ]
    assert client.get(path).status_code == 200
    assert client.post(path + "/void", json={"version": note["version"], "reason": "duplicate"}).status_code == 403
    actor["permissions"] = [WRITE]
    assert client.post(path + "/void", json={"version": note["version"], "reason": "duplicate"}).status_code == 403


def test_batch_endpoints_require_the_sync_flag_permission_and_correct_note(system, monkeypatch):
    client, actor, factory, _ = system
    monkeypatch.setattr(get_settings(), "FACTORY_INBOUND_SYNC_ENABLED", False)
    first = upload(client)
    second = upload(client)
    batches = f"notes/{first['id']}/batches"
    with factory.begin() as db:
        batch = Batch(note_id=first["id"], batch_no="FAKE-01", confirmed_by=1, idempotency_key="fake-01",
                      plan_snapshot={}, request_snapshot={}, purchase_intent={"purchase_order_no": "P-01"},
                      sync_checkpoint={"stage": "purchase"})
        db.add(batch)
        db.flush()
        batch_id = batch.id
    resume = f"{batches}/{batch_id}/resume"
    called = []

    def advance(db, selected_id):
        called.append(selected_id)
        return db.get(Batch, selected_id)

    monkeypatch.setattr(sync_service, "advance_batch", advance)
    payload = {"version": first["version"], "line_ids": [1]}
    confirmation = {
        **payload, "idempotency_key": "a" * 32, "preview_digest": "b" * 64,
        "unit_prices": [{"product_id": "1", "sku_id": "71", "unit_price": 12}],
    }
    assert client.post(batches + "/preview", json=payload).status_code == 503
    assert client.post(batches, json=confirmation).status_code == 503
    assert client.post(resume).status_code == 503
    assert client.get(batches).json()["data"]["can_advance"] is False
    monkeypatch.setattr(get_settings(), "FACTORY_INBOUND_SYNC_ENABLED", True)
    actor["permissions"] = [READ]
    assert client.get(batches).json()["data"]["items"][0]["id"] == str(batch_id)
    assert client.post(resume).status_code == 403
    actor["permissions"] = [WRITE]
    actor["sub"] = "2"
    assert client.post(resume).status_code == 404
    actor["sub"] = "1"
    assert client.post(f"notes/{second['id']}/batches/{batch_id}/resume").status_code == 404
    assert client.post(batches + "/preview", json={**payload, "line_ids": [1, 1]}).status_code == 422
    confirmation["unit_prices"][0]["unit_price"] = 0
    assert client.post(batches, json=confirmation).status_code == 422
    assert called == []
    assert client.post(resume).json()["data"]["id"] == str(batch_id)
    assert called == [batch_id]


def test_corrected_duplicate_void_references_confirmed_collision(system, monkeypatch):
    client, _, factory, queue = system
    first = recognize(client, monkeypatch, queue, "7085384")
    second = recognize(client, monkeypatch, queue, "7085385")
    for note in (first, second):
        response = client.patch(f"notes/{note['id']}/delivery", json={
            "version": note["version"], "delivery_no": note["recognized_delivery_no"], "confirmed": True,
        })
        assert response.json()["data"]["delivery_no"] == note["recognized_delivery_no"]
    third = recognize(client, monkeypatch, queue, "7085384")
    assert third["status"] == "draft"
    assert third["duplicate"]["id"] == first["id"]
    changed = client.patch(f"notes/{third['id']}/delivery", json={
        "version": third["version"], "delivery_no": "7085385", "confirmed": True,
    }).json()["data"]
    assert changed["delivery_no"] is None
    assert changed["duplicate"]["id"] == second["id"]
    assert len(changed["lines"]) == 1
    response = client.post(f"notes/{third['id']}/void", json={
        "version": changed["version"], "reason": "确认重拍", "duplicate": True,
    })
    assert response.status_code == 200
    with factory() as db:
        assert db.get(Note, third["id"]).duplicate_of_note_id == second["id"]


def test_fresh_permission_filters_invoice_originals_and_restricts_ambiguous_choice(system, monkeypatch):
    client, actor, factory, queue = system
    actor["permissions"] = [WRITE, "invoice:read", "invoice:read_all"]
    with factory.begin() as db:
        for name in ("Synthetic Name One生产单1113", "Synthetic Name Two生产单1113"):
            db.add(Invoice(invoice_no=name, invoice_date=beijing_today(), order_type="production",
                           customer_id="fixture", customer_name="Synthetic Buyer", created_by=1))
    note = recognize(client, monkeypatch, queue, "7099999", "1113")
    line = note["lines"][0]
    orders = line["match"]["orders"]
    assert len(orders) == 2
    assert all(order["restricted"] and "invoice_no" not in order for order in orders)
    assert "Synthetic" not in str(note)
    assert client.patch(f"notes/{note['id']}/lines/{line['id']}", json={
        "version": note["version"], "select": {"order": {"kind": "invoice", "id": orders[0]["id"]}},
    }).status_code == 403


def test_daily_number_changes_at_beijing_midnight_on_utc_clock(system, monkeypatch):
    client, _, _, _ = system

    class UTCClock(datetime):
        clock = datetime(2026, 11, 17, 15, 59, 59, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.clock.astimezone(tz or timezone.utc)

    monkeypatch.setattr(business_time, "datetime", UTCClock)
    previous = upload(client)
    UTCClock.clock = datetime(2026, 11, 17, 16, 0, tzinfo=timezone.utc)
    current = upload(client)
    same_day = upload(client)
    assert previous["inbound_no"] == "FI20261117-001"
    assert current["inbound_no"] == "FI20261118-001"
    assert current["created_at"] == "2026-11-18T00:00:00"
    assert same_day["inbound_no"] == "FI20261118-002"


def test_queued_attempt_cannot_replace_existing_recognition(system, monkeypatch):
    client, _, factory, queue = system
    note = upload(client)
    note_id, attempt = queue.pop()
    with factory.begin() as db:
        db.get(Note, note_id).recognition_attempt_id = "different-attempt"
    monkeypatch.setattr(recognition_service, "_recognize", lambda *_: pytest.fail("Stale worker called OCR"))
    recognition_service.run(note_id, attempt)
    fresh = client.get(f"notes/{note['id']}").json()["data"]
    assert fresh["recognition_status"] == "queued"
    with factory() as db:
        assert not db.scalars(select(Line).where(Line.note_id == note_id)).all()
