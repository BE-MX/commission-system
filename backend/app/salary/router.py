"""薪资模块 — API 路由（M1：档案 / 职级表 / 规则参数 / 部门映射）。

权限：salary:read（看）/ salary:write（维护主数据）/ salary:admin（锁定批次、解密）。
统一信封 ok()。**响应里永不出现身份证/银行卡明文**，脱敏在 service.serialize_profile。
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok
from app.salary import service
from app.salary.models import SalaryEmployeeProfile, SalaryRuleParam
from app.salary.schemas import (
    GRADE_SCHEMES,
    DeptMappingUpsert,
    GradeUpsert,
    ProfileCreate,
    ProfileUpdate,
    RuleParamUpdate,
)

logger = logging.getLogger("commission")

router = APIRouter()

_READ_PERMS = ("salary:read", "salary:write", "salary:admin")


def _operator_id(current_user: dict) -> int | None:
    """从 JWT claims 取操作人 id。取不到返回 None——留痕缺个人名也不该挡住保存。"""
    raw = current_user.get("sub")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _get_profile_or_404(db: Session, profile_id: int) -> SalaryEmployeeProfile:
    row = db.query(SalaryEmployeeProfile).filter(SalaryEmployeeProfile.id == profile_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="员工档案不存在")
    return row


# 约束名与列名两套 token 都列上：MySQL 的 1062 报约束名（uk_...），
# SQLite 报「表名.列名」。只认一种的话，另一种环境下会退回无信息的兜底文案。
_CONSTRAINT_MESSAGES = (
    ("uk_salary_profile_emp_no", "工号已存在（注意 3 与 003 会归一成同一个工号）"),
    (".emp_no", "工号已存在（注意 3 与 003 会归一成同一个工号）"),
    ("uk_salary_profile_id_card", "身份证已被其他员工档案占用"),
    (".id_card_hash", "身份证已被其他员工档案占用"),
    ("ark_salary_employee_profile_ibfk", "关联的平台账号不存在，请重新选择或留空"),
    ("FOREIGN KEY", "关联的平台账号不存在，请重新选择或留空"),
)


def _integrity_context(exc: IntegrityError) -> tuple[str, str]:
    """把入库失败翻成 (给用户的话, 可安全落日志的标识)。

    **不要把 exc 本体写进日志**：SQLAlchemy 的 str(IntegrityError) 会带上完整
    `[SQL: INSERT ...] [parameters: (...)]`，参数里就是身份证/银行卡的密文与 HMAC
    摘要。身份证号空间小，哈希一旦落进 NSSM 的明文 service.log，配合密钥泄漏即可
    反查。所以只回传命中的约束名（固定字符串），不回传异常内容。
    """
    text = str(getattr(exc, "orig", exc))
    for token, message in _CONSTRAINT_MESSAGES:
        if token in text:
            return message, token
    return "保存失败：数据唯一性冲突", "unknown_constraint"


# ---------------------------------------------------------------------------
# 员工档案
# ---------------------------------------------------------------------------

@router.get("/profiles", summary="员工薪资档案列表")
def list_profiles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str = Query(""),
    dept_detail: str = Query(""),
    status: str = Query("", pattern="^(active|left)?$"),
    payroll_included: int | None = Query(None, ge=0, le=1),
    sort_field: str = Query("emp_no"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*_READ_PERMS)),
):
    data = service.list_profiles(
        db,
        page=page,
        page_size=page_size,
        keyword=keyword,
        dept_detail=dept_detail,
        status=status,
        payroll_included=payroll_included,
        sort_field=sort_field,
        sort_order=sort_order,
    )
    return ok(data)


@router.get("/profiles/{profile_id}", summary="员工薪资档案详情")
def get_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*_READ_PERMS)),
):
    profile = _get_profile_or_404(db, profile_id)
    return ok(
        service.serialize_profile(
            profile, service.load_dept_group_map(db), service.load_grade_map(db)
        )
    )


@router.post("/profiles", summary="新建员工薪资档案")
def create_profile(
    payload: ProfileCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("salary:write")),
):
    try:
        profile = service.create_profile(db, payload)
    except IntegrityError as exc:
        db.rollback()
        message, token = _integrity_context(exc)
        logger.warning("薪资档案创建入库失败，命中约束 %s", token)
        print(f"[salary.router] create profile rejected by {token}", flush=True)
        raise HTTPException(status_code=409, detail=message)
    return ok(
        service.serialize_profile(
            profile, service.load_dept_group_map(db), service.load_grade_map(db)
        )
    )


@router.put("/profiles/{profile_id}", summary="编辑员工薪资档案")
def update_profile(
    profile_id: int,
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("salary:write")),
):
    profile = _get_profile_or_404(db, profile_id)
    try:
        profile = service.update_profile(
            db, profile, payload, operator_user_id=_operator_id(current_user)
        )
    except IntegrityError as exc:
        db.rollback()
        message, token = _integrity_context(exc)
        logger.warning("薪资档案编辑入库失败，命中约束 %s", token)
        print(f"[salary.router] update profile rejected by {token}", flush=True)
        raise HTTPException(status_code=409, detail=message)
    return ok(
        service.serialize_profile(
            profile, service.load_dept_group_map(db), service.load_grade_map(db)
        )
    )


# ---------------------------------------------------------------------------
# 规则配置（职级表 / 参数 / 部门映射）
# ---------------------------------------------------------------------------

@router.get("/grades", summary="职级薪级表")
def list_grades(
    scheme: str = Query(""),
    include_history: int = Query(
        0, ge=0, le=1, description="1=含历史版本（规则页用）；0=只返回当前生效版本（下拉用）",
    ),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*_READ_PERMS)),
):
    # 默认只出当前生效版本：档案页职级下拉按 grade_code 做 key，
    # 一旦 HR 建了未来生效的新版本，全量返回会让同一个 P1 出现两行、
    # key 重复且无从判断选哪个。规则页要看历史，显式传 include_history=1。
    rows = service.list_grades(db, scheme=scheme, on_date=None if include_history else date.today())
    return ok({
        "schemes": [{"code": k, "label": v} for k, v in GRADE_SCHEMES.items()],
        "items": [
            {
                "id": r.id,
                "scheme": r.scheme,
                "grade_code": r.grade_code,
                "base_salary": r.base_salary,
                "perf_full": r.perf_full,
                "std_salary": r.std_salary,
                "perf_target_monthly": r.perf_target_monthly,
                "new_sign_min": r.new_sign_min,
                "team_rate": r.team_rate,
                "effective_from": r.effective_from,
                "effective_to": r.effective_to,
            }
            for r in rows
        ],
    })


@router.post("/grades", summary="新增/更新职级薪级行")
def upsert_grade(
    payload: GradeUpsert,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("salary:admin")),
):
    # 为什么是 admin 而不是 write：档案改动影响 1 个人，职级表与规则参数是全员
    # 发薪口径的来源，改一行动 66 人的钱。按爆炸半径分权，不按「是不是主数据」分。
    row = service.upsert_grade(db, payload)
    return ok({"id": row.id})


@router.get("/params", summary="规则参数列表")
def list_params(
    category: str = Query(""),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*_READ_PERMS)),
):
    rows = service.list_rule_params(db, category=category)
    return ok([
        {
            "id": r.id,
            "param_key": r.param_key,
            "param_value": r.param_value,
            "value_type": r.value_type,
            "category": r.category,
            "description": r.description,
            "effective_from": r.effective_from,
            "effective_to": r.effective_to,
        }
        for r in rows
    ])


@router.put("/params/{param_id}", summary="修改规则参数值")
def update_param(
    param_id: int,
    payload: RuleParamUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("salary:admin")),
):
    row = db.query(SalaryRuleParam).filter(SalaryRuleParam.id == param_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="规则参数不存在")
    old_value = row.param_value
    row.param_value = payload.param_value
    if payload.description is not None:
        row.description = payload.description
    # 参数是全员发薪口径，原地改必须留痕：否则「谁把全勤奖从 100 改成 150」查无对证。
    # employee_id 为空表示这是全局口径变更而非某个人的档案改动。
    if old_value != payload.param_value:
        logger.warning(
            "薪资规则参数变更 %s: %s → %s (by user=%s)",
            row.param_key, old_value, payload.param_value, _operator_id(current_user),
        )
        print(
            f"[salary.router] param {row.param_key}: {old_value} -> {payload.param_value}"
            f" by user={_operator_id(current_user)}",
            flush=True,
        )
    db.commit()
    return ok({"id": row.id, "param_key": row.param_key, "param_value": row.param_value})


@router.get("/dept-mappings", summary="明细部门 → 大部门映射")
def list_dept_mappings(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*_READ_PERMS)),
):
    rows = service.list_dept_mappings(db)
    return ok([
        {
            "id": r.id,
            "dept_detail": r.dept_detail,
            "dept_group": r.dept_group,
            "sort_order": r.sort_order,
        }
        for r in rows
    ])


@router.post("/dept-mappings", summary="新增/更新部门映射")
def upsert_dept_mapping(
    payload: DeptMappingUpsert,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("salary:write")),
):
    row = service.upsert_dept_mapping(db, payload)
    return ok({"id": row.id})
