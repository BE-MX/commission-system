"""Overdue drawer grades apply inside the visible scope before pagination."""
from datetime import timedelta

import pytest

from app.domestic_followup import stats_service
from tests.domestic_followup_helpers import followup_client, make_customer, make_user
from tests.test_domestic_followup_stats import MANAGER, SALES, TODAY, _record, _roster


@pytest.fixture(autouse=True)
def fixed_business_day(monkeypatch):
    monkeypatch.setattr(stats_service, "beijing_today", lambda: TODAY)


def _seed(db):
    sales, other, outsider, manager = [make_user(db, name) for name in
                                       ("grade_sales", "grade_other", "grade_outsider", "grade_manager")]
    customers = []
    # Insert lower grades first and make them more overdue than the higher grades.
    for owner, level, name, age in (
        (sales, "C级", "C", 100), (sales, "B级", "B", 90),
        (sales, "A级", "A-Z", 60), (sales, "A级", "A-A", 60),
        (sales, "A级", "A-old", 70), (sales, "S级", "S", 20),
        (other, "S级", "team-S", 30), (outsider, "S级", "hidden-S", 100),
    ):
        customer = make_customer(db, owner, name, level=level)
        _record(db, owner, customer, TODAY - timedelta(days=age))
        customers.append(customer)
    _roster(db, [sales, other])
    return sales, other, outsider, manager, customers


@pytest.mark.parametrize("team", [False, True])
def test_grade_order_filter_total_and_pagination_follow_visible_scope(db, team):
    sales, other, outsider, manager, customers = _seed(db)
    actor, permissions = (manager, MANAGER) if team else (sales, SALES)
    with followup_client(db, actor, permissions=permissions) as client:
        base = "/api/domestic-followup/stats/drilldown?kind=overdue"
        response = client.get(base + "&page_size=2")
        assert response.status_code == 200
        first = response.json()["data"]
        assert first["total"] == (7 if team else 6)
        assert [row["shop_name"] for row in first["items"]] == (
            ["team-S", "S"] if team else ["S", "A-old"])
        all_rows = client.get(base + "&page_size=100").json()["data"]["items"]
        assert [row["shop_name"] for row in all_rows] == (
            (["team-S"] if team else []) + ["S", "A-old", "A-A", "A-Z", "B", "C"])
        filtered = client.get(base + "&customer_level=A级&page=2&page_size=2").json()["data"]
        assert filtered["total"] == 3
        assert [row["shop_name"] for row in filtered["items"]] == ["A-Z"]
        empty = client.get(base + f"&customer_level=C级&user_id={other.id if team else sales.id}").json()["data"]
        assert empty["total"] == (0 if team else 1)
        if not team:
            assert client.get(base + f"&user_id={other.id}&customer_level=S级").status_code == 403
        assert client.get(base + "&customer_level=invalid").status_code == 422


def test_drawer_sort_does_not_change_dashboard_preview(db):
    sales, *_ = _seed(db)
    claims = {"sub": str(sales.id), "permissions": list(SALES)}
    preview = stats_service.personal(db, claims)["people"][0]["overdue_customers"]
    assert preview[0]["level"] == "C级"
