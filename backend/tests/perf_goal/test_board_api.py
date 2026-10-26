"""看板 API：roster、overview 口径与状态、trend 累积、战队榜、排名、明细分页与数据范围。"""
from datetime import date

from app.perf_goal import statistics as stats
from tests.perf_goal.conftest import TODAY, become


def test_roster_shape(perf):
    s = perf
    data = s.client.get(f"{s.url}/roster").json()["data"]
    assert len(data["teams"]) == 2 and len(data["unassigned"]) == 1
    alpha = next(t for t in data["teams"] if t["department_id"] == 101)
    assert alpha["name"] == "阿尔法队" and alpha["captain_user_id"] == s.users[1].id
    assert alpha["captain_name"] == "毕晓珍"
    members = {m["user_id"]: m for m in alpha["members"]}
    assert members[s.users[1].id]["is_captain"] is True and members[s.users[1].id]["listed"] is True
    assert members[s.users[1].id]["okki_user_id"] == "90001"
    beta = next(t for t in data["teams"] if t["department_id"] == 102)
    beta_members = {m["user_id"]: m for m in beta["members"]}
    assert beta_members[s.users[4].id]["listed"] is False
    assert data["unassigned"][0]["user_id"] == s.users[5].id
    assert data["unassigned"][0]["listed"] is False


def test_overview_company_listed_only(perf):
    s = perf
    data = s.client.get(f"{s.url}/overview", params={
        "scope": "company", "period_type": "year", "year": 2026}).json()["data"]
    assert data["as_of"] == TODAY.isoformat() and data["period_label"] == "2026 年度"
    tp = stats.workday_time_progress(date(2026, 1, 1), date(2026, 12, 31), TODAY)
    assert data["time_progress"] == tp
    gmv = data["metrics"]["gmv"]
    # 只汇总 listed（users[1..3]）：4600/9000；users[4] 的 400 不计入
    assert gmv["target"] == 9000.0 and gmv["achieved"] == 4600.0
    assert gmv["rate"] == round(4600 / 9000, 4)
    assert gmv["delta_pp"] == round((gmv["rate"] - tp) * 100, 2)
    assert gmv["prev_rate"] is None and gmv["unit"] == "USD"
    new_sign = data["metrics"]["new_sign"]
    assert new_sign["target"] == 10 and new_sign["achieved"] == 2 and new_sign["rate"] == 0.2
    repeat = data["metrics"]["repeat_customers"]
    assert repeat["target"] is None and repeat["rate"] is None and repeat["achieved"] == 2
    assert data["metrics"]["repeat_amount"]["achieved"] == 2500.0
    warnings = data["warnings"]
    assert any(w["user_id"] == s.users[1].id and w["metric"] == "new_sign"
               and w["projected_rate"] < 0.8 and w["text"] for w in warnings)


def test_overview_person_and_team(perf):
    s = perf
    person = s.client.get(f"{s.url}/overview", params={
        "scope": "person", "scope_id": s.users[1].id, "period_type": "year"}).json()["data"]
    gmv = person["metrics"]["gmv"]
    assert gmv["target"] == 3000.0 and gmv["achieved"] == 1500.0 and gmv["rate"] == 0.5
    assert person["metrics"]["new_sign"]["target"] == 10
    team = s.client.get(f"{s.url}/overview", params={
        "scope": "team", "scope_id": 102, "period_type": "year"}).json()["data"]
    team_gmv = team["metrics"]["gmv"]
    # 战队 achieved 含未设目标成员 users[4] 的 400
    assert team_gmv["target"] == 4000.0 and team_gmv["achieved"] == 2400.0
    # 季度口径：Q1 目标缺省 → rate None，achieved 照算
    quarter = s.client.get(f"{s.url}/overview", params={
        "scope": "person", "scope_id": s.users[1].id, "period_type": "quarter",
        "year": 2026, "quarter": 1}).json()["data"]
    assert quarter["metrics"]["gmv"]["target"] is None
    assert quarter["metrics"]["gmv"]["achieved"] == 1500.0
    assert quarter["period_label"] == "2026 Q1"


def test_trend_year_cumulative_and_month_days(perf):
    s = perf
    data = s.client.get(f"{s.url}/trend", params={
        "scope": "person", "scope_id": s.users[1].id, "metric": "gmv",
        "period_type": "year", "year": 2026}).json()["data"]
    assert data["labels"] == [f"2026-{m:02d}" for m in range(1, 13)]
    assert data["cumulative_actual"][:6] == [1000.0, 1500.0, 1500.0, 1500.0, 1500.0, 1500.0]
    assert all(value is None for value in data["cumulative_actual"][6:])
    assert data["period_actual"][:3] == [1000.0, 500.0, 0.0]
    assert data["plan"][:3] == [250.0, 500.0, 750.0]
    assert all(value is None for value in data["plan"][6:])
    assert all(value is None for value in data["time_progress_line"][6:])
    month = s.client.get(f"{s.url}/trend", params={
        "scope": "person", "scope_id": s.users[1].id, "metric": "gmv",
        "period_type": "month", "year": 2026, "month": 1}).json()["data"]
    assert len(month["labels"]) == 31 and month["labels"][0] == "2026-01-01"
    assert month["cumulative_actual"][8] == 0.0 and month["cumulative_actual"][9] == 1000.0
    assert month["period_actual"][9] == 1000.0 and month["period_actual"][10] == 0.0
    new_sign = s.client.get(f"{s.url}/trend", params={
        "scope": "person", "scope_id": s.users[1].id, "metric": "new_sign",
        "period_type": "year", "year": 2026}).json()["data"]
    assert new_sign["cumulative_actual"][0] == 1 and new_sign["cumulative_actual"][5] == 1
    assert new_sign["plan"][6] is None  # 未来点为 null


def test_trend_plan_uses_monthly_split(perf):
    s = perf
    assert s.client.put(f"{s.url}/periods/{s.period.id}/goals", json={"rows": [
        {"user_id": s.users[1].id, "metric": "gmv", "granularity": "month",
         "quarter": 1, "month": m, "target_value": v}
        for m, v in ((1, "100"), (2, "200"), (3, "300"))]}).status_code == 200
    data = s.client.get(f"{s.url}/trend", params={
        "scope": "person", "scope_id": s.users[1].id, "metric": "gmv",
        "period_type": "year", "year": 2026}).json()["data"]
    assert data["plan"][:3] == [100.0, 300.0, 600.0]
    assert data["plan"][5] == 600.0 and data["plan"][6] is None


def test_teams_board_and_included_unlisted(perf):
    s = perf
    rows = s.client.get(f"{s.url}/teams", params={"period_type": "year"}).json()["data"]["rows"]
    assert len(rows) == 2
    beta = next(r for r in rows if r["department_id"] == 102)
    assert beta["team_name"] == "贝塔队" and beta["captain_name"] == "尹德魁"
    assert beta["member_count"] == 2
    assert beta["metrics"]["gmv"] == {"target": 4000.0, "achieved": 2400.0, "rate": 0.6}
    assert beta["overall_rate"] == 0.6
    assert beta["included_unlisted"] is True  # users[4] 无目标但有 400 成交
    alpha = next(r for r in rows if r["department_id"] == 101)
    assert alpha["included_unlisted"] is False
    members = {m["user_id"]: m for m in beta["members"]}
    assert members[s.users[3].id]["gmv_rate"] == 0.5
    assert members[s.users[4].id]["gmv_rate"] is None and members[s.users[4].id]["listed"] is False


def test_ranking(perf):
    s = perf
    rows = s.client.get(f"{s.url}/ranking", params={"period_type": "year"}).json()["data"]["rows"]
    assert len(rows) == 5
    by_user = {row["user_id"]: row for row in rows}
    assert by_user[s.users[2].id]["rank"] == 1
    assert by_user[s.users[2].id]["gmv"] == {"target": 2000.0, "achieved": 1100.0, "rate": 0.55}
    assert {by_user[s.users[1].id]["rank"], by_user[s.users[3].id]["rank"]} == {2, 3}
    assert by_user[s.users[4].id]["listed"] is False and by_user[s.users[4].id]["status"] == "no_target"
    assert by_user[s.users[4].id]["gmv"]["rate"] is None
    tp = stats.workday_time_progress(date(2026, 1, 1), date(2026, 12, 31), TODAY)
    assert by_user[s.users[2].id]["delta_pp"] == round((0.55 - tp) * 100, 2)
    assert by_user[s.users[2].id]["new_sign"]["achieved"] == 1
    asc = s.client.get(f"{s.url}/ranking", params={"sort": "gmv_rate", "order": "asc"}).json()["data"]["rows"]
    assert asc[0]["gmv"]["rate"] == 0.5 and asc[-1]["gmv"]["rate"] is None  # 升序时无目标者仍在最后
    assert s.client.get(f"{s.url}/ranking", params={"sort": "bogus"}).status_code == 422


def test_metric_orders_filters_pagination_summary(perf):
    s = perf
    data = s.client.get(f"{s.url}/metric-orders", params={
        "metric": "gmv", "page_size": 2, "page": 1}).json()["data"]
    assert data["total"] == 6 and len(data["items"]) == 2
    assert data["summary"] == {"order_count": 6, "amount_usd": 5000.0, "customer_count": 5}
    page3 = s.client.get(f"{s.url}/metric-orders", params={
        "metric": "gmv", "page_size": 2, "page": 3}).json()["data"]
    assert page3["total"] == 6 and len(page3["items"]) == 2 and page3["summary"]["order_count"] == 6
    first = data["items"][0]
    assert first["order_id"] == "1004"  # 日期倒序：2026-03-05 最新
    assert first["customer_name"] == "客户三" and first["country"] == "德国"
    assert first["owner_user_id"] == s.users[2].id and first["owner_name"] == "代晴玉"
    assert first["flags"] == []
    new_sign = s.client.get(f"{s.url}/metric-orders", params={"metric": "new_sign"}).json()["data"]
    assert new_sign["total"] == 3 and new_sign["summary"]["customer_count"] == 3
    assert {item["order_id"] for item in new_sign["items"]} == {"1001", "1003", "1006"}
    assert "new_sign" in new_sign["items"][0]["flags"]
    repeat = s.client.get(f"{s.url}/metric-orders", params={"metric": "repeat_amount"}).json()["data"]
    assert repeat["total"] == 2 and repeat["summary"]["amount_usd"] == 2500.0
    assert repeat["summary"]["customer_count"] == 2
    ranged = s.client.get(f"{s.url}/metric-orders", params={
        "metric": "gmv", "date_from": "2026-02-01"}).json()["data"]
    assert ranged["total"] == 3 and ranged["summary"]["amount_usd"] == 1200.0
    assert s.client.get(f"{s.url}/metric-orders", params={
        "metric": "gmv", "date_from": "2026-03-01", "date_to": "2026-01-01"}).status_code == 422
    assert s.client.get(f"{s.url}/metric-orders", params={"metric": "bogus"}).status_code == 422


def test_salesperson_scope_restrictions(perf):
    s = perf
    become(s, 2)  # 业务员：仅本人
    assert s.client.get(f"{s.url}/teams").status_code == 403
    assert s.client.get(f"{s.url}/ranking").status_code == 403
    assert s.client.get(f"{s.url}/overview", params={"scope": "company"}).status_code == 403
    assert s.client.get(f"{s.url}/overview", params={"scope": "team", "scope_id": 101}).status_code == 403
    assert s.client.get(f"{s.url}/overview", params={
        "scope": "person", "scope_id": s.users[1].id}).status_code == 403
    mine = s.client.get(f"{s.url}/overview", params={
        "scope": "person", "scope_id": s.users[2].id}).json()["data"]
    assert mine["metrics"]["gmv"]["achieved"] == 1100.0
    orders = s.client.get(f"{s.url}/metric-orders", params={"metric": "gmv"}).json()["data"]
    assert orders["total"] == 2 and orders["summary"]["amount_usd"] == 1100.0
    assert s.client.get(f"{s.url}/metric-orders", params={
        "metric": "gmv", "user_id": s.users[1].id}).status_code == 403
    assert s.client.get(f"{s.url}/metric-orders", params={
        "metric": "gmv", "department_id": 101}).status_code == 403


def test_captain_scope_restrictions(perf):
    s = perf
    become(s, 1)  # 队长：本人 + 本队
    teams = s.client.get(f"{s.url}/teams").json()["data"]["rows"]
    assert len(teams) == 1 and teams[0]["department_id"] == 101
    ranking = s.client.get(f"{s.url}/ranking").json()["data"]["rows"]
    assert {row["user_id"] for row in ranking} == {s.users[1].id, s.users[2].id}
    assert s.client.get(f"{s.url}/overview", params={"scope": "company"}).status_code == 403
    assert s.client.get(f"{s.url}/overview", params={"scope": "team", "scope_id": 102}).status_code == 403
    team = s.client.get(f"{s.url}/overview", params={"scope": "team", "scope_id": 101}).json()["data"]
    assert team["metrics"]["gmv"]["achieved"] == 2600.0
    orders = s.client.get(f"{s.url}/metric-orders", params={"metric": "gmv"}).json()["data"]
    assert orders["total"] == 4
    member_orders = s.client.get(f"{s.url}/metric-orders", params={
        "metric": "gmv", "user_id": s.users[2].id}).json()["data"]
    assert member_orders["total"] == 2
    assert s.client.get(f"{s.url}/metric-orders", params={
        "metric": "gmv", "user_id": s.users[3].id}).status_code == 403


def test_management_reads_all(perf):
    s = perf
    become(s, 0, ("perf_goal:read",), roles=("supervisor",))
    assert s.client.get(f"{s.url}/overview", params={"scope": "company"}).status_code == 200
    assert len(s.client.get(f"{s.url}/teams").json()["data"]["rows"]) == 2
    assert len(s.client.get(f"{s.url}/ranking").json()["data"]["rows"]) == 5
    assert s.client.get(f"{s.url}/metric-orders", params={"metric": "gmv"}).json()["data"]["total"] == 6
