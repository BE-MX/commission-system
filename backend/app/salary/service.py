"""薪资模块 — 主数据 service（M1：档案 / 职级表 / 规则参数 / 部门映射）。

两个贯穿全模块的推导口径在这里定义，M3 计算引擎复用同一份，不许各算各的：
- `resolve_dept_group`：档案 override 优先，其次 dept_mapping，都没有则 None
- `resolve_base_salary`：档案 base_salary_override 优先，其次职级表（按赛道取
  base_salary，管理岗取 std_salary），都没有则 None

PII 一律经 pii.py 的 normalize → hash → encrypt 三步，service 之外不碰密文。
"""

from __future__ import annotations

import logging
from datetime import date
from app.core.time import beijing_today
from decimal import Decimal
from typing import Any, Optional

from app.core.list_sort import apply_list_sort, apply_items_sort

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.salary import pii
from app.salary.models import (
    SalaryChangeLog,
    SalaryDeptMapping,
    SalaryEmployeeProfile,
    SalaryGradeTable,
    SalaryRuleParam,
)
from app.salary.schemas import DeptMappingUpsert, GradeUpsert, ProfileCreate, ProfileUpdate

logger = logging.getLogger("commission")

# 管理岗赛道用 std_salary 列，其余赛道用 base_salary 列
_STD_SALARY_SCHEMES = {"manage"}


# ---------------------------------------------------------------------------
# 推导口径（M3 引擎复用）
# ---------------------------------------------------------------------------

def load_dept_group_map(db: Session) -> dict[str, str]:
    return {m.dept_detail: m.dept_group for m in db.query(SalaryDeptMapping).all()}


def resolve_dept_group(
    profile: SalaryEmployeeProfile, dept_map: dict[str, str]
) -> Optional[str]:
    """大部门生效值：按人覆盖 > 部门映射。

    覆盖优先是 3 月表实证需求：跟单1部 7 人里吕德洋（业务总监）归业务部、
    其余归后综部——大部门不是纯部门属性，不能只靠映射表。
    """
    if profile.dept_group_override:
        return profile.dept_group_override
    if profile.dept_detail:
        return dept_map.get(profile.dept_detail)
    return None


def load_grade_map(db: Session, on_date: Optional[date] = None) -> dict[tuple[str, str], SalaryGradeTable]:
    """取指定日期生效的职级表，键 (scheme, grade_code)。默认取今天。"""
    d = on_date or beijing_today()
    rows = (
        db.query(SalaryGradeTable)
        .filter(SalaryGradeTable.effective_from <= d)
        .filter(or_(SalaryGradeTable.effective_to.is_(None), SalaryGradeTable.effective_to >= d))
        .order_by(SalaryGradeTable.effective_from)
        .all()
    )
    # 同键多版本时后取胜：order_by effective_from 升序，晚生效的覆盖早生效的
    return {(r.scheme, r.grade_code): r for r in rows}


def resolve_base_salary(
    profile: SalaryEmployeeProfile,
    grade_map: dict[tuple[str, str], SalaryGradeTable],
) -> Optional[Decimal]:
    """底薪生效值：手动定薪 > 职级表。都没有返回 None（M3 须报异常而非算 0）。"""
    if profile.base_salary_override is not None:
        return profile.base_salary_override
    if not profile.grade_scheme or not profile.grade_code:
        return None
    row = grade_map.get((profile.grade_scheme, profile.grade_code))
    if row is None:
        return None
    if profile.grade_scheme in _STD_SALARY_SCHEMES:
        return row.std_salary
    return row.base_salary


# ---------------------------------------------------------------------------
# 档案
# ---------------------------------------------------------------------------

def _apply_pii(profile: SalaryEmployeeProfile, *, id_card: Optional[str], bank_card: Optional[str]) -> None:
    """写 PII 三步：归一化 → HMAC 哈希（唯一/匹配）→ AES 密文（还原）。

    传 None = 不动；传空串 = 清除。明文不落任何列。
    """
    if id_card is not None:
        norm = pii.normalize_id_card(id_card)
        profile.id_card_hash = pii.hash_pii(norm)
        profile.id_card_cipher = pii.encrypt_pii(norm)
    if bank_card is not None:
        norm = pii.normalize_bank_card(bank_card)
        profile.bank_card_hash = pii.hash_pii(norm)
        profile.bank_card_cipher = pii.encrypt_pii(norm)


def create_profile(db: Session, payload: ProfileCreate) -> SalaryEmployeeProfile:
    data = payload.model_dump(exclude={"id_card", "bank_card"})
    profile = SalaryEmployeeProfile(**data)
    _apply_pii(profile, id_card=payload.id_card, bank_card=payload.bank_card)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


# 改动即影响发薪金额的列。这些列变了必须留痕，否则「这个月为什么多发 500」查无对证。
_PAY_AFFECTING_FIELDS = (
    "base_salary_override",
    "probation_salary",
    "guaranteed_salary",
    "guaranteed_from",
    "guaranteed_to",
    "grade_scheme",
    "grade_code",
    "payroll_included",
    "fund_included",
    "status",
    "leave_date",
    "regular_date",
    "special_calc",
    "seniority_override",
)


# 决定底薪费率的三列。它们变了，算薪要知道「从哪天起」——编辑日不是生效日：
# 4/3 补录 3/15 的调薪、4/20 预录 5/1 的调薪，按编辑日记都会把钱算进错的月份。
RATE_FIELDS = ("base_salary_override", "grade_scheme", "grade_code")

# change_type 值域。只有 raise/grade 参与月中加权与「月末费率回推」；
# correction（更正录错，视为一直是新值）与 profile（其余金额列，自带日期或整月生效）只留痕
RATE_CHANGE_TYPES = ("raise", "grade")
CHANGE_TYPE_CORRECTION = "correction"
CHANGE_TYPE_PROFILE = "profile"


class ProfileChangeError(ValueError):
    """档案编辑缺必要信息（如改了定薪却没给生效日）。路由转 400。"""


def _log_pay_changes(
    db: Session,
    profile: SalaryEmployeeProfile,
    before: dict[str, Any],
    after: dict[str, Any],
    operator_user_id: Optional[int],
    *,
    kind: Optional[str] = None,
    effective_date: Optional[date] = None,
) -> None:
    """把影响金额的档案改动写进 change_logs，不记 PII。

    定薪/职级与其余金额列分两条记：前者带 HR 给的生效日、供引擎分段，
    后者只是留痕。定薪/职级那条**三列整组快照**而不是只记差异列——调级只改
    grade_code 时，只记差异的 old_value 里没有 scheme，引擎还原不出旧费率，
    月中分段会静默退化成整月新薪。
    """
    rate_changed = {k for k in RATE_FIELDS
                    if _blank_to_none(before[k]) != _blank_to_none(after[k])}
    other = {k for k in before if k not in RATE_FIELDS and before[k] != after[k]}

    if rate_changed:
        if kind == "correction":
            change_type, eff, reason = CHANGE_TYPE_CORRECTION, beijing_today(), "更正录入错误"
        else:
            change_type = "grade" if {"grade_scheme", "grade_code"} & rate_changed else "raise"
            eff, reason = effective_date, "调薪调级"
        db.add(
            SalaryChangeLog(
                employee_id=profile.id,
                change_type=change_type,
                effective_date=eff,
                old_value=_jsonable({k: before[k] for k in RATE_FIELDS}),
                new_value=_jsonable({k: after[k] for k in RATE_FIELDS}),
                reason=reason,
                created_by=operator_user_id,
            )
        )
    if other:
        db.add(
            SalaryChangeLog(
                employee_id=profile.id,
                change_type=CHANGE_TYPE_PROFILE,
                effective_date=beijing_today(),
                old_value=_jsonable({k: before[k] for k in other}),
                new_value=_jsonable({k: after[k] for k in other}),
                reason="档案编辑",
                created_by=operator_user_id,
            )
        )


def _blank_to_none(v: Any) -> Any:
    # 前端整表回传：库里 NULL 的职级回来是 ''，不归一的话每次保存都算「改了职级」
    return None if v == "" else v


def _rate_change_requested(profile: SalaryEmployeeProfile, data: dict[str, Any]) -> bool:
    return any(
        f in data and _blank_to_none(data[f]) != _blank_to_none(getattr(profile, f))
        for f in RATE_FIELDS
    )


def _reject_out_of_order_adjust(
    db: Session, profile: SalaryEmployeeProfile, effective_date: date,
) -> None:
    """已有更晚生效的调薪时，拒绝补录更早的。

    引擎按生效日把调薪记录串成链、用后一条的 old_value 推前一段的费率；
    old_value 记的是录入那一刻的档案。先录 5/1 到 5000、再补录 3/15 到 4500，
    补录那条的 old_value 是 5000、档案也被盖成 4500——3、4、5 三个月全算错。
    """
    later = (
        db.query(SalaryChangeLog)
        .filter(SalaryChangeLog.employee_id == profile.id,
                SalaryChangeLog.change_type.in_(RATE_CHANGE_TYPES),
                SalaryChangeLog.effective_date > effective_date)
        .order_by(SalaryChangeLog.effective_date.desc())
        .first()
    )
    if later is not None:
        raise ProfileChangeError(
            f"{profile.name} 已有 {later.effective_date} 生效的调薪调级，晚于这次填的 "
            f"{effective_date}。系统只能按时间顺序登记调薪，倒着补录会把前后几个月的"
            f"底薪都推错。{effective_date} 到 {later.effective_date} 之间少发或多发的差额，"
            "请在对应批次的「其他加减」里处理"
        )


def pay_change_warnings(db: Session, payload: ProfileUpdate) -> list[str]:
    """改了定薪/职级后，哪些已算过的批次不会自动跟上。

    改档案不会回写任何批次：已锁定的要解锁重算或在后续批次补差，
    已算过的要重算。不提示的话，HR 以为改完就生效，钱静默按旧数发出去。
    adjust 只看生效月起的批次；correction 视为一直是新值，所有已算批次都受影响。
    """
    from app.salary import period_service  # period_service 依赖本模块，延迟导入避环
    from app.salary.models import SalaryPeriod

    q = db.query(SalaryPeriod).filter(SalaryPeriod.status.in_((
        period_service.STATUS_CALCULATED,
        period_service.STATUS_REVIEWING,
        period_service.STATUS_CONFIRMED,
    )))
    if payload.pay_change_kind == "adjust" and payload.pay_effective_date is not None:
        q = q.filter(SalaryPeriod.year_month >= payload.pay_effective_date.strftime("%Y-%m"))
    warnings = []
    for p in q.order_by(SalaryPeriod.year_month).all():
        if p.status == period_service.STATUS_CONFIRMED:
            warnings.append(f"{p.year_month} 批次已锁定，不会自动按新底薪重算："
                            "需管理员解锁后重算，或在后续批次的「其他加减」里补差")
        else:
            warnings.append(f"{p.year_month} 批次已算过，重新计算后才按新底薪出数")
    return warnings


def _jsonable(d: dict[str, Any]) -> dict[str, Any]:
    """Decimal / date 转成 JSON 列能存的形态。"""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, Decimal):
            out[k] = str(v)
        elif isinstance(v, date):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def update_profile(
    db: Session,
    profile: SalaryEmployeeProfile,
    payload: ProfileUpdate,
    operator_user_id: Optional[int] = None,
) -> SalaryEmployeeProfile:
    data = payload.model_dump(
        exclude_unset=True,
        exclude={"id_card", "bank_card", "pay_change_kind", "pay_effective_date"},
    )
    # 先校验再动档案：抛错时 profile 还没被改脏，session 里不留半截状态
    if _rate_change_requested(profile, data):
        if payload.pay_change_kind is None:
            raise ProfileChangeError("改了定薪或职级，请选择是「调薪调级」还是「更正录入错误」")
        if payload.pay_change_kind == "adjust" and payload.pay_effective_date is None:
            raise ProfileChangeError("调薪调级必须填写生效日期")
        if payload.pay_change_kind == "adjust":
            _reject_out_of_order_adjust(db, profile, payload.pay_effective_date)
    before = {f: getattr(profile, f) for f in _PAY_AFFECTING_FIELDS}
    for field, value in data.items():
        setattr(profile, field, value)
    after = {f: getattr(profile, f) for f in _PAY_AFFECTING_FIELDS}
    _log_pay_changes(db, profile, before, after, operator_user_id,
                     kind=payload.pay_change_kind, effective_date=payload.pay_effective_date)
    _apply_pii(profile, id_card=payload.id_card, bank_card=payload.bank_card)
    # updated_at 交给 Column 的 onupdate，不在这里显式赋值——两处各写一次会漂。
    db.commit()
    db.refresh(profile)
    return profile


def serialize_profile(
    profile: SalaryEmployeeProfile,
    dept_map: dict[str, str],
    grade_map: dict[tuple[str, str], SalaryGradeTable],
) -> dict[str, Any]:
    """出站序列化。PII 只出脱敏串——明文与密文都不进响应。"""
    return {
        "id": profile.id,
        "emp_no": profile.emp_no,
        "name": profile.name,
        "user_id": profile.user_id,
        "id_card_masked": pii.mask_pii(pii.decrypt_pii(profile.id_card_cipher), 3, 4),
        "bank_card_masked": pii.mask_pii(pii.decrypt_pii(profile.bank_card_cipher), 4, 4),
        "bank_name": profile.bank_name,
        "hire_date": profile.hire_date,
        "regular_date": profile.regular_date,
        "leave_date": profile.leave_date,
        "status": profile.status,
        "dept_detail": profile.dept_detail,
        "dept_group": resolve_dept_group(profile, dept_map),
        "dept_group_override": profile.dept_group_override,
        "position": profile.position,
        "grade_scheme": profile.grade_scheme,
        "grade_code": profile.grade_code,
        "base_salary_override": profile.base_salary_override,
        "base_salary_effective": resolve_base_salary(profile, grade_map),
        "probation_salary": profile.probation_salary,
        "probation_note": profile.probation_note,
        "guaranteed_salary": profile.guaranteed_salary,
        "guaranteed_from": profile.guaranteed_from,
        "guaranteed_to": profile.guaranteed_to,
        "insurance_entity": profile.insurance_entity,
        "payroll_included": profile.payroll_included,
        "fund_included": profile.fund_included,
        "special_calc": profile.special_calc,
        "seniority_override": profile.seniority_override,
        "dingtalk_userid": profile.dingtalk_userid,
        "mobile": profile.mobile,
        "remark": profile.remark,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


_SORTABLE = {
    "emp_no": SalaryEmployeeProfile.emp_no,
    "name": SalaryEmployeeProfile.name,
    "hire_date": SalaryEmployeeProfile.hire_date,
    "dept_detail": SalaryEmployeeProfile.dept_detail,
    "position": SalaryEmployeeProfile.position,
    "grade_code": SalaryEmployeeProfile.grade_code,
    "created_at": SalaryEmployeeProfile.created_at,
}


def list_profiles(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str = "",
    dept_detail: str = "",
    status: str = "",
    payroll_included: Optional[int] = None,
    sort_field: str = "emp_no",
    sort_order: str = "asc",
) -> dict[str, Any]:
    q = db.query(SalaryEmployeeProfile)
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter(
            or_(
                SalaryEmployeeProfile.name.like(like),
                SalaryEmployeeProfile.emp_no.like(like),
                SalaryEmployeeProfile.position.like(like),
            )
        )
    if dept_detail:
        q = q.filter(SalaryEmployeeProfile.dept_detail == dept_detail)
    if status:
        q = q.filter(SalaryEmployeeProfile.status == status)
    if payroll_included is not None:
        q = q.filter(SalaryEmployeeProfile.payroll_included == payroll_included)

    total = q.with_entities(func.count(SalaryEmployeeProfile.id)).scalar() or 0

    profile = SalaryEmployeeProfile
    if sort_field == "bank_card_masked" and sort_order in ("asc", "desc"):
        # Only this explicitly requested display sort materializes the filtered
        # identifiers and card ciphers. Retain masks only, then fetch one page.
        masked_rows = [
            {"id": row.id, "masked": pii.mask_pii(pii.decrypt_pii(row.bank_card_cipher), 4, 4) or None}
            for row in q.with_entities(profile.id, profile.bank_card_cipher).all()
        ]
        sorted_rows = apply_items_sort(masked_rows, sort_field, sort_order, {"bank_card_masked": "masked"})
        start = (page - 1) * page_size
        page_ids = [row["id"] for row in sorted_rows[start:start + page_size]]
        page_rows = {row.id: row for row in q.filter(profile.id.in_(page_ids)).all()} if page_ids else {}
        dept_map = load_dept_group_map(db)
        grade_map = load_grade_map(db)
        return {
            "items": [serialize_profile(page_rows[row_id], dept_map, grade_map) for row_id in page_ids],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    department = db.query(SalaryDeptMapping.dept_group).filter(SalaryDeptMapping.dept_detail == profile.dept_detail).correlate(profile).scalar_subquery()
    today = beijing_today()
    grade_salary = db.query(case((SalaryGradeTable.scheme.in_(_STD_SALARY_SCHEMES), SalaryGradeTable.std_salary), else_=SalaryGradeTable.base_salary)).filter(
        SalaryGradeTable.scheme == profile.grade_scheme, SalaryGradeTable.grade_code == profile.grade_code,
        SalaryGradeTable.effective_from <= today,
        or_(SalaryGradeTable.effective_to.is_(None), SalaryGradeTable.effective_to >= today),
    ).order_by(SalaryGradeTable.effective_from.desc()).limit(1).correlate(profile).scalar_subquery()
    columns = {**_SORTABLE, "status": profile.status, "dept_group": func.coalesce(func.nullif(profile.dept_group_override, ""), department), "base_salary_effective": func.coalesce(profile.base_salary_override, grade_salary)}
    q = apply_list_sort(q, sort_field, sort_order, columns, default=(profile.emp_no.asc(),), tie_breakers=(profile.id.asc(),))
    rows = q.offset((page - 1) * page_size).limit(page_size).all()

    dept_map = load_dept_group_map(db)
    grade_map = load_grade_map(db)
    return {
        "items": [serialize_profile(r, dept_map, grade_map) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def find_by_id_card(db: Session, id_card_plain: str) -> Optional[SalaryEmployeeProfile]:
    """按身份证明文查档案。匹配走 hash 列——密文列 IV 随机，JOIN 不了。

    M2 的社保/公积金导入靠它把源表的明文身份证接到档案上。
    """
    h = pii.hash_pii(pii.normalize_id_card(id_card_plain))
    if not h:
        return None
    return db.query(SalaryEmployeeProfile).filter(SalaryEmployeeProfile.id_card_hash == h).first()


# ---------------------------------------------------------------------------
# 职级表 / 规则参数 / 部门映射
# ---------------------------------------------------------------------------

def list_grades(db: Session, scheme: str = "", on_date: Optional[date] = None) -> list[SalaryGradeTable]:
    q = db.query(SalaryGradeTable)
    if scheme:
        q = q.filter(SalaryGradeTable.scheme == scheme)
    if on_date:
        q = q.filter(SalaryGradeTable.effective_from <= on_date).filter(
            or_(SalaryGradeTable.effective_to.is_(None), SalaryGradeTable.effective_to >= on_date)
        )
    return q.order_by(
        SalaryGradeTable.scheme,
        SalaryGradeTable.effective_from.desc(),
        SalaryGradeTable.id,
    ).all()


def upsert_grade(db: Session, payload: GradeUpsert) -> SalaryGradeTable:
    """按 (scheme, grade_code, effective_from) upsert。改口径请新建生效日版本。"""
    row = (
        db.query(SalaryGradeTable)
        .filter(
            SalaryGradeTable.scheme == payload.scheme,
            SalaryGradeTable.grade_code == payload.grade_code,
            SalaryGradeTable.effective_from == payload.effective_from,
        )
        .first()
    )
    data = payload.model_dump()
    if row is None:
        row = SalaryGradeTable(**data)
        db.add(row)
    else:
        for field, value in data.items():
            setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


def list_rule_params(db: Session, category: str = "", on_date: Optional[date] = None) -> list[SalaryRuleParam]:
    q = db.query(SalaryRuleParam)
    if category:
        q = q.filter(SalaryRuleParam.category == category)
    if on_date:
        q = q.filter(SalaryRuleParam.effective_from <= on_date).filter(
            or_(SalaryRuleParam.effective_to.is_(None), SalaryRuleParam.effective_to >= on_date)
        )
    return q.order_by(SalaryRuleParam.category, SalaryRuleParam.param_key).all()


def load_params(db: Session, on_date: Optional[date] = None) -> dict[str, str]:
    """取生效参数快照（key → 原始字符串）。M3 计算前冻结进 period.param_snapshot。"""
    d = on_date or beijing_today()
    rows = (
        db.query(SalaryRuleParam)
        .filter(SalaryRuleParam.effective_from <= d)
        .filter(or_(SalaryRuleParam.effective_to.is_(None), SalaryRuleParam.effective_to >= d))
        .order_by(SalaryRuleParam.effective_from)
        .all()
    )
    return {r.param_key: r.param_value for r in rows}


def param_decimal(params: dict[str, str], key: str, default: Decimal) -> Decimal:
    """从参数快照取 Decimal。取不到或格式坏时回默认值并告警——静默算 0 会算错钱。"""
    raw = params.get(key)
    if raw is None:
        return default
    try:
        return Decimal(str(raw))
    except Exception as exc:  # noqa: BLE001
        logger.warning("薪资参数 %s=%r 无法转 Decimal，回落默认 %s: %s", key, raw, default, exc)
        print(f"[salary.service] bad param {key}={raw!r}: {exc}", flush=True)
        return default


def param_bool(params: dict[str, str], key: str, default: bool = False) -> bool:
    raw = params.get(key)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")


def list_dept_mappings(db: Session) -> list[SalaryDeptMapping]:
    return db.query(SalaryDeptMapping).order_by(
        SalaryDeptMapping.sort_order, SalaryDeptMapping.dept_detail
    ).all()


def upsert_dept_mapping(db: Session, payload: DeptMappingUpsert) -> SalaryDeptMapping:
    row = (
        db.query(SalaryDeptMapping)
        .filter(SalaryDeptMapping.dept_detail == payload.dept_detail)
        .first()
    )
    if row is None:
        row = SalaryDeptMapping(**payload.model_dump())
        db.add(row)
    else:
        row.dept_group = payload.dept_group
        row.sort_order = payload.sort_order
    db.commit()
    db.refresh(row)
    return row
