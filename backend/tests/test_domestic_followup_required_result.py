"""Confirmed followups require an explicit outcome; drafts may remain incomplete."""
from datetime import date

import pytest

from app.domestic_followup import followup_service, jobs
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupRevision, DomesticFollowupTask
from app.system.models import SysDict
from tests.domestic_followup_helpers import followup_client, make_customer, make_user, seed_dicts


@pytest.fixture
def setup_record(db, monkeypatch):
    seed_dicts(db)
    monkeypatch.setattr(followup_service, "beijing_today", lambda: date(2026, 11, 13))
    monkeypatch.setattr(jobs, "submit", lambda *args: None)
    user = make_user(db, "required_result")
    customer = make_customer(db, user, "结果必填客户")
    db.commit()
    return user, customer


@pytest.mark.parametrize("result", [None, "", "   "])
def test_direct_save_rejects_blank_outcome_without_saving_record(db, setup_record, result):
    user, customer = setup_record
    with followup_client(db, user) as client:
        response = client.post("/api/domestic-followup/followups", json={
            "request_id": "required-direct", "customer_id": customer.id,
            "raw_text": "客户介绍了经营情况", "result_code": result,
        })
        assert response.status_code == 400
        assert "请选择本次结果" in response.json()["detail"]
        assert db.query(DomesticFollowup).count() == 0


def test_draft_accepts_missing_outcome_but_confirmation_requires_it(db, setup_record):
    user, customer = setup_record
    with followup_client(db, user) as client:
        response = client.post("/api/domestic-followup/drafts", json={
            "request_id": "required-draft", "raw_text": "待整理的沟通原文", "customer_id": customer.id,
        })
        assert response.status_code == 200
        draft = response.json()["data"]
        url = f"/api/domestic-followup/drafts/{draft['id']}/confirm"
        payload = {"version": draft["version"], "customer_id": customer.id}
        response = client.post(url, json=payload)
        assert response.status_code == 400
        assert "请选择本次结果" in response.json()["detail"]
        assert db.get(DomesticFollowup, draft["id"]).status == "draft"
        response = client.post(url, json={**payload, "result_code": "未回复"})
        assert response.status_code == 200
        assert response.json()["data"]["result_code"] == "未回复"


def test_edit_legacy_record_requires_outcome_and_does_not_backfill_other_records(db, setup_record):
    user, customer = setup_record
    rows = [DomesticFollowup(author_user_id=user.id, customer_id=customer.id,
                            followup_date=date(2026, 11, 10), status="confirmed", version=2,
                            raw_text="历史记录", request_id=f"legacy-result-{i}") for i in range(2)]
    db.add_all(rows)
    db.commit()
    with followup_client(db, user) as client:
        url = f"/api/domestic-followup/followups/{rows[0].id}"
        payload = {"version": 2, "request_id": "required-edit", "reason": "补充沟通结果",
                   "followup_date": "2026-11-10", "raw_text": "客户介绍了经营情况"}
        response = client.put(url, json=payload)
        assert response.status_code == 400
        assert "请选择本次结果" in response.json()["detail"]
        assert db.query(DomesticFollowupRevision).count() == 0
        response = client.put(url, json={**payload, "result_code": "有效沟通"})
        assert response.status_code == 200, response.text
        assert db.get(DomesticFollowup, rows[0].id).result_code == "有效沟通"
        assert db.get(DomesticFollowup, rows[1].id).result_code is None
        payload.update(version=3, request_id="required-edit-clear", result_code="")
        response = client.put(url, json=payload)
        assert response.status_code == 400
        assert db.get(DomesticFollowup, rows[0].id).result_code == "有效沟通"


def test_quick_receipt_with_disabled_outcome_preserves_task_and_offers_manual_recording(db, setup_record):
    user, customer = setup_record
    value = db.query(SysDict).filter_by(type="domestic_followup_result", code="有效沟通").one()
    value.is_active = False
    task = DomesticFollowupTask(customer_id=customer.id, assignee_user_id=user.id,
                               task_type="receipt", source_key="receipt:required-result",
                               title="收货回访", due_date=date(2026, 11, 13))
    db.add(task)
    db.commit()
    with followup_client(db, user) as client:
        response = client.post(f"/api/domestic-followup/tasks/{task.id}/receipt-ok",
                               json={"request_id": "disabled-result-receipt"})
        assert response.status_code == 400
        assert "记跟进" in response.json()["detail"]
        assert db.get(DomesticFollowupTask, task.id).status == "todo"
        assert db.query(DomesticFollowup).count() == 0
