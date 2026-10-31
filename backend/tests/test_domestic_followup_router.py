from datetime import date

import pytest

from app.domestic_followup import followup_service, router as followup_router
from tests.domestic_followup_helpers import followup_client, make_customer, make_user, seed_dicts

TODAY = date(2026, 10, 30)


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(followup_service, "beijing_today", lambda: TODAY)
    monkeypatch.setattr(followup_service, "_enqueue_urgent", lambda *a, **k: None)


def test_requires_permission(db):
    user = make_user(db, "fu_rt_a")
    with followup_client(db, user, permissions=()) as client:
        assert client.get("/api/domestic-followup/tasks").status_code == 403


def test_direct_save_and_list(db):
    seed_dicts(db)
    user = make_user(db, "fu_rt_b")
    customer = make_customer(db, user, "路由店B")
    with followup_client(db, user) as client:
        resp = client.post("/api/domestic-followup/followups", json={
            "request_id": "rt-direct-b", "customer_id": customer.id, "raw_text": "回访正常",
            "next_date": "2026-11-02", "next_plan": "问补货"})
        assert resp.status_code == 200 and resp.json()["code"] == 200
        listed = client.get("/api/domestic-followup/followups", params={"customer_id": customer.id}).json()["data"]
        assert listed["total"] == 1
        tasks = client.get("/api/domestic-followup/tasks", params={"due": "all"}).json()["data"]
        assert tasks["items"][0]["task_type"] == "plan"


def test_draft_starts_background_parse_and_conflict_maps_409(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_rt_c")
    customer = make_customer(db, user, "路由店C")
    calls = []
    monkeypatch.setattr(followup_router.ai_parse_service, "run_parse", lambda fid, cu: calls.append(fid))
    with followup_client(db, user) as client:
        draft = client.post("/api/domestic-followup/drafts",
                            json={"request_id": "rt-draft-c", "raw_text": "聊天"}).json()["data"]
        assert calls == [draft["id"]] and draft["ai_status"] == "running"
        bad = client.post(f"/api/domestic-followup/drafts/{draft['id']}/confirm",
                          json={"version": 9, "customer_id": customer.id})
        assert bad.status_code == 409
        good = client.post(f"/api/domestic-followup/drafts/{draft['id']}/confirm",
                           json={"version": draft["version"], "customer_id": customer.id})
        assert good.status_code == 200 and good.json()["data"]["status"] == "confirmed"


def test_writing_other_owners_customer_is_403(db):
    seed_dicts(db)
    owner = make_user(db, "fu_rt_d1")
    other = make_user(db, "fu_rt_d2")
    customer = make_customer(db, owner, "路由店D")
    with followup_client(db, other) as client:
        resp = client.post("/api/domestic-followup/followups",
                           json={"request_id": "rt-direct-d", "customer_id": customer.id, "raw_text": "x"})
        assert resp.status_code == 403 and "fu_rt_d1" in resp.json()["detail"]


def test_config_write_requires_admin(db):
    user = make_user(db, "fu_rt_e")
    with followup_client(db, user) as client:
        assert client.put("/api/domestic-followup/config", json={"receipt_delay_days": 4}).status_code == 403
    with followup_client(db, user, permissions=("domestic_followup:read", "domestic_followup:admin")) as client:
        resp = client.put("/api/domestic-followup/config", json={"receipt_delay_days": 4})
        assert resp.status_code == 200 and resp.json()["data"]["receipt_delay_days"] == 4
