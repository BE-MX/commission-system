"""薪资主数据种子（幂等 upsert）：职级薪级表 / 规则参数 / 部门映射。

三张表都带 effective_from/effective_to 版本列，种子只负责铺**当前生效版本**，
后续调整由 HR 在规则页新建版本，不回来改这里。因此 upsert 的键是
(scheme, grade_code, effective_from) 与 (param_key, effective_from)——
同一生效日重复导入是刷新，不同生效日是并存的两个版本。

数据来源（2026-07-29 材料包四张规则图，有效期「2026/04/01-更新新版本为止」）：
- 外贸业务员分配资源晋升规则.png  → scheme=resource
- 外贸业务员开发晋升规则.png      → scheme=develop
- 跟单晋升机制.png                → scheme=merch(F1~F6) + merch_manage(M1~M3)
业务员管理岗 M1~M6 两条赛道数值相同、只有团队提成率不同，归到 scheme=manage，
团队提成率差异（resource 1.0% / develop 1.5%）落在 rule_param，不拆两套职级表。
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.salary.models import SalaryDeptMapping, SalaryGradeTable, SalaryRuleParam

logger = logging.getLogger("commission")

# 四张规则图共同标注的生效日
EFFECTIVE_FROM = dt.date(2026, 4, 1)


def _d(v: Optional[float]) -> Optional[Decimal]:
    return None if v is None else Decimal(str(v))


# ── 职级薪级表 ────────────────────────────────────────────
# (grade_code, base_salary, perf_target_monthly, new_sign_min)
# perf_target_monthly 为美元月均业绩标准，new_sign_min 为月均新签客户数下限。
_RESOURCE_P = [
    ("P1", 3500, 3500, 6),
    ("P2", 4000, 10000, 6),
    ("P3", 4500, 15000, 6),
    ("P4", 5000, 20000, 5),
    ("P5", 5500, 30000, 5),
    ("P6", 6000, 40000, 5),
    ("P7", 6500, 50000, 4),
    ("P8", 7000, 60000, 4),
    ("P9", 8000, 80000, 4),
    ("P10", 10000, 100000, 4),
]

_DEVELOP_P = [
    ("P1", 4000, 3500, 4),
    ("P2", 4500, 10000, 4),
    ("P3", 5000, 15000, 4),
    ("P4", 5500, 20000, 3),
    ("P5", 6000, 30000, 3),
    ("P6", 6500, 40000, 3),
    ("P7", 7000, 50000, 2),
    ("P8", 8000, 60000, 2),
    ("P9", 10000, 80000, 2),
    ("P10", 12000, 100000, 2),
]

# 业务员管理岗：两条赛道数值一致（标准工资 / 半年月均业绩），团队提成率不同见 rule_param
# (grade_code, std_salary, perf_target_monthly)
_MANAGE_M = [
    ("M1", 5000, 15000),
    ("M2", 5500, 25000),
    ("M3", 6000, 35000),
    ("M4", 6500, 40000),
    ("M5", 8000, 50000),
    ("M6", 10000, 60000),
]

# 跟单：F1~F6 底薪按季度月均业绩晋升
_MERCH_F = [
    ("F1", 4000, 30000),
    ("F2", 4500, 60000),
    ("F3", 5000, 90000),
    ("F4", 5500, 120000),
    ("F5", 6000, 150000),
    ("F6", 6500, 180000),
]

# 跟单管理岗 M1~M3：阶梯底薪按半年月均业绩
_MERCH_MANAGE_M = [
    ("M1", 5000, 90000),
    ("M2", 6000, 120000),
    ("M3", 8000, 150000),
]


def _grade_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for code, base, target, new_min in _RESOURCE_P:
        rows.append(
            dict(scheme="resource", grade_code=code, base_salary=_d(base),
                 perf_target_monthly=_d(target), new_sign_min=new_min)
        )
    for code, base, target, new_min in _DEVELOP_P:
        rows.append(
            dict(scheme="develop", grade_code=code, base_salary=_d(base),
                 perf_target_monthly=_d(target), new_sign_min=new_min)
        )
    for code, std, target in _MANAGE_M:
        rows.append(
            dict(scheme="manage", grade_code=code, std_salary=_d(std),
                 perf_target_monthly=_d(target))
        )
    for code, base, target in _MERCH_F:
        rows.append(
            dict(scheme="merch", grade_code=code, base_salary=_d(base),
                 perf_target_monthly=_d(target))
        )
    for code, base, target in _MERCH_MANAGE_M:
        rows.append(
            dict(scheme="merch_manage", grade_code=code, base_salary=_d(base),
                 perf_target_monthly=_d(target), team_rate=_d(0.001))
        )
    return rows


# ── 规则参数 ──────────────────────────────────────────────
# (param_key, param_value, value_type, category, description)
_RULE_PARAMS: list[tuple[str, str, str, str, str]] = [
    # 考勤折算
    ("day_hours", "7.83", "decimal", "attendance",
     "日折算工时：请假小时 ÷ 7.83 = 缺勤天数（3 月表实证口径）"),
    ("full_month_days", "31", "int", "attendance",
     "满月员工的应出天数基准，固定 31 天（决策 B1）。"
     "注意与 mid_month_weight_base=30 是两个不同用途的参数，不是笔误"),
    ("mid_month_weight_base", "30", "int", "salary",
     "月中调薪/转正的底薪按天加权基数，固定 30 天（决策 B2）。"
     "只用于底薪加权；工龄/全勤/绩效目标按月末档案取，不加权。"
     "与 full_month_days=31 分离不是笔误：一个是出勤基准，一个是计薪加权基准"),
    ("min_actual_days_for_full_base", "15", "decimal", "attendance",
     "实出天数低于此值时，应出天数改取当月工作日数而非 full_month_days"),
    # 全勤
    ("attendance_bonus", "100", "decimal", "attendance", "全勤奖金额（元/月）"),
    ("attendance_sick_hours_max", "8", "decimal", "attendance",
     "病假不破全勤的上限小时数，超过即无全勤"),
    ("annual_leave_breaks_attendance", "false", "bool", "attendance",
     "年假是否破全勤。决策 B3=否。留参数是给 HR 反悔的口子"),
    # 病假折算
    ("sick_pay_deduct_ratio", "0.30", "decimal", "attendance",
     "病假扣减比例：病假时长按 30% 折算成缺勤（决策 B3）。"
     "等价于病假期间发 70% 工资，实现上走扣减而非另起一条发放项"),
    # 工龄
    ("seniority_step", "200", "decimal", "seniority", "工龄工资：每满一年 200 元"),
    ("seniority_cap", "2000", "decimal", "seniority", "工龄工资上限（元）"),
    # 团队提成参考率（职级表不拆两套，费率差异落这里）
    ("team_rate_resource", "0.010", "decimal", "commission",
     "分配资源赛道管理岗团队提成参考率 1.0%"),
    ("team_rate_develop", "0.015", "decimal", "commission",
     "开发赛道管理岗团队提成参考率 1.5%"),
    ("team_rate_merch", "0.001", "decimal", "commission",
     "跟单管理岗团队提成参考率 0.1%"),
    # 舍入
    ("net_salary_rounding", "1", "int", "salary",
     "实发工资舍入到的单位（元）。3 月表口径为四舍五入到元"),
]


# ── 明细部门 → 汇总大部门 ─────────────────────────────────
# 取自 2026 年 3 月工资表实际配对。'跟单1部' 在源表里同时出现两种归属
# （6 人后综部 + 吕德洋业务总监归业务部）——映射表按多数口径落后综部，
# 吕德洋走档案的 dept_group_override，不为一个人拆明细部门。
_DEPT_MAPPINGS: list[tuple[str, str, int]] = [
    ("开发部", "业务部", 10),
    ("阿里部", "业务部", 20),
    ("跟单1部", "后综部", 30),
    ("跟单2部", "后综部", 40),
    ("外贸跟单部", "后综部", 50),
    ("社媒运营部", "后综部", 60),
    ("阿里运营部", "后综部", 70),
    ("亚马逊运营部", "后综部", 80),
    ("TK运营部", "后综部", 90),
    ("设计部", "后综部", 100),
    ("技术部", "后综部", 110),
    ("人资部", "后综部", 120),
]


def seed_grade_table(db: Session) -> int:
    """upsert 职级薪级表当前版本。键 = (scheme, grade_code, effective_from)。"""
    existing = {
        (r.scheme, r.grade_code): r
        for r in db.query(SalaryGradeTable)
        .filter(SalaryGradeTable.effective_from == EFFECTIVE_FROM)
        .all()
    }
    changed = 0
    for row in _grade_rows():
        key = (row["scheme"], row["grade_code"])
        obj = existing.get(key)
        if obj is None:
            db.add(SalaryGradeTable(effective_from=EFFECTIVE_FROM, **row))
            changed += 1
            continue
        for field in ("base_salary", "std_salary", "perf_full",
                      "perf_target_monthly", "new_sign_min", "team_rate"):
            new = row.get(field)
            if new is not None and getattr(obj, field) != new:
                setattr(obj, field, new)
                changed += 1
    return changed


def seed_rule_params(db: Session) -> int:
    """upsert 规则参数当前版本。已存在的键只刷元数据，不覆盖 HR 改过的值。

    param_value 存量不覆盖是刻意的：参数是给 HR 调的，种子只保证「有」，
    不保证「等于代码里的默认」。要强制回默认得在规则页手动改。
    """
    existing = {
        r.param_key: r
        for r in db.query(SalaryRuleParam)
        .filter(SalaryRuleParam.effective_from == EFFECTIVE_FROM)
        .all()
    }
    changed = 0
    for key, value, vtype, category, desc in _RULE_PARAMS:
        obj = existing.get(key)
        if obj is None:
            db.add(SalaryRuleParam(
                param_key=key, param_value=value, value_type=vtype,
                category=category, description=desc, effective_from=EFFECTIVE_FROM,
            ))
            changed += 1
            continue
        if obj.value_type != vtype or obj.category != category or obj.description != desc:
            obj.value_type, obj.category, obj.description = vtype, category, desc
            changed += 1
    return changed


def seed_dept_mappings(db: Session) -> int:
    """upsert 明细部门 → 大部门映射。dept_detail 唯一，已存在则不覆盖 HR 的调整。"""
    existing = {r.dept_detail: r for r in db.query(SalaryDeptMapping).all()}
    changed = 0
    for detail, group, order in _DEPT_MAPPINGS:
        if detail not in existing:
            db.add(SalaryDeptMapping(dept_detail=detail, dept_group=group, sort_order=order))
            changed += 1
    return changed


def seed_salary_master_data(db: Session) -> None:
    """三张主数据表的统一入口。启动期调用，幂等。"""
    n = seed_grade_table(db) + seed_rule_params(db) + seed_dept_mappings(db)
    db.commit()
    if n:
        logger.info("Salary master data seeded: %d rows touched", n)
