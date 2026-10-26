"""2026 种子：数据合计校验、幂等与战队自动汇总。"""
from decimal import Decimal

from app.perf_goal.models import PerfGoal, PerfGoalTeamOverride
from app.perf_goal.seed import SEED_2026, run_seed


def test_seed_data_totals_match_excel():
    assert len(SEED_2026) == 20
    assert sum(Decimal(gmv) for _name, gmv, _ns in SEED_2026) == Decimal("15697000")
    assert sum(ns for _name, _gmv, ns in SEED_2026) == 998


def test_run_seed_dry_run_apply_and_idempotent(db, perf):
    dry = run_seed(db, apply=False)
    assert dry["applied"] is False and dry["period_created"] is False
    assert dry["period_id"] == perf.period.id
    # 毕晓珍/代晴玉/尹德魁/罗馨瑜 在测试战队配置中有绑定
    assert dry["users_planned"] == 4 and len(dry["warnings"]) == 16
    assert db.query(PerfGoal).filter_by(period_id=perf.period.id).count() == 4

    applied = run_seed(db, apply=True)
    # fixture 已有 users[1] 两项与 users[2]/users[3] 的 gmv；
    # 补 users[2]/users[3] 的新签 + users[4]（罗馨瑜）两项
    assert applied["goals_written"] == 4
    assert applied["team_rows_written"] == 4  # 2 个战队 × (gmv + new_sign)
    goals = {(row.user_id, row.metric): row for row in
             db.query(PerfGoal).filter_by(period_id=perf.period.id, granularity="year").all()}
    # 既有目标不被种子覆盖（fixture users[3] gmv=4000 ≠ 种子 1170000）
    assert Decimal(goals[(perf.users[3].id, "gmv")].target_value) == Decimal("4000")
    assert Decimal(goals[(perf.users[2].id, "new_sign")].target_value) == Decimal("52")
    assert Decimal(goals[(perf.users[4].id, "gmv")].target_value) == Decimal("166000")
    teams = {(row.department_id, row.metric): row for row in
             db.query(PerfGoalTeamOverride).filter_by(period_id=perf.period.id).all()}
    # 战队汇总按种子值（而非 fixture 既有目标）计算 auto
    assert Decimal(teams[(101, "gmv")].auto_value) == Decimal("4000000")
    assert Decimal(teams[(101, "new_sign")].auto_value) == Decimal("77")
    assert Decimal(teams[(102, "gmv")].effective_value) == Decimal("1336000")
    assert Decimal(teams[(102, "new_sign")].auto_value) == Decimal("107")
    assert all(row.stale is False for row in teams.values())

    again = run_seed(db, apply=True)
    assert again["goals_written"] == 0 and again["team_rows_written"] == 0
    assert again["period_created"] is False
