"""2026 年度目标种子：GMV 与新签两项真实年度目标（复购指标留管理员设置）。

人名 → OKKI user_id 走战队配置（sys_dict，空库回落 DEFAULT_TEAMS），
OKKI → 方舟账号走 ark_user_external_bindings(provider='okki')。
幂等：批次/目标行/战队汇总行已存在时跳过，重复运行不重复写入。
"""
import logging
from decimal import Decimal

from sqlalchemy.orm import Session

from app.auth.models import ArkRole, ArkUser
from app.core.time import beijing_now
from app.dingtalk.gmv_daily_config import load_config as load_team_config, okki_user_bindings
from app.perf_goal.models import PerfGoal, PerfGoalPeriod, PerfGoalTeamOverride

logger = logging.getLogger(__name__)

# (姓名, GMV 年度目标 USD, 新签年度目标 个) — 口径同《2026年度目标完成情况_截至9月.xlsx》主名单。
SEED_2026: list[tuple[str, str, int]] = [
    ("毕晓珍", "3100000", 25), ("李宝珠", "2440000", 26), ("尹德魁", "1170000", 30),
    ("夏新月", "1100000", 14), ("翟佳盟", "730000", 39), ("宋化通", "780000", 53),
    ("刘琳琳", "900000", 40), ("田雯", "615000", 74), ("宋皓月", "750000", 36),
    ("周露露", "500000", 60), ("潘康衡", "370000", 70), ("张砚斐", "490000", 53),
    ("代晴玉", "900000", 52), ("刘源", "490000", 55), ("刘行行", "360000", 46),
    ("张笑", "290000", 50), ("高瑞杰", "195000", 74), ("曲冉", "270000", 52),
    ("罗馨瑜", "166000", 77), ("胡宁宁", "81000", 72),
]

PERIOD_NAME = "2026 年度目标"


def _operator_id(db: Session) -> int:
    row = (db.query(ArkUser).join(ArkUser.roles)
           .filter(ArkRole.name == "super_admin", ArkUser.is_active.is_(True),
                   ArkUser.deleted_at.is_(None))
           .order_by(ArkUser.id).first())
    return row.id if row else 1


def _name_to_okki(db: Session) -> dict[str, str]:
    config = load_team_config(db)
    mapping: dict[str, str] = {}
    for team in config["teams"]:
        for member in team["members"]:
            mapping.setdefault(member["name"], str(member["okki_user_id"]))
    return mapping


def run_seed(db: Session, year: int = 2026, apply: bool = False) -> dict:
    """返回执行摘要；apply=False 时只计划不写入。"""
    now = beijing_now()
    operator = _operator_id(db)
    name_to_okki = _name_to_okki(db)
    bindings = okki_user_bindings(db)
    warnings: list[str] = []
    plan: list[tuple[int, str, Decimal, Decimal]] = []
    for name, gmv, new_sign in SEED_2026:
        okki_id = name_to_okki.get(name)
        bound = bindings.get(okki_id) if okki_id else None
        if bound is None:
            warnings.append(f"{name}: 未找到 OKKI 绑定（okki_user_id={okki_id or '未知'}），已跳过")
            continue
        plan.append((bound["ark_user_id"], name, Decimal(gmv), Decimal(new_sign)))

    period = (db.query(PerfGoalPeriod)
              .filter(PerfGoalPeriod.year == year, PerfGoalPeriod.name == PERIOD_NAME).first())
    period_created = False
    if period is None:
        if apply:
            period = PerfGoalPeriod(year=year, name=PERIOD_NAME, status="active",
                                    published_by=operator, published_at=now, created_by=operator)
            db.add(period)
            db.flush()
            period_created = True
        else:
            period = PerfGoalPeriod(id=-1, year=year, name=PERIOD_NAME)

    existing: set[tuple] = set()
    if period.id and period.id > 0:
        existing = {(row.user_id, row.metric)
                    for row in db.query(PerfGoal).filter(PerfGoal.period_id == period.id,
                                                         PerfGoal.granularity == "year").all()}
    goals_written = 0
    if apply:
        for user_id, _name, gmv, new_sign in plan:
            for metric, value in (("gmv", gmv), ("new_sign", new_sign)):
                if (user_id, metric) in existing:
                    continue
                db.add(PerfGoal(period_id=period.id, user_id=user_id, metric=metric,
                                granularity="year", quarter=None, month=None,
                                target_value=value, updated_by=operator, updated_at=now))
                goals_written += 1

    teams_written = 0
    if apply:
        config = load_team_config(db)
        team_sums: dict[int, dict[str, Decimal]] = {}
        member_team: dict[int, int] = {}
        for team in config["teams"]:
            if not team.get("is_active", True):
                continue
            for member in team["members"]:
                bound = bindings.get(str(member["okki_user_id"]))
                if bound:
                    member_team[bound["ark_user_id"]] = team["department_id"]
        for user_id, _name, gmv, new_sign in plan:
            department_id = member_team.get(user_id)
            if department_id is None:
                continue
            sums = team_sums.setdefault(department_id, {"gmv": Decimal(0), "new_sign": Decimal(0)})
            sums["gmv"] += gmv
            sums["new_sign"] += new_sign
        for department_id, sums in team_sums.items():
            for metric, value in sums.items():
                exists = (db.query(PerfGoalTeamOverride)
                          .filter_by(period_id=period.id, department_id=department_id,
                                     metric=metric, granularity="year", quarter=None,
                                     month=None).first())
                if exists is not None:
                    continue
                db.add(PerfGoalTeamOverride(period_id=period.id, department_id=department_id,
                                            metric=metric, granularity="year",
                                            quarter=None, month=None, auto_value=value,
                                            factor=Decimal(1), override_value=None,
                                            effective_value=value, stale=False,
                                            updated_by=operator, updated_at=now))
                teams_written += 1
        db.commit()

    return {"period_id": period.id if period.id and period.id > 0 else None,
            "period_created": period_created, "applied": apply,
            "users_planned": len(plan), "goals_written": goals_written,
            "team_rows_written": teams_written, "warnings": warnings}
