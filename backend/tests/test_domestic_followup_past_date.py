"""Past-dated normal followups may carry explicit current plans and progress."""
from datetime import date, datetime, time, timedelta

import pytest

from app.domestic_followup import followup_service, jobs, record_access, stats_service
from app.domestic_followup.collaboration_access import create_initial_responsibility
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupTask
from tests.domestic_followup_helpers import ALL_PERMS, followup_client, grant, make_customer, make_user, seed_dicts

TODAY = date(2026, 11, 13)


@pytest.fixture
def managed_customer(db, monkeypatch):
    for module in (followup_service, record_access, stats_service):
        monkeypatch.setattr(module, "beijing_today", lambda: TODAY)
    monkeypatch.setattr(jobs, "submit", lambda *args: None)
    seed_dicts(db)
    owner = make_user(db, "past_date_owner")
    grant(db, owner, *ALL_PERMS)
    customer = make_customer(db, owner, "允许补录日期")
    responsibility = create_initial_responsibility(db, customer.id, owner.id)
    responsibility.last_progress_at = datetime.combine(TODAY - timedelta(days=1), time.min)
    db.commit()
    return owner, customer, responsibility


@pytest.mark.parametrize("via_draft", [False, True])
@pytest.mark.parametrize("days_ago", [2, 45])
def test_past_followup_with_plan_and_explicit_stage_saves_and_counts_on_selected_date(
        db, managed_customer, via_draft, days_ago):
    owner, customer, responsibility = managed_customer
    occurred = TODAY - timedelta(days=days_ago)
    recent_progress = responsibility.last_progress_at
    payload = {"customer_id": customer.id, "followup_date": occurred.isoformat(),
               "result_code": "有效沟通", "next_date": (TODAY + timedelta(days=3)).isoformat(),
               "next_plan": "电话确认采购需求", "plan_purpose": "development",
               "development_stage": "quoted", "effective_progress": True,
               "responsibility_version": responsibility.version}
    with followup_client(db, owner) as client:
        if via_draft:
            draft_response = client.post("/api/domestic-followup/drafts", json={
                "request_id": "past-date-draft", "customer_id": customer.id,
                "followup_date": occurred.isoformat(), "raw_text": "客户电话询价",
            })
            assert draft_response.status_code == 200
            draft = draft_response.json()["data"]
            response = client.post(f"/api/domestic-followup/drafts/{draft['id']}/confirm",
                                   json={**payload, "version": draft["version"]})
        else:
            response = client.post("/api/domestic-followup/followups", json={
                **payload, "request_id": "past-date-direct", "raw_text": "客户电话询价",
            })
        assert response.status_code == 200, response.text
        assert response.json()["data"]["followup_date"] == occurred.isoformat()
        assert response.json()["data"]["status"] == "confirmed"
        for day, expected in ((occurred, 1), (TODAY, 0)):
            stats = client.get("/api/domestic-followup/stats/personal", params={
                "range": "custom", "date_from": day.isoformat(), "date_to": day.isoformat(),
            })
            assert stats.status_code == 200
            assert stats.json()["data"]["people"][0]["kpis"]["count"] == expected
    task = db.query(DomesticFollowupTask).filter_by(task_type="plan").one()
    assert task.due_date == TODAY + timedelta(days=3)
    assert task.assignee_user_id == owner.id
    assert responsibility.stage == "quoted"
    assert responsibility.last_progress_at == recent_progress


@pytest.mark.parametrize("change, expected_status, message", [
    ({"responsibility_version": 999}, 409, "已变更"),
    ({"followup_date": (TODAY + timedelta(days=1)).isoformat()}, 400, "不能晚于今天"),
    ({"next_date": (TODAY - timedelta(days=20)).isoformat()}, 400, "不能早于跟进日期"),
    ({"result_code": None}, 400, "请选择本次结果"),
])
def test_past_date_keeps_existing_validation(db, managed_customer, change, expected_status, message):
    owner, customer, responsibility = managed_customer
    payload = {"request_id": "past-date-validation", "customer_id": customer.id,
               "raw_text": "客户电话询价", "followup_date": (TODAY - timedelta(days=3)).isoformat(),
               "result_code": "有效沟通", "next_date": (TODAY + timedelta(days=1)).isoformat(),
               "plan_purpose": "development", "responsibility_version": responsibility.version, **change}
    with followup_client(db, owner) as client:
        response = client.post("/api/domestic-followup/followups", json=payload)
        assert response.status_code == expected_status
        assert message in response.json()["detail"]
    assert db.query(DomesticFollowup).count() == 0
    assert db.query(DomesticFollowupTask).count() == 0
