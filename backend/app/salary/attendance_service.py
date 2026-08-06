"""薪资模块 — 考勤落库、全勤判定与人工覆盖（M2-d）。

分工同 M2-c：`attendance_source` 只管从钉钉取数（纯函数、无 session），
这里管事务、匹配、覆盖语义与留痕。

## 三条设计红线

1. **人工录入的值永不被同步覆盖。**
   钉钉取不到请假小时（`attendance_source` 约束 2、3），事假/病假**必须**人工录入。
   如果「同步考勤」把人工填的病假清成 0，HR 会在毫无提示的情况下丢掉刚录的数据，
   而病假直接决定实出天数和缺勤扣款。所以同步只写**钉钉真正给了值的字段**，
   人工字段按 `manual_fields` 白名单保护，同步时原样保留。

2. **钉钉的「应出勤天数」不进 `due_days`。**
   实测 3 月钉钉给 22（工作日口径），而满月员工的应出天数按决策 B1 是 31
   （`full_month_days`）。把钉钉这一列接进分母，缺勤扣款 `底薪/应出×缺勤` 全员算错。
   钉钉值只落进 `raw_payload.dingtalk_should_days` 供人核对，`due_days` 由规则算。

3. **同步是「按人隔离 + 整批一个事务」。**
   单人取数失败标记 `sync_failed` 进异常清单，不阻塞其余 65 人（红线 6）；
   而整批的提交点仍是末尾的 `guarded_write`——中途有人锁定批次，整批回滚，
   不留半批考勤。与 M2-c 完全同构。

4. **规则参数按批次月取，不按 today。**
   走 `period_service.resolve_params`。8 月同步 3 月批次时，`load_params(db)` 的
   默认 today 会取到今天生效的版本，`due_days` 与 param_snapshot 各说各话。
   （对抗性审查 2026-08-07 第 1 条实测：31 vs 26，缺勤 4 天差 248 元/人）

5. **同步不是无害的读操作，已计算/复核中的批次不许同步。**
   同步会重写全表考勤，而这两个状态下的数已经被算过了。状态机不会因为再同步
   一次而回退（`_ALLOWED` 里没这条边），于是界面仍显示「已计算」而底下的数变了，
   导出的是过期结果。（第 3 条）
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.salary import period_service, service
from app.salary.models import SalaryAttendance, SalaryEmployeeProfile, SalaryPeriod

logger = logging.getLogger("commission")

SOURCE_DINGTALK = "dingtalk"
SOURCE_MANUAL = "manual"
SOURCE_MIXED = "mixed"

SYNC_OK = "ok"
SYNC_FAILED = "sync_failed"
SYNC_NO_USERID = "no_userid"

SYNC_LABELS = {
    SYNC_OK: "已同步",
    SYNC_FAILED: "钉钉取数失败",
    SYNC_NO_USERID: "档案未绑定钉钉",
}

# 人工录入字段白名单（红线 1）。钉钉给不了，只能人填；同步时必须原样保留。
# 放在模块级常量而不是散在函数里：M2-e 异常面板要用同一份清单去问「哪些还没填」。
MANUAL_FIELDS = ("personal_leave_hours", "sick_leave_hours",
                 "annual_leave_days", "annual_leave_remain")

# 钉钉能给的字段 → 模型列。值取自 attendance_source.COLUMN_ALIASES 的输出字段名。
_DINGTALK_FIELDS = {
    "late_count": "late_count",
    "early_leave_count": "early_leave_count",
    "absent_days": "absent_count",
}


class AttendanceError(ValueError):
    """考勤操作失败。文案直接给 HR 看。"""


# ---------------------------------------------------------------------------
# 全勤判定
# ---------------------------------------------------------------------------

def judge_full_attendance(row: SalaryAttendance, params: dict[str, str]) -> bool:
    """全勤 = 无事假 且 病假 ≤ 上限 且 迟到/早退/漏打卡/旷工均为 0。

    **年假不破全勤**（决策 B3，参数 `annual_leave_breaks_attendance` 留了反悔口子）。
    这条是从 3 月数据反推的：王京花年假 5.5 天仍拿到全勤 100。

    请假小时为 NULL 时**不算全勤**，而不是当 0 处理：NULL 的含义是「人还没录」，
    把没录当没请假，会给一个可能有事假的人白发 100 元，且错误只在对账时才浮现。
    """
    if row.personal_leave_hours is None or row.sick_leave_hours is None:
        return False

    sick_max = service.param_decimal(params, "attendance_sick_hours_max", Decimal("8"))
    if row.personal_leave_hours > 0:
        return False
    if row.sick_leave_hours > sick_max:
        return False
    if (row.late_count or 0) > 0 or (row.early_leave_count or 0) > 0:
        return False
    if (row.miss_punch_count or 0) > 0:
        return False
    if (row.absent_count or Decimal("0")) > 0:
        return False

    if service.param_bool(params, "annual_leave_breaks_attendance", False):
        if (row.annual_leave_days or Decimal("0")) > 0:
            return False
    return True


def compute_actual_days(
    row: SalaryAttendance, due_days: Decimal, params: dict[str, str]
) -> Optional[Decimal]:
    """实出天数 = 应出 − 事假/7.83 − 病假/7.83×扣减比例（设计文档 §5.2）。

    请假小时未录时返回 None 而不是等于应出：算成满勤会让工资偏高，
    而「还没录」和「确实没请假」必须在界面上分得开。
    """
    if row.personal_leave_hours is None or row.sick_leave_hours is None:
        return None
    day_hours = service.param_decimal(params, "day_hours", Decimal("7.83"))
    if day_hours <= 0:
        raise AttendanceError("规则参数 day_hours 必须大于 0，请到规则配置页修正")
    sick_ratio = service.param_decimal(params, "sick_pay_deduct_ratio", Decimal("0.30"))

    personal = Decimal(row.personal_leave_hours) / day_hours
    sick = Decimal(row.sick_leave_hours) / day_hours * sick_ratio
    actual = Decimal(due_days) - personal - sick - Decimal(row.absent_count or 0)
    return max(actual, Decimal("0")).quantize(Decimal("0.01"))


def resolve_due_days(period: SalaryPeriod, params: dict[str, str]) -> Decimal:
    """满月员工的应出天数 = full_month_days（决策 B1）。

    **不用钉钉的「应出勤天数」**（红线 2）。非满月（月中入离职、实出<15）走
    workday_count，那是 M3 分段函数的事，这里只给满月基准。
    """
    return service.param_decimal(params, "full_month_days", Decimal("31"))


# ---------------------------------------------------------------------------
# 落库
# ---------------------------------------------------------------------------

def _existing_rows(db: Session, period_id: int) -> dict[int, SalaryAttendance]:
    rows = db.query(SalaryAttendance).filter(SalaryAttendance.period_id == period_id).all()
    return {r.employee_id: r for r in rows}


def payroll_profiles(db: Session) -> list[SalaryEmployeeProfile]:
    """发薪名单（在职 + payroll_included）。同步、名单门、缺失清单共用同一口径。

    这三处口径必须是同一份：router 按 A 取 userid、service 按 B 匹配、缺失清单按 C
    数分母，任意两处不一致都会让「某人没同步上」在界面上看不出来。
    """
    return (
        db.query(SalaryEmployeeProfile)
        .filter(SalaryEmployeeProfile.payroll_included == 1)
        .filter(SalaryEmployeeProfile.status == "active")
        .order_by(SalaryEmployeeProfile.emp_no)
        .all()
    )


def profiles_by_userid(
    db: Session,
) -> tuple[dict[str, SalaryEmployeeProfile], dict[str, list[str]]]:
    """userid → 档案，外加撞号清单 {userid: [姓名...]}。

    撞号必须显式返回而不是让 dict 悄悄覆盖：见 `sync_from_dingtalk` 里的说明。
    """
    by_uid: dict[str, SalaryEmployeeProfile] = {}
    names: dict[str, list[str]] = {}
    for p in payroll_profiles(db):
        uid = (p.dingtalk_userid or "").strip()
        if not uid:
            continue
        names.setdefault(uid, []).append(p.name)
        by_uid.setdefault(uid, p)
    return by_uid, {uid: n for uid, n in names.items() if len(n) > 1}


def assert_syncable(period: SalaryPeriod) -> None:
    """同步门：锁定不行，**已计算/复核中也不行**。

    `assert_writable` 只挡 confirmed。但 calculated / reviewing 这两个状态下，
    考勤已经被算进工资了，再同步一次会静默改掉底数：状态机没有「calculated →
    attendance_synced」这条边，`_next_status` 因此返回 None，状态和版本号都不动，
    界面继续显示「已计算」，导出的却是过期数字（实测约 1067 元/人）。
    要重来就先退回 imported（状态机允许 calculated → imported），那一步是显式的、
    有留痕的，HR 知道自己作废了上一次计算。（对抗性审查 2026-08-07 第 3 条）
    """
    period_service.assert_writable(period)
    if period.status in (period_service.STATUS_CALCULATED, period_service.STATUS_REVIEWING):
        label = period_service.STATUS_LABELS.get(period.status, period.status)
        raise AttendanceError(
            f"批次当前是「{label}」，重新同步考勤会让已算出的工资失效但状态不变。"
            "请先把批次退回「社保已导入」再同步，退回会留痕并作废本次计算结果。"
        )


def _apply_dingtalk(row: SalaryAttendance, values: dict[str, Decimal]) -> None:
    """把钉钉值写进行对象。**只动钉钉能给的字段**，人工字段一律不碰（红线 1）。

    **只写 values 里真正出现的 key，缺列不写 0。** 钉钉报表被 HR 改名（`fetch_columns`
    的注释里说过这是常规操作）会让某一列彻底取不到，而 `.get(k, 0)` 会把人工补录的
    迟到/漏打卡清零——`manual_upsert` 明确允许人工改这四个字段，正是钉钉权限没开通时
    的唯一来源。清零的直接后果是全勤判定从「不给」翻成「给」，白发 100 元。
    （对抗性审查 2026-08-07 第 4 条实测：late 3→0, miss 2→0, full False→True）

    漏打卡是上班缺卡 + 下班缺卡两列相加：只要有一列在就写，两列都不在才跳过。
    """
    if "late_count" in values:
        row.late_count = _to_int(values["late_count"])
    if "early_leave_count" in values:
        row.early_leave_count = _to_int(values["early_leave_count"])
    if "miss_punch_on" in values or "miss_punch_off" in values:
        row.miss_punch_count = _to_int(
            values.get("miss_punch_on", Decimal("0"))
            + values.get("miss_punch_off", Decimal("0"))
        )
    if "absent_days" in values:
        row.absent_count = values["absent_days"]


def _to_int(v: Decimal) -> int:
    """次数向上取整。`int()` 朝零截断，钉钉给出 0.5 这类小数时会变成 0——
    异常直接消失，全勤判定从「不给」翻成「给」。次数是「有没有」的判定，
    宁可多记一次让 HR 去核，也不能把异常抹平成零。
    """
    return int(Decimal(v).quantize(Decimal("1"), rounding=ROUND_CEILING))


def sync_from_dingtalk(
    db: Session,
    period: SalaryPeriod,
    fetched: dict[str, Any],
    *,
    expected_version: Optional[int] = None,
    operator_id: Optional[int] = None,
) -> dict[str, Any]:
    """把 `attendance_source.fetch_many` 的结果落库。

    `fetched` 形如 `{"results": [PersonAttendance...], "missing_leave": [...]}`，
    取数在 router 层做（异步），这里只管落库——service 层不发起 HTTP，
    否则测试要么打真钉钉要么 mock 一整套 httpx。

    **upsert 语义而非先删后插**：删了重建会把人工录的请假小时一并抹掉（红线 1），
    而且 id 变化会让前端刚打开的编辑框指向一条不存在的行。
    """
    assert_syncable(period)
    from_status = period.status
    from_version = period.status_version
    if expected_version is not None and expected_version != from_version:
        # 前端带回的版本已经落后：与其跑完一分钟的取数再在末尾被 guarded_write 拒掉，
        # 不如当场失败。末尾那道谓词仍然保留——这里只是省时间，不是替代品。
        raise period_service.SalaryStaleVersion(
            "批次已被他人修改，本次同步未开始，请刷新后重试"
        )

    params = period_service.resolve_params(db, period)
    due_days = resolve_due_days(period, params)

    profiles, duplicate_userids = profiles_by_userid(db)
    if duplicate_userids:
        # 一个 userid 挂两份档案时，dict 推导会让后来者覆盖前者：钉钉只回一条记录，
        # 落库也只有一条，`source_count == synced`、`failed == 0`、unbound 为空——
        # 所有告警指标全绿，而被覆盖的那个人当月考勤是空的，M3 会按全勤给他发钱。
        # 唯一能救的时机是同步开始前，所以整批拒绝而不是「跳过重复的继续跑」。
        # （对抗性审查 2026-08-07 第 2 条）
        detail = "、".join(
            f"{uid}（{'/'.join(names)}）" for uid, names in duplicate_userids.items()
        )
        raise AttendanceError(
            f"以下钉钉 userid 被多份员工档案共用，同步会让其中一人考勤为空：{detail}。"
            "请先到员工档案里把绑定改对再同步。"
        )
    existing = _existing_rows(db, period.id)

    counts = {SYNC_OK: 0, SYNC_FAILED: 0}
    failures: list[dict[str, str]] = []
    dirty_people: list[dict[str, Any]] = []
    now = datetime.now()

    for person in fetched.get("results") or []:
        profile = profiles.get(person.userid)
        if profile is None:
            # 档案侧没这个 userid：不是同步失败，是绑定问题，交给 unbound 清单
            continue
        if not person.ok:
            counts[SYNC_FAILED] += 1
            failures.append({"employee_id": profile.id, "name": profile.name,
                             "reason": person.error or "未知错误"})
            continue

        row = existing.get(profile.id)
        try:
            with db.begin_nested():
                if row is None:
                    row = SalaryAttendance(period_id=period.id, employee_id=profile.id)
                    db.add(row)
                    existing[profile.id] = row
                _apply_dingtalk(row, person.values)
                row.due_days = due_days
                row.actual_days = compute_actual_days(row, due_days, params)
                row.full_attendance = 1 if judge_full_attendance(row, params) else 0
                # 钉钉原样值留档：排障时要能回答「是钉钉给错了还是我们算错了」
                row.raw_payload = {
                    "dingtalk_should_days": str(person.values.get("dingtalk_should_days", "")),
                    "actual_days_raw": str(person.values.get("actual_days_raw", "")),
                    "values": {k: str(v) for k, v in person.values.items()},
                }
                row.sync_source = (
                    SOURCE_MIXED if _has_manual(row) else SOURCE_DINGTALK
                )
                row.synced_at = now
        except Exception as exc:  # noqa: BLE001
            # **只打异常类型 + 驱动原始文案，不打 str(exc)**：SQLAlchemy 的
            # DataError/IntegrityError 文案里带完整 INSERT 参数元组，考勤行本身没有
            # PII，但同一份日志会被当模板抄到别处（M2-c 的导入路径就带身份证密文）。
            # 引擎侧已开 hide_parameters=True，这里再收一道，两层都不指望对方。
            detail = getattr(getattr(exc, "orig", None), "args", None) or (type(exc).__name__,)
            logger.warning("考勤落库单人失败 period=%s employee=%s: %s %s",
                           period.id, profile.id, type(exc).__name__, detail[0])
            print(f"[salary.attendance] row failed emp={profile.id}: "
                  f"{type(exc).__name__} {detail[0]}", flush=True)
            counts[SYNC_FAILED] += 1
            failures.append({"employee_id": profile.id, "name": profile.name,
                             "reason": f"落库失败：{type(exc).__name__}"})
            continue
        counts[SYNC_OK] += 1
        if getattr(person, "dirty", None):
            # 脏值不算失败：数落进去了，只是某几列偏小。但必须让人看见——
            # 31 天里坏 11 天会聚合出一个「看起来很正常」的 20.0。
            dirty_people.append({"employee_id": profile.id, "name": profile.name,
                                 "columns": dict(person.dirty)})

    new_status = _next_status(period)
    values: dict[str, Any] = (
        {"status": new_status, "status_version": from_version + 1}
        if new_status else {"status": from_status}
    )
    period_service.guarded_write(
        db, period, values,
        expected_version=from_version,
        conflict_message="批次已被锁定或被他人修改，本次同步未生效，请刷新后重试",
    )

    unbound = list_unbound(db)
    missing = list_missing(db, period.id)
    summary = {
        # 分母是**发薪名单人数**，不是钉钉回了几条。钉钉那边少回一个人、档案撞号
        # 让一个人被覆盖，这两种情况下 source_count 和 synced 都会相等——
        # 拿它俩比对等于用出题人自己的答案批卷。真正的问题是「名单上有 66 人，
        # 库里只有 65 条考勤」，所以 payroll_headcount 才是该盯的分母。
        "payroll_headcount": len(payroll_profiles(db)),
        "source_count": len(fetched.get("results") or []),
        "synced": counts[SYNC_OK],
        "failed": counts[SYNC_FAILED],
        "failures": failures[:50],
        "failures_truncated": len(failures) > 50,
        "unbound": unbound,
        "unbound_count": len(unbound),
        # 取数失败的人只在这一次 HTTP 响应里出现过，刷新一下就没了；而他们在
        # 考勤列表里同样查无此人（列表只列已有行的人）。missing 是**持久**出口：
        # 名单 LEFT JOIN 考勤，任何没落上行的人都在这里，撞号被覆盖的那个也在。
        "missing": missing,
        "missing_count": len(missing),
        "dirty_values": dirty_people[:50],
        "missing_leave_columns": fetched.get("missing_leave") or [],
        "status": period.status,
        "status_version": period.status_version,
    }
    period_service.log_event(
        db, period, "attendance_sync",
        from_status=from_status if new_status else None,
        to_status=new_status,
        payload={"synced": counts[SYNC_OK], "failed": counts[SYNC_FAILED],
                 "unbound": len(summary["unbound"])},
        operator_id=operator_id,
    )
    return summary


def _has_manual(row: SalaryAttendance) -> bool:
    return any(getattr(row, f, None) is not None for f in MANUAL_FIELDS)


def _next_status(period: SalaryPeriod) -> Optional[str]:
    """同步后推进到 attendance_synced；已在该状态则自环不消耗版本号。

    与 M2-c 同理：重复同步是常态（HR 会反复拉几次核对），每次 +1 会让所有打开
    批次页的客户端拿 409，把乐观锁的告警价值淹进噪音里。
    """
    target = period_service.STATUS_ATTENDANCE
    if period.status == target:
        return None
    if period_service.can_transition(period.status, target):
        return target
    return None


# ---------------------------------------------------------------------------
# 人工录入 / 覆盖
# ---------------------------------------------------------------------------

def manual_upsert(
    db: Session,
    period: SalaryPeriod,
    employee_id: int,
    payload: dict[str, Any],
    *,
    expected_version: Optional[int] = None,
    operator_id: Optional[int] = None,
) -> SalaryAttendance:
    """人工录入或修正一个人的考勤。请假小时唯一的入口（钉钉给不了）。

    改完立刻重算 actual_days 与 full_attendance——让 HR 填完病假还要去点一次
    「重新判定全勤」是把系统的活推给用户。
    """
    period_service.assert_writable(period)
    from_version = period.status_version
    if expected_version is not None and expected_version != from_version:
        raise period_service.SalaryStaleVersion(
            "批次已被他人修改，本次录入未生效，请刷新后重试"
        )

    profile = db.query(SalaryEmployeeProfile).filter(
        SalaryEmployeeProfile.id == employee_id
    ).first()
    if profile is None:
        raise AttendanceError(f"员工档案 {employee_id} 不存在")
    # 名单门：同步和 router 都按「在职 + payroll_included」筛人，只有这里是按 id 直取。
    # 缺了这道门，给一个只参保不发薪（或已离职）的人录考勤会建出考勤行、判出全勤，
    # M3 顺着考勤行就把工资和 100 元全勤奖一起发了。（对抗性审查 2026-08-07 第 6 条）
    if profile.payroll_included != 1 or profile.status != "active":
        raise AttendanceError(
            f"{profile.name} 不在本月发薪名单里（"
            f"{'已离职' if profile.status != 'active' else '仅参保不发薪'}），"
            "不能录考勤。确需发薪请先到员工档案里改状态。"
        )

    params = period_service.resolve_params(db, period)
    row = (
        db.query(SalaryAttendance)
        .filter(SalaryAttendance.period_id == period.id)
        .filter(SalaryAttendance.employee_id == employee_id)
        .first()
    )
    if row is None:
        row = SalaryAttendance(period_id=period.id, employee_id=employee_id)
        db.add(row)

    for fname in MANUAL_FIELDS:
        if fname in payload:
            setattr(row, fname, payload[fname])
    # 迟到/漏打卡等钉钉字段也允许手工改（权限未开通时这是唯一来源）
    for fname in ("late_count", "early_leave_count", "miss_punch_count", "absent_count"):
        if fname in payload and payload[fname] is not None:
            setattr(row, fname, payload[fname])

    if row.due_days is None:
        row.due_days = resolve_due_days(period, params)
    row.actual_days = compute_actual_days(row, row.due_days, params)
    row.full_attendance = 1 if judge_full_attendance(row, params) else 0
    row.sync_source = SOURCE_MIXED if row.synced_at else SOURCE_MANUAL

    db.flush()
    period_service.guarded_write(
        db, period, {"status": period.status},
        expected_version=from_version,
        conflict_message="批次已被锁定或被他人修改，本次录入未生效，请刷新后重试",
    )
    period_service.log_event(
        db, period, "attendance_manual",
        payload={"employee_id": employee_id, "name": profile.name,
                 "fields": sorted(k for k in payload if payload[k] is not None)},
        operator_id=operator_id,
    )
    return row


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------

def list_unbound(db: Session) -> list[dict[str, Any]]:
    """发薪名单里没绑钉钉 userid 的人。这些人考勤永远是空的，必须逐个点名。"""
    rows = [p for p in payroll_profiles(db) if not (p.dingtalk_userid or "").strip()]
    return [{"employee_id": r.id, "emp_no": r.emp_no, "name": r.name} for r in rows]


def list_missing(db: Session, period_id: int) -> list[dict[str, Any]]:
    """发薪名单里**该有考勤行却没有**的人（含绑了 userid 但取数失败的）。

    与 `list_unbound` 分开：没绑 userid 是档案问题，取数失败是钉钉那边的事，
    HR 的下一步动作不同（一个去补绑定，一个重试或改手工录入）。
    但两者的后果一样——考勤行不存在，M3 拿不到缺勤天数，只能按全勤发。
    """
    have = {
        r.employee_id
        for r in db.query(SalaryAttendance.employee_id)
        .filter(SalaryAttendance.period_id == period_id)
        .all()
    }
    return [
        {"employee_id": p.id, "emp_no": p.emp_no, "name": p.name,
         "bound": bool((p.dingtalk_userid or "").strip())}
        for p in payroll_profiles(db)
        if p.id not in have
    ]


def serialize_row(row: SalaryAttendance, profile: Optional[SalaryEmployeeProfile]) -> dict[str, Any]:
    pending = [f for f in MANUAL_FIELDS[:2] if getattr(row, f, None) is None]
    return {
        "id": row.id,
        "employee_id": row.employee_id,
        "emp_no": profile.emp_no if profile else None,
        "name": profile.name if profile else None,
        "due_days": row.due_days,
        "actual_days": row.actual_days,
        "personal_leave_hours": row.personal_leave_hours,
        "sick_leave_hours": row.sick_leave_hours,
        "annual_leave_days": row.annual_leave_days,
        "annual_leave_remain": row.annual_leave_remain,
        "late_count": row.late_count,
        "early_leave_count": row.early_leave_count,
        "miss_punch_count": row.miss_punch_count,
        "absent_count": row.absent_count,
        "full_attendance": bool(row.full_attendance),
        "sync_source": row.sync_source,
        "synced_at": row.synced_at,
        # 请假小时没录时，actual_days 是 None、全勤判 0——界面必须解释为什么，
        # 否则 HR 只会看到「全员非全勤」而不知道是缺输入
        "pending_manual": pending,
    }


def list_rows(
    db: Session, period_id: int, *, keyword: str = "", only_pending: bool = False,
    limit: int = 500,
) -> dict[str, Any]:
    q = (
        db.query(SalaryAttendance, SalaryEmployeeProfile)
        .outerjoin(SalaryEmployeeProfile,
                   SalaryEmployeeProfile.id == SalaryAttendance.employee_id)
        .filter(SalaryAttendance.period_id == period_id)
    )
    if keyword:
        q = q.filter(SalaryEmployeeProfile.name.like(f"%{keyword}%"))
    if only_pending:
        q = q.filter(
            (SalaryAttendance.personal_leave_hours.is_(None))
            | (SalaryAttendance.sick_leave_hours.is_(None))
        )
    pairs = q.order_by(SalaryAttendance.employee_id).limit(limit).all()

    total = (
        db.query(SalaryAttendance)
        .filter(SalaryAttendance.period_id == period_id).count()
    )
    pending_count = (
        db.query(SalaryAttendance)
        .filter(SalaryAttendance.period_id == period_id)
        .filter(
            (SalaryAttendance.personal_leave_hours.is_(None))
            | (SalaryAttendance.sick_leave_hours.is_(None))
        )
        .count()
    )
    return {
        "items": [serialize_row(a, p) for a, p in pairs],
        "total": total,
        "pending_manual_count": pending_count,
        "unbound": list_unbound(db),
        "truncated": len(pairs) >= limit,
    }
