"""目标设置 API：批次、CRUD+版本+审计、拆分权重、战队 auto/factor/override/recalc/stale。"""
from tests.perf_goal.conftest import become


def _goals_url(s, suffix=""):
    return f"{s.url}/periods/{s.period.id}/goals{suffix}"


def test_period_lifecycle(perf):
    s = perf
    rows = s.client.get(f"{s.url}/periods").json()["data"]
    assert len(rows) == 1 and rows[0]["status"] == "active" and rows[0]["year"] == 2026
    active = s.client.get(f"{s.url}/periods/active").json()["data"]
    assert active["id"] == s.period.id and active["version"] == 1
    created = s.client.post(f"{s.url}/periods", json={"year": 2027, "name": "2027 年度目标"})
    assert created.status_code == 200, created.text
    new_id = created.json()["data"]["id"]
    assert created.json()["data"]["status"] == "draft"
    assert s.client.post(f"{s.url}/periods", json={"year": 2027, "name": "2027 年度目标"}).status_code == 409
    assert s.client.post(f"{s.url}/periods/{new_id}/activate").status_code == 200
    periods = s.client.get(f"{s.url}/periods").json()["data"]
    by_id = {row["id"]: row for row in periods}
    assert by_id[new_id]["status"] == "active" and by_id[s.period.id]["status"] == "archived"
    assert by_id[new_id]["published_by"] == s.users[0].id
    assert s.client.get(f"{s.url}/periods/active").json()["data"]["id"] == new_id
    # 归档批次禁止改目标
    response = s.client.put(_goals_url(s), json={"rows": [
        {"user_id": s.users[1].id, "metric": "gmv", "granularity": "year", "target_value": "100"}]})
    assert response.status_code == 409


def test_goals_upsert_version_and_audits(perf):
    s = perf
    payload = {"rows": [
        {"user_id": s.users[4].id, "metric": "gmv", "granularity": "year", "target_value": "1500.5"},
        {"user_id": s.users[4].id, "metric": "new_sign", "granularity": "year", "target_value": "20"},
    ], "reason": "首年录入"}
    result = s.client.put(_goals_url(s), json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["data"] == {"version": 2, "audit_count": 2}
    rows = s.client.get(_goals_url(s), params={"granularity": "year"}).json()["data"]["rows"]
    mine = [row for row in rows if row["user_id"] == s.users[4].id]
    assert {row["metric"] for row in mine} == {"gmv", "new_sign"}
    assert next(row for row in mine if row["metric"] == "gmv")["target_value"] == 1500.5
    # 新签为计数指标：保存时量化为整数
    result = s.client.put(_goals_url(s), json={"rows": [
        {"user_id": s.users[4].id, "metric": "gmv", "granularity": "year", "target_value": "1800"},
        {"user_id": s.users[4].id, "metric": "new_sign", "granularity": "year", "target_value": "20"},
    ]})
    assert result.json()["data"] == {"version": 3, "audit_count": 1}
    audits = s.client.get(f"{s.url}/periods/{s.period.id}/audits").json()["data"]
    assert len(audits) == 3
    changed = next(a for a in audits if a["new_value"] == "1800.00")
    assert changed["old_value"] == "1500.50" and changed["object_type"] == "person_goal"
    assert changed["object_label"] == "罗馨瑜" and changed["field"] == "gmv:year"
    assert changed["operator_name"] == "管理员"
    first = next(a for a in audits if a["reason"] == "首年录入")
    assert first["old_value"] is None


def test_goals_validation(perf):
    s = perf
    bad_rows = [
        [{"user_id": s.users[1].id, "metric": "gmv", "granularity": "year", "quarter": 1, "target_value": "1"}],
        [{"user_id": s.users[1].id, "metric": "gmv", "granularity": "quarter", "target_value": "1"}],
        [{"user_id": s.users[1].id, "metric": "gmv", "granularity": "month", "quarter": 1, "month": 4, "target_value": "1"}],
        [{"user_id": s.users[1].id, "metric": "gmv", "granularity": "year", "target_value": "1"},
         {"user_id": s.users[1].id, "metric": "gmv", "granularity": "year", "target_value": "2"}],
        [{"user_id": s.users[1].id, "metric": "gmv", "granularity": "year", "target_value": "-1"}],
        [{"user_id": 999999, "metric": "gmv", "granularity": "year", "target_value": "1"}],
    ]
    for rows in bad_rows:
        assert s.client.put(_goals_url(s), json={"rows": rows}).status_code == 422, rows


def test_split_preview_and_apply_with_remainder(perf):
    s = perf
    preview = s.client.post(f"{s.url}/periods/{s.period.id}/split", json={
        "metric": "gmv", "source": "year", "target": "quarter",
        "weights": ["1", "1", "1", "3"], "user_ids": [s.users[2].id], "apply": False})
    assert preview.status_code == 200, preview.text
    data = preview.json()["data"]
    assert data["applied"] is False and len(data["preview"]) == 1
    entries = data["preview"][0]["entries"]
    assert [e["quarter"] for e in entries] == [1, 2, 3, 4]
    # 2000 × [1,1,1,3]：前三个 333.33，尾槽兜底余数 1000.01，合计=源值
    values = [e["new_value"] for e in entries]
    assert values[:3] == [333.33, 333.33, 333.33] and values[3] == 1000.01
    assert round(sum(values), 2) == 2000.00
    assert all(e["old_value"] is None for e in entries)
    assert not s.client.get(_goals_url(s), params={"granularity": "quarter"}).json()["data"]["rows"]
    applied = s.client.post(f"{s.url}/periods/{s.period.id}/split", json={
        "metric": "gmv", "source": "year", "target": "quarter",
        "weights": ["1", "1", "1", "3"], "user_ids": [s.users[2].id], "apply": True})
    assert applied.json()["data"]["applied"] is True
    rows = s.client.get(_goals_url(s), params={"granularity": "quarter"}).json()["data"]["rows"]
    assert len(rows) == 4 and all(row["user_id"] == s.users[2].id for row in rows)
    again = s.client.post(f"{s.url}/periods/{s.period.id}/split", json={
        "metric": "gmv", "source": "year", "target": "quarter",
        "weights": ["1", "1", "1", "3"], "user_ids": [s.users[2].id], "apply": False})
    entries = again.json()["data"]["preview"][0]["entries"]
    assert entries[0]["old_value"] == 333.33


def test_split_quarter_to_month(perf):
    s = perf
    assert s.client.post(f"{s.url}/periods/{s.period.id}/split", json={
        "metric": "gmv", "source": "year", "target": "quarter",
        "weights": ["1", "1", "1", "1"], "user_ids": [s.users[1].id], "apply": True}).status_code == 200
    result = s.client.post(f"{s.url}/periods/{s.period.id}/split", json={
        "metric": "gmv", "source": "quarter", "target": "month",
        "weights": ["1", "1", "1"], "user_ids": [s.users[1].id], "apply": True})
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert data["applied"] is True
    months = s.client.get(_goals_url(s), params={"granularity": "month"}).json()["data"]["rows"]
    assert len(months) == 12 and all(row["target_value"] == 250.0 for row in months)
    jan = next(row for row in months if row["month"] == 1)
    assert jan["quarter"] == 1
    # 权重个数与拆分方向校验
    assert s.client.post(f"{s.url}/periods/{s.period.id}/split", json={
        "metric": "gmv", "source": "year", "target": "quarter",
        "weights": ["1", "1", "1"], "apply": False}).status_code == 422
    assert s.client.post(f"{s.url}/periods/{s.period.id}/split", json={
        "metric": "gmv", "source": "year", "target": "month",
        "weights": ["1", "1", "1"], "apply": False}).status_code == 422


def test_team_goals_auto_factor_override_recalc_stale(perf):
    s = perf
    url = f"{s.url}/periods/{s.period.id}/team-goals"
    rows = s.client.get(url, params={"granularity": "year"}).json()["data"]["rows"]
    by_key = {(r["department_id"], r["metric"]): r for r in rows}
    alpha_gmv = by_key[(101, "gmv")]
    assert alpha_gmv["auto_value"] == 5000.0 and alpha_gmv["factor"] == 1.0
    assert alpha_gmv["override_value"] is None and alpha_gmv["effective_value"] == 5000.0
    assert alpha_gmv["team_name"] == "阿尔法队" and alpha_gmv["captain_name"] == "毕晓珍"
    assert alpha_gmv["member_count"] == 2 and alpha_gmv["stale"] is False
    assert by_key[(102, "gmv")]["auto_value"] == 4000.0
    assert by_key[(101, "new_sign")]["auto_value"] == 10
    assert (102, "new_sign") not in by_key  # 无成员目标的指标不出行
    # factor 调整 + override 微调
    result = s.client.put(url, json={"rows": [
        {"department_id": 101, "metric": "gmv", "granularity": "year", "factor": "1.2"}]})
    assert result.status_code == 200, result.text
    row = next(r for r in s.client.get(url, params={"granularity": "year"}).json()["data"]["rows"]
               if r["department_id"] == 101 and r["metric"] == "gmv")
    assert row["factor"] == 1.2 and row["effective_value"] == 6000.0
    assert s.client.put(url, json={"rows": [
        {"department_id": 101, "metric": "gmv", "granularity": "year", "override_value": "5500"}]}).status_code == 200
    row = next(r for r in s.client.get(url, params={"granularity": "year"}).json()["data"]["rows"]
               if r["department_id"] == 101 and r["metric"] == "gmv")
    assert row["override_value"] == 5500.0 and row["effective_value"] == 5500.0
    # 成员目标变更 → 待重算角标
    assert s.client.put(_goals_url(s), json={"rows": [
        {"user_id": s.users[2].id, "metric": "gmv", "granularity": "year", "target_value": "2200"}]}).status_code == 200
    row = next(r for r in s.client.get(url, params={"granularity": "year"}).json()["data"]["rows"]
               if r["department_id"] == 101 and r["metric"] == "gmv")
    assert row["stale"] is True and row["auto_value"] == 5200.0
    # 一键重算：auto 刷新、stale 清除、factor/override 保留
    recalc = s.client.post(f"{url}/recalc")
    assert recalc.status_code == 200 and recalc.json()["data"]["updated"] >= 3
    row = next(r for r in s.client.get(url, params={"granularity": "year"}).json()["data"]["rows"]
               if r["department_id"] == 101 and r["metric"] == "gmv")
    assert row["stale"] is False and row["auto_value"] == 5200.0
    assert row["override_value"] == 5500.0 and row["effective_value"] == 5500.0
    audits = s.client.get(f"{s.url}/periods/{s.period.id}/audits").json()["data"]
    assert any(a["object_type"] == "team_goal" and a["field"] == "factor:year" for a in audits)
    assert s.client.put(url, json={"rows": [
        {"department_id": 999, "metric": "gmv", "granularity": "year", "factor": "1.1"}]}).status_code == 422


def test_write_endpoints_require_write_permission(perf):
    s = perf
    become(s, 2)  # 只有 perf_goal:read
    assert s.client.put(_goals_url(s), json={"rows": []}).status_code == 403
    assert s.client.post(f"{s.url}/periods", json={"year": 2027, "name": "x"}).status_code == 403
    assert s.client.post(f"{s.url}/periods/{s.period.id}/activate").status_code == 403
    assert s.client.post(f"{s.url}/periods/{s.period.id}/split", json={
        "metric": "gmv", "source": "year", "target": "quarter", "weights": ["1", "1", "1", "1"]}).status_code == 403
    assert s.client.put(f"{s.url}/periods/{s.period.id}/team-goals", json={"rows": [
        {"department_id": 101, "metric": "gmv", "granularity": "year", "factor": "1.1"}]}).status_code == 403
    assert s.client.post(f"{s.url}/periods/{s.period.id}/team-goals/recalc").status_code == 403
    assert s.client.get(f"{s.url}/config").status_code == 403
    # 读端点放行
    assert s.client.get(f"{s.url}/periods").status_code == 200
    assert s.client.get(f"{s.url}/roster").status_code == 200
