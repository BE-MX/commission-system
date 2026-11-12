from datetime import date, datetime, timedelta

import pytest

from app.core.time import beijing_now

from app.domestic_followup.models import DomesticFollowup
from tests.domestic_followup_helpers import followup_client, grant, make_customer, make_user

TODAY = date(2026, 11, 12)
SALES = ("domestic_followup:read", "domestic_followup:write")
MANAGER = ("domestic_followup:read", "domestic_followup:read_all")


def _confirmed(db, author, customer, text="客户说月底要上新", *, days=1):
    row = DomesticFollowup(
        author_user_id=author.id, customer_id=customer.id, followup_date=TODAY - timedelta(days=days),
        request_id=f"insight-evidence-{author.id}-{customer.id}-{len(db.query(DomesticFollowup).all())}",
        status="confirmed", version=2, result_code="有效沟通", summary=text, raw_text=text,
    )
    db.add(row)
    db.flush()
    return row


def _snapshot(db, scope, user_id, items, *, record_count=1):
    from app.domestic_followup.insight_models import DomesticFollowupInsight, DomesticFollowupInsightSnapshot

    snapshot = DomesticFollowupInsightSnapshot(
        scope=scope, user_id=user_id, status="done", trigger="test", period_start=TODAY - timedelta(days=30),
        period_end=TODAY, record_count=record_count, generated_at=beijing_now(),
        payload={"highlights": []},
    )
    db.add(snapshot)
    db.flush()
    rows = []
    for item in items:
        item.setdefault("evidence_versions", {str(record_id): db.get(DomesticFollowup, record_id).version
                                            for record_id in item["evidence_followup_ids"]})
        row = DomesticFollowupInsight(snapshot_id=snapshot.id, **item)
        db.add(row)
        db.flush()
        rows.append(row)
    return snapshot, rows


def test_insights_empty_state_and_manual_refresh_quota(db, monkeypatch):
    from app.domestic_followup import insight_jobs

    manager = make_user(db, "insight_manager")
    targets = [make_user(db, f"insight_target_{i}") for i in range(3)]
    submitted = []
    monkeypatch.setattr(insight_jobs, "submit", lambda fn, *args: submitted.append((fn, args)))
    with followup_client(db, manager, permissions=MANAGER) as client:
        empty = client.get("/api/domestic-followup/insights", params={"user_id": targets[0].id})
        assert empty.status_code == 200 and empty.json()["data"]["personal"] is None
        for target in targets[:2]:
            response = client.post("/api/domestic-followup/insights/refresh", json={"user_id": target.id})
            assert response.status_code == 200 and response.json()["data"]["status"] == "running"
        third = client.post("/api/domestic-followup/insights/refresh", json={"user_id": targets[2].id})
        assert third.status_code == 400 and "每天" in third.json()["detail"]
    assert len(submitted) == 3  # two personal snapshots plus one shared company snapshot


def test_personal_evidence_is_reloaded_and_invalidated_on_read(db):
    from app.domestic_followup.insight_models import DomesticFollowupInsightSnapshot

    sales = make_user(db, "insight_sales")
    customer = make_customer(db, sales, "证据店")
    record = _confirmed(db, sales, customer)
    _snapshot(db, "personal", sales.id, [{
        "category": "deal", "customer_id": customer.id, "title": "出现成交信号", "body": "客户主动问交期",
        "suggested_action": "本周报价", "suggested_date": TODAY + timedelta(days=1),
        "evidence_followup_ids": [record.id], "signals": ["问交期"], "sample_size": 1,
    }])
    with followup_client(db, sales, permissions=SALES) as client:
        data = client.get("/api/domestic-followup/insights").json()["data"]
        item = data["personal"]["items"][0]
        assert item["evidence"][0]["raw_text"] == "客户说月底要上新"
        record.status = "discarded"
        db.flush()
        data = client.get("/api/domestic-followup/insights").json()["data"]
        assert data["personal"]["items"] == []


def test_company_insights_are_deidentified_and_small_topics_hidden(db):
    sales = make_user(db, "insight_company_sales")
    other = make_user(db, "insight_company_other")
    customer = make_customer(db, other, "不该泄露店名")
    first = _confirmed(db, other, customer, "直播退货率高")
    second = _confirmed(db, other, make_customer(db, other, "第二家"), "直播退货率仍然高")
    third = _confirmed(db, other, make_customer(db, other, "第三家"), "退货问题")
    for record in (first, second, third):
        record.obstacles = ["价格"]
    _snapshot(db, "company", None, [
        {"category": "common", "customer_id": customer.id, "theme_key": "obstacle:价格",
         "title": "不该泄露店名提到直播退货", "body": "不该泄露店名等 3 家提到同一问题",
         "suggested_action": "统一选品建议", "evidence_followup_ids": [first.id, second.id], "sample_size": 3,
         "public_summary": {"title": "价格问题", "body": "3 家提到价格问题", "suggested_action": "统一选品建议"}},
        {"category": "common", "title": "小样本主题", "body": "只有两家", "evidence_followup_ids": [first.id],
         "sample_size": 2},
        {"category": "single", "customer_id": customer.id, "title": "个别问题", "body": "高等级客户",
         "evidence_followup_ids": [first.id], "sample_size": 1},
    ])
    with followup_client(db, sales, permissions=SALES) as client:
        data = client.get("/api/domestic-followup/insights").json()["data"]
        items = data["company"]["items"]
        assert len(items) == 1
        assert items[0]["deidentified"] is True
        assert items[0]["customer_id"] is None and items[0]["evidence"] == []
        assert "不该泄露店名" not in items[0]["title"] + items[0]["body"]


def test_insight_to_task_requires_customer_write_and_is_idempotent(db):
    sales = make_user(db, "insight_task_sales")
    manager = make_user(db, "insight_task_manager")
    customer = make_customer(db, sales, "转待办店")
    record = _confirmed(db, sales, customer)
    _, items = _snapshot(db, "personal", sales.id, [{
        "category": "deal", "customer_id": customer.id, "title": "报价机会", "body": "问价",
        "suggested_action": "报批量价", "evidence_followup_ids": [record.id], "sample_size": 1,
    }])
    insight_id = items[0].id
    with followup_client(db, manager, permissions=MANAGER) as client:
        assert client.post(f"/api/domestic-followup/insights/{insight_id}/to-task", json={
            "due_date": (TODAY + timedelta(days=1)).isoformat(), "content": "报批量价",
        }).status_code == 403
    with followup_client(db, sales, permissions=SALES) as client:
        first = client.post(f"/api/domestic-followup/insights/{insight_id}/to-task", json={
            "due_date": (TODAY + timedelta(days=1)).isoformat(), "content": "报批量价",
        })
        assert first.status_code == 200
        second = client.post(f"/api/domestic-followup/insights/{insight_id}/to-task", json={
            "due_date": (TODAY + timedelta(days=2)).isoformat(), "content": "改名也不重复",
        })
        assert second.status_code == 200
        assert second.json()["data"]["task_id"] == first.json()["data"]["task_id"]


def test_generation_filters_unknown_evidence_and_fills_backend_numbers(db, monkeypatch):
    import json

    from app.domestic_followup import insight_generation, insight_service
    from app.domestic_followup.insight_models import DomesticFollowupInsight, DomesticFollowupInsightSnapshot

    sales = make_user(db, "insight_generation_sales")
    customer = make_customer(db, sales, "生成店", level="A级")
    record = _confirmed(db, sales, customer, days=20)
    grant(db, sales, "domestic_followup:write")
    monkeypatch.setattr(insight_generation, "beijing_today", lambda: TODAY)
    monkeypatch.setattr(insight_service, "beijing_today", lambda: TODAY)
    payload = {"items": [
        {"category": "deal", "customer_id": customer.id, "title": "问交期", "body": "当前超期 {overdue} 家",
         "suggested_action": "报价", "suggested_date": (TODAY + timedelta(days=1)).isoformat(),
         "evidence_followup_ids": [record.id], "signals": ["问交期"]},
        {"category": "cold", "customer_id": customer.id, "title": "无证据", "body": "不能展示",
         "evidence_followup_ids": [999999]},
    ]}
    monkeypatch.setattr(insight_generation, "chat", lambda **kwargs: {"content": json.dumps(payload, ensure_ascii=False)})
    snapshot = DomesticFollowupInsightSnapshot(
        scope="personal", user_id=sales.id, status="running", trigger="test",
        period_start=TODAY - timedelta(days=30), period_end=TODAY, request_day=TODAY,
    )
    db.add(snapshot)
    db.flush()
    insight_generation.generate_snapshot(db, snapshot.id)
    db.refresh(snapshot)
    assert snapshot.status == "done"
    assert db.query(DomesticFollowupInsight).filter_by(snapshot_id=snapshot.id).count() == 1
    with followup_client(db, sales, permissions=SALES) as client:
        items = client.get("/api/domestic-followup/insights").json()["data"]["personal"]["items"]
        assert len(items) == 1
        assert items[0]["body"] == f"当前超期 {items[0]['numeric_values']['overdue']} 家"
        assert items[0]["numeric_values"]["overdue"] == 1
