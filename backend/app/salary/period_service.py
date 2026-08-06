"""薪资模块 — 批次工作流与状态机（M2-a）。

批次是整个模块的并发边界：考勤同步、社保导入、重算、锁定都改同一条 period 行，
而这几件事在真实使用里就是会撞——HR 点了「同步考勤」还没转完，另一个人点了「重算」。
所以状态跃迁一律走 `transition()`，它做三件事，缺一不可：

1. **合法性**：目标状态必须在 `_ALLOWED[当前状态]` 里。跃迁图是白名单不是黑名单，
   新增状态必须显式登记，漏登记就报错——比「悄悄允许」安全。
2. **乐观锁**：带 `expected_version` 时用 `UPDATE ... WHERE id=? AND status_version=?`
   的行数判定。**不能先 SELECT 再比对再 UPDATE**——那中间有窗口，两个人都能读到
   version=3 然后都写成 4。这里靠数据库的原子 UPDATE 天然串行化。
3. **留痕**：跃迁写 changelog（employee_id 为空表示批次级事件），锁定/解锁额外记时间人。

confirmed 是单向门：进去之后除 admin 解锁外任何写操作都该被 `assert_writable` 拦掉。
解锁不是「回到 reviewing 当无事发生」——按决策 A4，前次导出要作废，所以解锁必须带
原因并留痕，`unlocked_at` / `unlock_reason` 就是导出时判断要不要打作废水印的依据。

应出天数口径（决策 B1）：满月取 `full_month_days=31`（**不是**当月自然日——2 月也是 31，
这是 HR 的固定基准，跟日历无关）；月中入离职或实出 < 15 天的人改取当月工作日数。
工作日数不能靠 `weekday() < 5` 猜——中国的调休会把周六变成上班日，国庆能连上 8 天。
所以 `workday_count` 是**可人工覆盖的字段**，自动值只是初值，创建批次时一并给出
`workday_source` 提示 HR 复核（详见 `derive_workday_count`）。
"""

from __future__ import annotations

import calendar
import logging
import re
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.salary import service
from app.salary.models import SalaryPeriod, SalaryPeriodEvent

logger = logging.getLogger("commission")

# 状态机白名单：{当前状态: (允许去的状态, ...)}
#
# 三条回边是有意留的，不是画错：
# - calculated → imported：重新导入社保会让已算的数失效，必须退回
# - reviewing → calculated：复核中发现口径错，重算
# - confirmed → reviewing：admin 解锁（A4），只此一条出口，且强制走 unlock()
STATUS_DRAFT = "draft"
STATUS_ATTENDANCE = "attendance_synced"
STATUS_IMPORTED = "imported"
STATUS_CALCULATED = "calculated"
STATUS_REVIEWING = "reviewing"
STATUS_CONFIRMED = "confirmed"

_ALLOWED: dict[str, tuple[str, ...]] = {
    STATUS_DRAFT: (STATUS_ATTENDANCE,),
    STATUS_ATTENDANCE: (STATUS_ATTENDANCE, STATUS_IMPORTED),  # 允许重复同步考勤
    STATUS_IMPORTED: (STATUS_ATTENDANCE, STATUS_IMPORTED, STATUS_CALCULATED),
    STATUS_CALCULATED: (STATUS_IMPORTED, STATUS_CALCULATED, STATUS_REVIEWING),
    STATUS_REVIEWING: (STATUS_CALCULATED, STATUS_CONFIRMED),
    STATUS_CONFIRMED: (STATUS_REVIEWING,),  # 仅 unlock() 走这条
}

STATUS_LABELS = {
    STATUS_DRAFT: "草稿",
    STATUS_ATTENDANCE: "考勤已同步",
    STATUS_IMPORTED: "社保已导入",
    STATUS_CALCULATED: "已计算",
    STATUS_REVIEWING: "复核中",
    STATUS_CONFIRMED: "已锁定",
}

# 步骤条顺序（前端渲染用，confirmed 之后无步骤）
STATUS_ORDER = (
    STATUS_DRAFT, STATUS_ATTENDANCE, STATUS_IMPORTED,
    STATUS_CALCULATED, STATUS_REVIEWING, STATUS_CONFIRMED,
)

_YEAR_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class SalaryPeriodError(ValueError):
    """批次工作流错误：月份非法、状态跃迁不合法、批次已锁定。

    与 `SalaryStaleVersion` 分开：前者是「你不该这么做」，后者是「有人比你先做了」，
    前端要给的提示完全不同——一个是纠正操作，一个是刷新重试。
    """


class SalaryStaleVersion(SalaryPeriodError):
    """乐观锁冲突：期望的 status_version 与库里不符，说明并发有人先改了。"""


# ---------------------------------------------------------------------------
# 月份与工作日
# ---------------------------------------------------------------------------

def parse_year_month(year_month: str) -> tuple[int, int]:
    """校验并拆 'YYYY-MM'。格式错直接抛——批次月份写错会让整批数落错月。"""
    text = (year_month or "").strip()
    if not _YEAR_MONTH_RE.match(text):
        raise SalaryPeriodError(f"批次月份格式应为 YYYY-MM，收到 {year_month!r}")
    y, m = text.split("-")
    return int(y), int(m)


def natural_days_of(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


# 含法定节假日/调休的月份（国办发明电〔2025〕7 号，**仅对 2026 年有效**）。
# 2026 年只有 3/7/8/11/12 月一天节假日都没有（春节调休 2/28 落在周六，差一天就会
# 把 3 月拖进来）。2025 年端午跨 5/31–6/2、中秋国庆合并，分布与此不同；2027 又会变。
# 换年份必须重核这张表，否则 needs_review 标记会静默漂移。
_HOLIDAY_MONTHS_2026 = (1, 2, 4, 5, 6, 9, 10)

WORKDAY_SOURCE_LABELS = {
    "weekday_auto": "自动推算",
    "needs_review": "自动推算（含节假日，待复核）",
    "manual": "人工填写",
}


def derive_workday_count(year: int, month: int) -> tuple[int, str]:
    """推当月工作日数，返回 (天数, 来源标记)。

    **只按周一~周五数，不含任何法定节假日与调休。** 这个结果对 3 月这种没有节假日的
    月份是对的（2026-03 → 22 天，与设计文档 §3 实证的 22 一致），但 1/2/5/10 月一定偏大：
    没扣春节国庆，也没加回调休上班的周末。

    没有引入 chinese-calendar 之类的依赖，是因为那类库的数据要跟着国务院每年的通知更新，
    漏更一次就是静默算错钱——比「明摆着让 HR 填」更危险。所以这里返回的是**初值**，
    `workday_source` 标成 needs_review 并**持久化到批次行**（不只落事件 payload），
    批次页据此渲染「待复核」角标提示 HR 覆盖——标记发不到前端等于这套机制空转。
    """
    days = natural_days_of(year, month)
    count = sum(
        1 for d in range(1, days + 1) if date(year, month, d).weekday() < 5
    )
    if month in _HOLIDAY_MONTHS_2026:
        return count, "needs_review"
    return count, "weekday_auto"


def _validate_workday(year: int, month: int, workday_count: int) -> None:
    """工作日数范围校验。上限是**当月自然日**，不是常量 31。

    2 月只有 28 天，允许填 31 会让所有按天折算的缺勤扣款分母偏大、往少了扣钱。
    create 与 update 两个入口共用这一段——之前 create 不校验，同一个值在两个入口
    结果相反（create 存下 31，update 拒绝）。
    """
    limit = natural_days_of(year, month)
    if not 1 <= workday_count <= limit:
        raise SalaryPeriodError(f"工作日数应在 1~{limit} 之间，收到 {workday_count}")


# ---------------------------------------------------------------------------
# 批次 CRUD
# ---------------------------------------------------------------------------

def get_period(db: Session, period_id: int) -> Optional[SalaryPeriod]:
    return db.query(SalaryPeriod).filter(SalaryPeriod.id == period_id).first()


def get_period_or_raise(db: Session, period_id: int) -> SalaryPeriod:
    row = get_period(db, period_id)
    if row is None:
        raise SalaryPeriodError(f"批次 {period_id} 不存在")
    return row


def get_by_year_month(db: Session, year_month: str) -> Optional[SalaryPeriod]:
    return db.query(SalaryPeriod).filter(SalaryPeriod.year_month == year_month).first()


def list_periods(db: Session, *, status: str = "", limit: int = 60) -> list[SalaryPeriod]:
    q = db.query(SalaryPeriod)
    if status:
        q = q.filter(SalaryPeriod.status == status)
    return q.order_by(SalaryPeriod.year_month.desc()).limit(limit).all()


def create_period(
    db: Session,
    year_month: str,
    *,
    operator_id: Optional[int] = None,
    workday_count: Optional[int] = None,
    remark: Optional[str] = None,
) -> SalaryPeriod:
    """建月度批次。同月只允许一条（DB 唯一键兜底，这里先给友好报错）。

    workday_count 传 None 时用自动推算的初值；HR 可以在批次页改。
    natural_days 无歧义，直接算，不给覆盖口子。
    """
    y, m = parse_year_month(year_month)
    if get_by_year_month(db, year_month) is not None:
        raise SalaryPeriodError(f"{year_month} 批次已存在，请勿重复创建")

    auto_workday, source = derive_workday_count(y, m)
    if workday_count is not None:
        _validate_workday(y, m, workday_count)
        source = "manual"

    row = SalaryPeriod(
        year_month=year_month,
        status=STATUS_DRAFT,
        status_version=0,
        natural_days=natural_days_of(y, m),
        workday_count=workday_count if workday_count is not None else auto_workday,
        workday_source=source,
        remark=remark,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    log_event(
        db, row, "create", to_status=STATUS_DRAFT,
        payload={
            "workday_count": row.workday_count,
            "natural_days": row.natural_days,
            "workday_source": source,
        },
        operator_id=operator_id,
    )
    return row


def update_workday_count(
    db: Session, period: SalaryPeriod, workday_count: int, *, operator_id: Optional[int] = None
) -> SalaryPeriod:
    """人工覆盖工作日数。锁定后禁止改——改了会让已冻结的记录口径与批次不一致。"""
    assert_writable(period)
    y, m = parse_year_month(period.year_month)
    _validate_workday(y, m, workday_count)
    old = period.workday_count
    # 走带谓词的 UPDATE 而不是 ORM 脏刷新：assert_writable 判的是内存里那份快照，
    # 从 SELECT 到这里之间别人可能已经锁定了批次。锁定判定必须在 DB 谓词里。
    guarded_write(
        db, period,
        {"workday_count": workday_count, "workday_source": "manual"},
        conflict_message="批次已被锁定或被他人修改，请刷新后重试",
    )
    log_event(db, period, "workday_update",
              payload={"old": old, "new": workday_count}, operator_id=operator_id)
    return period


# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------

def assert_writable(period: SalaryPeriod) -> None:
    """confirmed 之后一切写操作都要先过这道门。

    调用点是所有会改批次数据的 service（考勤落库、社保导入、重算、行内编辑）。
    这不是「多此一举的防御」——锁定后还能改数，正是设计文档 §2.5 想消灭的错误类型。

    **但它只是「快速失败 + 给好文案」，不是并发保护。** 它读的是调用方手上那份 ORM
    快照，SELECT 与后续写之间有窗口（M2-c 一次导入跑几十秒，窗口大得很）。真正的
    保护是 `guarded_write` 把 `status != confirmed` 放进 UPDATE 谓词。两层都要有：
    这层给用户看得懂的提示，那层保证撞上了也改不进去。
    """
    if period.status == STATUS_CONFIRMED:
        raise SalaryPeriodError(
            f"{period.year_month} 批次已锁定，需管理员解锁后才能修改"
        )


def guarded_write(
    db: Session,
    period: SalaryPeriod,
    values: dict[str, Any],
    *,
    expected_version: Optional[int] = None,
    allow_confirmed: bool = False,
    conflict_message: str = "批次已被他人修改，请刷新后重试",
) -> SalaryPeriod:
    """带锁定门 + 乐观锁的批次字段写入。M2-c/M2-d/M3 改批次行时都该走这里。

    谓词里同时钉三件事，由数据库保证原子：
    - `id` —— 目标行
    - `status != 'confirmed'` —— 锁定后写不进（allow_confirmed=True 时豁免，仅 confirm 自己用）
    - `status_version` —— 传了 expected_version 才加，防并发覆盖

    rowcount==0 说明这三条里至少一条不成立，一律当冲突拒绝。**不要退回去 SELECT
    再判断到底是哪条不成立**——那又是一个新窗口，而且对用户来说「刷新重试」是同一个动作。
    """
    conds = [SalaryPeriod.id == period.id]
    if not allow_confirmed:
        conds.append(SalaryPeriod.status != STATUS_CONFIRMED)
    if expected_version is not None:
        conds.append(SalaryPeriod.status_version == expected_version)

    stmt = update(SalaryPeriod).where(*conds).values(**values, updated_at=datetime.now())
    result = db.execute(stmt)
    if result.rowcount == 0:
        db.rollback()
        raise SalaryStaleVersion(conflict_message)
    db.commit()
    db.refresh(period)
    return period


def can_transition(current: str, target: str) -> bool:
    return target in _ALLOWED.get(current, ())


def transition(
    db: Session,
    period: SalaryPeriod,
    target: str,
    *,
    expected_version: Optional[int] = None,
    operator_id: Optional[int] = None,
    extra: Optional[dict[str, Any]] = None,
    extra_values: Optional[dict[str, Any]] = None,
) -> SalaryPeriod:
    """跃迁到 target，带乐观锁与留痕。返回刷新后的 period。

    `expected_version` 由前端从上次读到的批次带回来。传 None 表示不校验——只允许
    内部串行流程（比如同一个请求里刚创建就跃迁）这么用，凡是用户点出来的动作都要传。

    并发安全的关键是下面这条 UPDATE：条件里同时带 id 和 status_version，
    由数据库保证「比对 + 自增」原子。rowcount==0 就是有人抢先了。

    `extra_values` 是要跟状态**在同一条 UPDATE 里**落库的字段（confirm 的
    confirmed_at/by 就走这里）。跃迁后再补一次 `db.commit()` 是不行的：那条裸
    UPDATE 只有主键谓词，两次提交之间别人解锁的话，confirmed 戳会盖到 reviewing 行上。
    """
    if not can_transition(period.status, target):
        raise SalaryPeriodError(
            f"不允许从「{STATUS_LABELS.get(period.status, period.status)}」"
            f"跃迁到「{STATUS_LABELS.get(target, target)}」"
        )
    if period.status == STATUS_CONFIRMED and target == STATUS_REVIEWING:
        # 唯一出口只允许 unlock() 走，直接调 transition 绕过留痕是不行的
        raise SalaryPeriodError("已锁定批次请走管理员解锁流程（需填写解锁原因）")

    from_status = period.status
    from_version = period.status_version
    if expected_version is not None and expected_version != from_version:
        raise SalaryStaleVersion(
            f"批次已被他人修改（当前版本 {from_version}，你的版本 {expected_version}），请刷新后重试"
        )

    # 自环（重复同步考勤 / 重复导入）不消耗版本号。
    # 这两件事是设计里的常态操作，每做一次就让所有已打开批次页的客户端版本作废，
    # M2-c/M2-d 落地后会把 409 变成常态噪音——用户学会「刷新一下再来」，
    # 乐观锁的告警价值就归零了。状态没变就只留痕。
    if from_status == target and not extra_values:
        log_event(db, period, "transition", from_status=from_status, to_status=target,
                  payload=extra or None, operator_id=operator_id)
        return period

    values: dict[str, Any] = {"status": target, "status_version": from_version + 1}
    if extra_values:
        values.update(extra_values)

    stmt = (
        update(SalaryPeriod)
        .where(SalaryPeriod.id == period.id, SalaryPeriod.status_version == from_version)
        .values(**values, updated_at=datetime.now())
    )
    result = db.execute(stmt)
    if result.rowcount == 0:
        db.rollback()
        raise SalaryStaleVersion("批次已被他人修改，请刷新后重试")
    db.commit()
    db.refresh(period)

    log_event(db, period, "transition", from_status=from_status, to_status=target,
              payload=extra or None, operator_id=operator_id)
    return period


def confirm(
    db: Session,
    period: SalaryPeriod,
    *,
    expected_version: Optional[int] = None,
    operator_id: Optional[int] = None,
) -> SalaryPeriod:
    """锁定批次。档案快照冻结在 M4 接进来，这里只管状态与留痕。

    confirmed_at / confirmed_by 必须**跟状态同一条 UPDATE** 落库。分成两次写会开一个
    窗口：A 的 confirm 提交后、补时间戳前，B 完成一次 unlock，A 的第二条裸 UPDATE
    就把 confirmed_at 盖到已解锁的行上，造成 confirmed_at > unlocked_at 的假象——
    而 M4 正是靠这两个时间戳的先后判断前次导出要不要打作废水印（A4）。
    """
    return transition(
        db, period, STATUS_CONFIRMED,
        expected_version=expected_version, operator_id=operator_id,
        extra_values={"confirmed_at": datetime.now(), "confirmed_by": operator_id},
    )


def unlock(
    db: Session,
    period: SalaryPeriod,
    reason: str,
    *,
    expected_version: Optional[int] = None,
    operator_id: Optional[int] = None,
) -> SalaryPeriod:
    """管理员解锁（决策 A4）：回到复核中，并留下作废依据。

    reason 强制非空——解锁是要作废已发出去的表的，没有理由的解锁事后无法审计。
    `unlocked_at` 一旦有值，导出侧就该给前次文件打「作废」水印（M4 实现）。
    """
    text = (reason or "").strip()
    if not text:
        raise SalaryPeriodError("解锁必须填写原因（前次导出将被标记作废）")
    if period.status != STATUS_CONFIRMED:
        raise SalaryPeriodError("只有已锁定的批次需要解锁")

    from_version = period.status_version
    if expected_version is not None and expected_version != from_version:
        raise SalaryStaleVersion("批次已被他人修改，请刷新后重试")

    stmt = (
        update(SalaryPeriod)
        .where(SalaryPeriod.id == period.id, SalaryPeriod.status_version == from_version)
        .values(
            status=STATUS_REVIEWING,
            status_version=from_version + 1,
            unlocked_at=datetime.now(),
            unlock_reason=text[:255],
            updated_at=datetime.now(),
        )
    )
    result = db.execute(stmt)
    if result.rowcount == 0:
        db.rollback()
        raise SalaryStaleVersion("批次已被他人修改，请刷新后重试")
    db.commit()
    db.refresh(period)

    log_event(db, period, "unlock", from_status=STATUS_CONFIRMED, to_status=STATUS_REVIEWING,
              reason=text, operator_id=operator_id)
    logger.warning("薪资批次解锁 period=%s ym=%s by=%s reason=%s",
                   period.id, period.year_month, operator_id, text)
    print(f"[salary.period] unlock {period.year_month} by={operator_id} reason={text}", flush=True)
    return period


# ---------------------------------------------------------------------------
# 序列化 / 留痕
# ---------------------------------------------------------------------------

def next_steps(status: str) -> list[dict[str, str]]:
    """下一步可选动作，**带上该走哪个端点、要什么权限**。

    不能只返回状态码列表：confirmed 这一步走的是 `/confirm` 而不是 `/transition`，
    权限也从 salary:write 变成 salary:admin。前端照状态码循环渲染按钮的话，
    锁定按钮会打到 /transition 拿 400。这条特例后端知道，就得通过契约传出去，
    而不是让前端各自硬编码一份。

    confirmed → reviewing 不出现在这里：解锁要填原因，是独立的表单动作，
    不属于「下一步」按钮组。
    """
    steps = []
    for target in _ALLOWED.get(status, ()):
        if target == status:
            continue  # 自环（重复同步/重复导入）由各自的功能按钮触发，不进步骤条
        if status == STATUS_CONFIRMED:
            continue  # 解锁走独立表单
        is_confirm = target == STATUS_CONFIRMED
        steps.append({
            "status": target,
            "label": STATUS_LABELS.get(target, target),
            "endpoint": "confirm" if is_confirm else "transition",
            "permission": "salary:admin" if is_confirm else "salary:write",
        })
    return steps


def serialize_period(period: SalaryPeriod) -> dict[str, Any]:
    return {
        "id": period.id,
        "year_month": period.year_month,
        "status": period.status,
        "status_label": STATUS_LABELS.get(period.status, period.status),
        "status_version": period.status_version,
        "workday_count": period.workday_count,
        "workday_source": period.workday_source,
        "workday_source_label": WORKDAY_SOURCE_LABELS.get(
            period.workday_source or "", period.workday_source or ""
        ),
        # 批次页据此显示「待复核」角标。这个标记只落事件 payload 的话前端拿不到，
        # 2 月批次的 20 天就会静默成为应出基准（实际扣春节 9 天、加回调休 2 天）。
        "workday_needs_review": period.workday_source == "needs_review",
        "natural_days": period.natural_days,
        "has_param_snapshot": bool(period.param_snapshot),
        "calculated_at": period.calculated_at.isoformat() if period.calculated_at else None,
        "confirmed_at": period.confirmed_at.isoformat() if period.confirmed_at else None,
        "confirmed_by": period.confirmed_by,
        "unlocked_at": period.unlocked_at.isoformat() if period.unlocked_at else None,
        "unlock_reason": period.unlock_reason,
        "remark": period.remark,
        "writable": period.status != STATUS_CONFIRMED,
        "next_steps": next_steps(period.status),
        "created_at": period.created_at.isoformat() if period.created_at else None,
    }


def period_on_date(period: SalaryPeriod) -> date:
    """该批次查参数表该用的日期 = 当月最后一天。

    单独抽出来是因为「按批次月取参数」这条规则**不止 freeze_params 需要**：
    考勤同步、人工录入同样要按当月版本算 due_days。M2-d 的对抗性审查（2026-08-07
    第 1 条）实测过后果——3 月批次在 8 月同步，due_days 落 26（今天生效的版本），
    而 param_snapshot 里写着 31，同一个批次两个分母，底薪 10000 缺勤 4 天差 248 元。
    """
    y, m = parse_year_month(period.year_month)
    return date(y, m, natural_days_of(y, m))


def resolve_params(db: Session, period: SalaryPeriod) -> dict[str, str]:
    """取该批次该用的规则参数：优先已冻结的快照，否则按**当月最后一天**现查。

    `service.load_params(db)` 的 `on_date` 默认 today，任何直接这么调的地方
    都会在跨月使用时取错版本。模块内一律走这个函数，不要再自己调 load_params。
    """
    if period.param_snapshot:
        return period.param_snapshot
    return service.load_params(db, period_on_date(period))


def freeze_params(db: Session, period: SalaryPeriod) -> dict[str, str]:
    """把当月生效参数冻进 param_snapshot。M3 重算前调用。

    取参数用**当月最后一天**而非 today：8 月份补算 3 月工资时，要拿的是 3 月生效的
    参数版本，不是今天的。参数表本身按 effective_from/to 版本化，日期给错就取错版本。

    **快照为空必须抛错，不能放行。** 这条是被测试逼出来的真问题：seed 的
    EFFECTIVE_FROM 是 2026-04-01，而 P1 的验收目标恰恰是复算 2026-03——3 月批次
    取不到任何生效参数，snapshot 是 {}。而 `service.param_decimal` 在取不到 key 时
    会静默回落硬编码默认值，于是整个 3 月会拿一套「代码里的影子参数」算完，
    HR 在规则页改的任何值都不生效，且没有任何地方会报错。
    宁可在这里挡住，让用户去把参数生效日调到 3 月 1 日或更早。

    **锁定后禁止重新冻结。** param_snapshot 存在的全部意义就是让已发的批次可复算、
    可追溯；能被覆盖的快照不是快照。锁定后有人在规则页把 full_month_days 从 31 改成
    26，再触发一次重算入口，快照就会被悄悄换掉，拿这批数复算跟当初发出去的对不上，
    且事件时间线上一片空白。所以走 guarded_write + 留痕。
    """
    assert_writable(period)
    snapshot = service.load_params(db, period_on_date(period))
    if not snapshot:
        raise SalaryPeriodError(
            f"{period.year_month} 没有生效的规则参数版本（参数生效日晚于该月），"
            "请到规则配置页把参数生效日调整到该月 1 日或更早后重试"
        )
    guarded_write(
        db, period, {"param_snapshot": snapshot},
        conflict_message="批次已锁定或被他人修改，无法刷新参数快照",
    )
    log_event(db, period, "freeze_params",
              payload={"param_count": len(snapshot)})
    return snapshot


def list_events(db: Session, period_id: int, *, limit: int = 200) -> list[SalaryPeriodEvent]:
    return (
        db.query(SalaryPeriodEvent)
        .filter(SalaryPeriodEvent.period_id == period_id)
        .order_by(SalaryPeriodEvent.id.desc())
        .limit(limit)
        .all()
    )


def log_event(
    db: Session,
    period: SalaryPeriod,
    event_type: str,
    *,
    from_status: Optional[str] = None,
    to_status: Optional[str] = None,
    reason: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    operator_id: Optional[int] = None,
) -> None:
    """批次留痕。写失败不连累主流程——状态已经改完了，丢一条日志好过整个动作回滚。

    对外暴露（不是 `_log`）是给 M2-c/M2-d 用的：导入和考勤同步也要往同一条时间线上写，
    否则「这批数据哪来的」在批次页拼不出来。

    **用 savepoint 而不是裸 rollback。** 调用方的典型形态是「循环 add 一批导入行 →
    最后 log_event」，一个 `db.rollback()` 会把人家尚未提交的整批数据一起丢掉，
    而调用方只会看到一行「留痕失败」，根本不知道自己的数据没了。savepoint 只回滚
    事件插入本身（与红线 6「批量循环用 savepoint 隔离单条失败」同一个原则）。
    """
    try:
        with db.begin_nested():
            db.add(SalaryPeriodEvent(
                period_id=period.id,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                status_version=period.status_version,
                reason=str(reason)[:255] if reason else None,
                payload=payload,
                created_by=operator_id,
            ))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("薪资批次留痕失败 period=%s type=%s: %s", period.id, event_type, exc)
        print(f"[salary.period] event log failed {event_type}: {exc}", flush=True)
