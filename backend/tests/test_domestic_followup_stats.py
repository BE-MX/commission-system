from datetime import date, datetime, timedelta

import pytest

from app.domestic_followup.collaboration_models import FollowupResponsibility
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupConfig, DomesticFollowupTask
from tests.domestic_followup_helpers import followup_client, grant, make_customer, make_user

TODAY = date(2026, 11, 12)
START = date(2026, 10, 14)
MANAGER = ("domestic_followup:read", "domestic_followup:read_all")
SALES = ("domestic_followup:read", "domestic_followup:write")


@pytest.fixture(autouse=True)
def fixed_business_day(monkeypatch):
    from app.domestic_followup import stats_service

    monkeypatch.setattr(stats_service, "beijing_today", lambda: TODAY)


def _record(db, author, customer, when, *, result=None, effective=False, next_date=None,
            status="confirmed", obstacles=None, states=None):
    row = DomesticFollowup(
        author_user_id=author.id, customer_id=customer.id, followup_date=when,
        request_id=f"stats-{author.id}-{customer.id}-{when}-{status}-{result}-{len(db.query(DomesticFollowup).all())}",
        status=status, version=2, result_code=result, effective_progress=effective,
        next_date=next_date, obstacles=obstacles, state_changes=states,
        summary=f"{customer.shop_name} {result or '未填结果'}", raw_text="客户沟通原文",
    )
    db.add(row)
    db.flush()
    return row


def _roster(db, users):
    for user in users:
        grant(db, user, "domestic_followup:write")
    db.add(DomesticFollowupConfig(key="stats_user_ids", value=[u.id for u in users]))
    db.flush()


def _personal(client, user_id=None):
    params = {"range": "custom", "date_from": START.isoformat(), "date_to": TODAY.isoformat()}
    if user_id:
        params["user_id"] = user_id
    return client.get("/api/domestic-followup/stats/personal", params=params)


def test_personal_counts_confirmed_records_and_negative_results(db):
    sales = make_user(db, "stats_sales")
    other = make_user(db, "stats_other")
    first = make_customer(db, sales, "统计店A", level="A级")
    second = make_customer(db, sales, "统计店B", level="B级")
    _record(db, sales, first, TODAY - timedelta(days=2), result="有效沟通", effective=True,
            next_date=TODAY + timedelta(days=1))
    _record(db, sales, first, TODAY - timedelta(days=1), result="未回复")
    _record(db, sales, second, TODAY, result=None)
    _record(db, sales, second, TODAY, result="已报价", status="draft")
    _record(db, other, first, TODAY, result="有效沟通")
    _roster(db, [sales, other])

    with followup_client(db, sales, permissions=SALES) as client:
        response = _personal(client)
        assert response.status_code == 200
        data = response.json()["data"]
        assert [p["user"]["id"] for p in data["people"]] == [sales.id]
        person = data["people"][0]
        assert person["kpis"]["count"] == 3
        assert person["kpis"]["reach"] == 2
        assert person["kpis"]["effective_rate"] == 0.5
        assert person["quality"]["next_step"]["value"] == 0.3333
        assert person["quality"]["effective_progress"]["value"] == 0.5
        assert data["team_average"] is None  # 少于 4 人不能反推团队明细
        assert _personal(client, other.id).status_code == 403


def test_manager_gets_previous_period_and_four_person_anonymous_average(db):
    manager = make_user(db, "stats_manager")
    salespeople = [make_user(db, f"stats_avg_{i}") for i in range(4)]
    for index, sales in enumerate(salespeople, 1):
        customer = make_customer(db, sales, f"均值店{index}")
        for offset in range(index):
            _record(db, sales, customer, TODAY - timedelta(days=offset), result="有效沟通")
        _record(db, sales, customer, START - timedelta(days=1), result="未回复")
    _roster(db, salespeople)

    with followup_client(db, manager, permissions=MANAGER) as client:
        response = _personal(client)
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["people"]) == 4
        assert data["team_average"]["count"] == 2.5
        assert data["team_average"]["effective_rate"] == 1
        assert "people" not in data["team_average"]
        assert data["people"][0]["kpis"]["previous_count"] == 1


def test_customer_coverage_responsibility_pause_and_ungraded(db):
    sales = make_user(db, "stats_cover")
    legacy_owner = make_user(db, "stats_legacy")
    current = make_customer(db, legacy_owner, "责任转移店", level="A级")
    paused = make_customer(db, sales, "暂缓店", level="B级")
    ungraded = make_customer(db, sales, "未定级店", level=None)
    stopped = make_customer(db, sales, "停止开发店", level="S级")
    never = make_customer(db, sales, "从未跟进店", level="S级")
    db.add_all([
        FollowupResponsibility(customer_id=current.id, owner_user_id=sales.id, status="following", version=1),
        FollowupResponsibility(customer_id=paused.id, owner_user_id=sales.id, status="following", stage="paused",
                               next_plan_date=TODAY + timedelta(days=5), version=1),
        FollowupResponsibility(customer_id=stopped.id, owner_user_id=sales.id, status="stopped", version=1),
        FollowupResponsibility(customer_id=never.id, owner_user_id=sales.id, status="following", version=1,
                               created_at=datetime.combine(TODAY - timedelta(days=10), datetime.min.time())),
    ])
    db.flush()
    _record(db, sales, current, TODAY - timedelta(days=20), result="有效沟通")
    _roster(db, [sales])

    with followup_client(db, sales, permissions=SALES) as client:
        person = _personal(client).json()["data"]["people"][0]
        assert person["kpis"]["overdue"] == 2
        overdue = {row["customer_id"]: row for row in person["overdue_customers"]}
        assert overdue[current.id]["overdue_days"] == 6
        assert overdue[never.id]["overdue_days"] == 3
        assert paused.id not in overdue and ungraded.id not in overdue and stopped.id not in overdue
        coverage = {row["level"]: row for row in person["coverage"]}
        assert coverage["A级"]["total"] == 1 and coverage["A级"]["on_track"] == 0
        assert coverage["B级"]["total"] == 1 and coverage["B级"]["on_track"] == 1
        assert person["ungraded_customers"] == 1


def test_quality_uses_all_due_plans_and_excludes_snoozed_from_on_time(db):
    sales = make_user(db, "stats_quality")
    customer = make_customer(db, sales, "质量店")
    _roster(db, [sales])
    tasks = [
        ("todo", 0, None),
        ("done", 0, TODAY - timedelta(days=3)),
        ("done", 0, TODAY),
        ("done", 1, TODAY - timedelta(days=3)),
    ]
    for index, (status, snooze_count, closed_at) in enumerate(tasks):
        db.add(DomesticFollowupTask(
            task_type="plan", customer_id=customer.id, assignee_user_id=sales.id,
            source_key=f"stats-quality-{index}", title="约定跟进", due_date=TODAY - timedelta(days=2),
            status=status, snooze_count=snooze_count, closed_at=closed_at,
        ))
    db.flush()
    _record(db, sales, customer, TODAY, result="有效沟通")

    with followup_client(db, sales, permissions=SALES) as client:
        person = _personal(client).json()["data"]["people"][0]
        quality = person["quality"]["commitment"]
        assert quality["denominator"] == 4
        assert quality["numerator"] == 1
        assert quality["value"] == 0.25


def test_team_totals_deduplicate_customers_and_weight_effectiveness(db):
    manager = make_user(db, "stats_team_manager")
    first = make_user(db, "stats_team_a")
    second = make_user(db, "stats_team_b")
    shared = make_customer(db, first, "共同触达店")
    other = make_customer(db, second, "另一家店")
    _record(db, first, shared, TODAY, result="有效沟通")
    _record(db, second, shared, TODAY, result="未回复")
    _record(db, second, other, TODAY, result="未回复")
    _roster(db, [first, second])

    with followup_client(db, manager, permissions=MANAGER) as client:
        response = client.get("/api/domestic-followup/stats/team", params={
            "range": "custom", "date_from": START.isoformat(), "date_to": TODAY.isoformat(),
        })
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["kpis"]["count"] == 3
        assert data["kpis"]["reach"] == 2
        assert data["kpis"]["effective_rate"] == 0.3333  # API 比例统一保留四位小数
        assert len(data["people"]) == 2
        assert set(data["people"][0]["quality"]) == {"next_step", "commitment", "effective_progress"}

    coordinator = make_user(db, "stats_coordinator")
    with followup_client(db, coordinator, permissions=("domestic_followup:read", "domestic_followup:coordinate")) as client:
        assert client.get("/api/domestic-followup/stats/team").status_code == 403


def test_drilldown_keeps_record_visibility_and_result_filter(db):
    sales = make_user(db, "stats_drill")
    other = make_user(db, "stats_drill_other")
    mine = make_customer(db, sales, "下钻我的店")
    theirs = make_customer(db, other, "下钻他人店")
    _record(db, sales, mine, TODAY, result="未回复")
    _record(db, other, theirs, TODAY, result="未回复")
    _roster(db, [sales, other])

    with followup_client(db, sales, permissions=SALES) as client:
        response = client.get("/api/domestic-followup/stats/drilldown", params={
            "kind": "records", "result_code": "未回复", "date_from": TODAY.isoformat(), "date_to": TODAY.isoformat(),
        })
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["customer_id"] == mine.id


def test_missing_today_skips_sunday_and_configured_non_workday(db, monkeypatch):
    from app.domestic_followup import stats_service

    sales = make_user(db, "stats_missing")
    make_customer(db, sales, "未提交店")
    _roster(db, [sales])
    sunday = date(2026, 11, 8)
    monkeypatch.setattr(stats_service, "beijing_today", lambda: sunday)
    with followup_client(db, sales, permissions=SALES) as client:
        assert client.get("/api/domestic-followup/stats/missing-today").json()["data"]["applicable"] is False

    monday = date(2026, 11, 9)
    db.add(DomesticFollowupConfig(key="stats_non_workdays", value=[monday.isoformat()]))
    db.flush()
    monkeypatch.setattr(stats_service, "beijing_today", lambda: monday)
    with followup_client(db, sales, permissions=SALES) as client:
        assert client.get("/api/domestic-followup/stats/missing-today").json()["data"]["applicable"] is False
