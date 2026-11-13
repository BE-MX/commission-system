from datetime import date

import pytest

from app.domestic_followup import ai_parse_service, attachment_service, followup_service, jobs
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupAttachment, DomesticFollowupItem
from tests.domestic_followup_helpers import followup_client, grant, make_customer, make_user, seed_dicts

TODAY = date(2026, 10, 30)


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(followup_service, "beijing_today", lambda: TODAY)
    monkeypatch.setattr(followup_service, "_enqueue_urgent", lambda *a, **k: None)


def _record_jobs(monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "submit", lambda fn, *args: calls.append((fn, args)))
    return calls


def test_direct_save_submits_ocr_only_when_screenshots_pending(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_rt_ocr")
    customer = make_customer(db, user, "路由店OCR")
    att = DomesticFollowupAttachment(uploader_user_id=user.id, seq=1, file_path="fu/o.png", mime_type="image/png")
    db.add(att)
    db.flush()
    calls = _record_jobs(monkeypatch)
    with followup_client(db, user) as client:
        plain = client.post("/api/domestic-followup/followups", json={
            "result_code": "有效沟通",
            "request_id": "rt-ocr-plain", "customer_id": customer.id, "raw_text": "无截图"})
        assert plain.status_code == 200 and calls == []
        shot = client.post("/api/domestic-followup/followups", json={
            "result_code": "有效沟通",
            "request_id": "rt-ocr-shot", "customer_id": customer.id, "raw_text": "带截图",
            "attachment_ids": [att.id]})
        assert shot.status_code == 200
    assert calls == [(attachment_service.run_ocr, ([att.id],))]


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
            "result_code": "有效沟通",
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
    calls = _record_jobs(monkeypatch)
    with followup_client(db, user) as client:
        draft = client.post("/api/domestic-followup/drafts",
                            json={"request_id": "rt-draft-c", "raw_text": "聊天"}).json()["data"]
        assert [(fn, args[0]) for fn, args in calls] == [(ai_parse_service.run_parse, draft["id"])]
        assert draft["ai_status"] == "running"
        replay = client.post("/api/domestic-followup/drafts", json={"request_id": "rt-draft-c", "raw_text": "聊天"})
        assert replay.json()["data"]["id"] == draft["id"] and len(calls) == 1  # 重放不重复调模型
        bad = client.post(f"/api/domestic-followup/drafts/{draft['id']}/confirm",
                          json={"result_code": "有效沟通", "version": 9, "customer_id": customer.id})
        assert bad.status_code == 409
        good = client.post(f"/api/domestic-followup/drafts/{draft['id']}/confirm",
                           json={"result_code": "有效沟通", "version": draft["version"], "customer_id": customer.id})
        assert good.status_code == 200 and good.json()["data"]["status"] == "confirmed"


def test_writing_other_owners_customer_is_403(db):
    seed_dicts(db)
    owner = make_user(db, "fu_rt_d1")
    other = make_user(db, "fu_rt_d2")
    customer = make_customer(db, owner, "路由店D")
    with followup_client(db, other) as client:
        resp = client.post("/api/domestic-followup/followups",
                           json={"result_code": "有效沟通", "request_id": "rt-direct-d", "customer_id": customer.id, "raw_text": "x"})
        assert resp.status_code == 403 and "fu_rt_d1" in resp.json()["detail"]


def test_config_write_requires_admin(db):
    user = make_user(db, "fu_rt_e")
    with followup_client(db, user) as client:
        assert client.put("/api/domestic-followup/config", json={"receipt_delay_days": 4}).status_code == 403
    with followup_client(db, user, permissions=("domestic_followup:read", "domestic_followup:admin")) as client:
        resp = client.put("/api/domestic-followup/config", json={"receipt_delay_days": 4})
        assert resp.status_code == 200 and resp.json()["data"]["receipt_delay_days"] == 4


def test_cannot_read_other_users_draft(db):
    seed_dicts(db)
    author = make_user(db, "fu_rt_f1")
    other = make_user(db, "fu_rt_f2")
    draft = DomesticFollowup(author_user_id=author.id, followup_date=TODAY, request_id="rt-draft-f",
                             status="draft", ai_status="none", version=1)
    db.add(draft)
    db.flush()
    with followup_client(db, other) as client:
        assert client.get(f"/api/domestic-followup/drafts/{draft.id}").status_code == 404


def test_cannot_read_other_users_screenshot(db):
    author = make_user(db, "fu_rt_g1")
    other = make_user(db, "fu_rt_g2")
    att = DomesticFollowupAttachment(uploader_user_id=author.id, seq=1, file_path="fu/g.png", mime_type="image/png")
    db.add(att)
    db.flush()
    with followup_client(db, other) as client:
        assert client.get(f"/api/domestic-followup/attachments/{att.id}/file").status_code == 403


def test_cannot_resolve_item_outside_scope(db):
    owner = make_user(db, "fu_rt_h1")
    other = make_user(db, "fu_rt_h2")
    customer = make_customer(db, owner, "路由店H")
    followup = DomesticFollowup(author_user_id=owner.id, customer_id=customer.id, followup_date=TODAY,
                                request_id="rt-item-h", status="confirmed", version=2)
    db.add(followup)
    db.flush()
    item = DomesticFollowupItem(followup_id=followup.id, customer_id=customer.id, seq=1, kind="issue",
                                text="掉色", category="质量", severity="一般", status="open",
                                handler_user_id=owner.id)
    db.add(item)
    db.flush()
    with followup_client(db, other) as client:
        resp = client.post(f"/api/domestic-followup/items/{item.id}/resolve",
                           json={"status": "resolved", "resolution": "x"})
        assert resp.status_code == 403
    db.refresh(item)
    assert item.status == "open"


def test_user_search_for_transfer(db):
    user = make_user(db, "fu_rt_f")
    grant(db, make_user(db, "fu_rt_qc"), "domestic_followup:write")
    make_user(db, "fu_rt_qc_reader")  # 没有跟进权限：转过去也处理不了，不该出现在候选里
    with followup_client(db, user) as client:
        rows = client.get("/api/domestic-followup/users", params={"q": "qc"}).json()["data"]
        assert [r["real_name"] for r in rows] == ["fu_rt_qc"]
