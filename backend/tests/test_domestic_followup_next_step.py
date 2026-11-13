"""Next-step coverage uses all confirmed records, independent of outcome."""
from datetime import timedelta

import pytest

from app.domestic_followup import stats_service
from tests.domestic_followup_helpers import followup_client, make_customer, make_user
from tests.test_domestic_followup_stats import MANAGER, SALES, START, TODAY, _personal, _record, _roster


@pytest.mark.parametrize("result", [None, "未回复", "有效沟通"])
def test_next_step_counts_dates_without_requiring_positive_outcomes(db, monkeypatch, result):
    monkeypatch.setattr(stats_service, "beijing_today", lambda: TODAY)
    sales = make_user(db, "next_step_sales")
    other = make_user(db, "next_step_other")
    manager = make_user(db, "next_step_manager")
    customer = make_customer(db, sales, "下一步统计客户")
    _roster(db, [sales])
    planned = _record(db, sales, customer, TODAY, result=result, next_date=TODAY + timedelta(days=1))
    text_only = _record(db, sales, customer, TODAY, result=result)
    text_only.next_plan = "再次联系客户"
    _record(db, sales, customer, TODAY, result=result, next_date=TODAY, status="draft")
    _record(db, sales, customer, START - timedelta(days=1), result=result, next_date=TODAY)
    _record(db, other, customer, TODAY, result=result, next_date=TODAY)
    db.flush()
    params = {"range": "custom", "date_from": START.isoformat(), "date_to": TODAY.isoformat()}

    with followup_client(db, sales, permissions=SALES) as client:
        person = _personal(client).json()["data"]["people"][0]
        assert person["kpis"]["count"] == 2
        assert person["quality"]["next_step"] == {
            "label": "留下一步", "numerator": 1, "denominator": 2, "value": 0.5,
        }
        detail = client.get("/api/domestic-followup/stats/drilldown", params={
            "date_from": START.isoformat(), "date_to": TODAY.isoformat(), "quality": "next_step",
        }).json()["data"]
        assert detail["total"] == 1
        assert [row["id"] for row in detail["items"]] == [planned.id]

    with followup_client(db, manager, permissions=MANAGER) as client:
        data = client.get("/api/domestic-followup/stats/team", params=params).json()["data"]
        assert data["people"][0]["quality"]["next_step"]["value"] == 0.5


def test_next_step_distinguishes_no_records_from_no_plan(db, monkeypatch):
    monkeypatch.setattr(stats_service, "beijing_today", lambda: TODAY)
    sales = make_user(db, "next_step_empty")
    customer = make_customer(db, sales, "无计划客户")
    _roster(db, [sales])
    with followup_client(db, sales, permissions=SALES) as client:
        quality = _personal(client).json()["data"]["people"][0]["quality"]["next_step"]
        assert quality["value"] is None
        assert quality["denominator"] == 0
        _record(db, sales, customer, TODAY)
        quality = _personal(client).json()["data"]["people"][0]["quality"]["next_step"]
        assert quality["value"] == 0
        assert quality["numerator"] == 0
        assert quality["denominator"] == 1
