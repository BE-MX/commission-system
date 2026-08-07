"""薪资模块 — API 路由（M1：档案 / 职级表 / 规则参数 / 部门映射）。

权限：salary:read（看）/ salary:write（维护主数据）/ salary:admin（锁定批次、解密）。
统一信封 ok()。**响应里永不出现身份证/银行卡明文**，脱敏在 service.serialize_profile。
"""

import calendar
import logging
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok
from app.salary import (
    anomaly_service,
    attendance_service,
    attendance_source,
    calc_service,
    import_persist,
    period_service,
    service,
)
from app.salary.import_service import SalaryImportError
from app.salary.models import SalaryEmployeeProfile, SalaryRuleParam
from app.salary.schemas import (
    GRADE_SCHEMES,
    AttendanceManualUpsert,
    AttendanceSync,
    DeptMappingUpsert,
    GradeUpsert,
    PeriodCalculate,
    PeriodConfirm,
    PeriodCreate,
    PeriodTransition,
    PeriodUnlock,
    PeriodWorkdayUpdate,
    ProfileCreate,
    ProfileUpdate,
    RecordManualEdit,
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


# ---------------------------------------------------------------------------
# 月度批次（M2-a）
# ---------------------------------------------------------------------------

def _get_period_or_404(db: Session, period_id: int):
    row = period_service.get_period(db, period_id)
    if not row:
        raise HTTPException(status_code=404, detail="批次不存在")
    return row


@router.get("/periods", summary="工资批次列表")
def list_periods(
    status: str = Query(""),
    limit: int = Query(60, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*_READ_PERMS)),
):
    rows = period_service.list_periods(db, status=status, limit=limit)
    return ok([period_service.serialize_period(r) for r in rows])


@router.get("/periods/{period_id}", summary="批次详情")
def get_period(
    period_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*_READ_PERMS)),
):
    return ok(period_service.serialize_period(_get_period_or_404(db, period_id)))


@router.get("/periods/{period_id}/events", summary="批次事件时间线")
def list_period_events(
    period_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*_READ_PERMS)),
):
    _get_period_or_404(db, period_id)
    rows = period_service.list_events(db, period_id)
    names = period_service.operator_names(db, rows)
    return ok([
        {
            "id": e.id,
            "event_type": e.event_type,
            # 中文标签在后端出，不让前端再写一份映射：新增事件类型时前端会静默
            # 显示成 attendance_sync 这种 code，不报错也没人发现。
            "event_label": period_service.EVENT_LABELS.get(e.event_type, e.event_type),
            "from_status": e.from_status,
            "from_status_label": period_service.STATUS_LABELS.get(e.from_status or ""),
            "to_status": e.to_status,
            "to_status_label": period_service.STATUS_LABELS.get(e.to_status or ""),
            "status_version": e.status_version,
            "reason": e.reason,
            "payload": e.payload,
            "created_by": e.created_by,
            # 名字查不到时退回 id 字符串，而不是留空：时间线的用途就是
            # 「谁在什么时候把这批数据改了」，留空等于这条留痕白写了。
            "operator_name": names.get(e.created_by) or (str(e.created_by) if e.created_by else None),
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in rows
    ])


@router.post("/periods", summary="新建工资批次")
def create_period(
    payload: PeriodCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("salary:write")),
):
    try:
        row = period_service.create_period(
            db,
            payload.year_month,
            operator_id=_operator_id(current_user),
            workday_count=payload.workday_count,
            remark=payload.remark,
        )
    except period_service.SalaryPeriodError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except IntegrityError as exc:
        # 并发下两个人同时建同月批次：唯一键兜底，翻成友好文案
        db.rollback()
        logger.warning("薪资批次创建撞唯一键 ym=%s", payload.year_month)
        print(f"[salary.router] duplicate period {payload.year_month}: {type(exc).__name__}",
              flush=True)
        raise HTTPException(status_code=409, detail=f"{payload.year_month} 批次已存在")
    return ok(period_service.serialize_period(row))


@router.put("/periods/{period_id}/workday", summary="修改批次工作日数")
def update_period_workday(
    period_id: int,
    payload: PeriodWorkdayUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("salary:write")),
):
    row = _get_period_or_404(db, period_id)
    try:
        row = period_service.update_workday_count(
            db, row, payload.workday_count, operator_id=_operator_id(current_user)
        )
    except period_service.SalaryStaleVersion as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except period_service.SalaryPeriodError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(period_service.serialize_period(row))


@router.post("/periods/{period_id}/transition", summary="批次状态跃迁")
def transition_period(
    period_id: int,
    payload: PeriodTransition,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("salary:write")),
):
    """跃迁到目标状态。锁定（confirmed）需 salary:admin，走独立端点。"""
    row = _get_period_or_404(db, period_id)
    if payload.target == period_service.STATUS_CONFIRMED:
        raise HTTPException(status_code=400, detail="锁定批次请调用 /confirm 端点")
    try:
        row = period_service.transition(
            db, row, payload.target,
            expected_version=payload.expected_version,
            operator_id=_operator_id(current_user),
        )
    except period_service.SalaryStaleVersion as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except period_service.SalaryPeriodError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(period_service.serialize_period(row))


@router.post("/periods/{period_id}/confirm", summary="锁定批次")
def confirm_period(
    period_id: int,
    payload: PeriodConfirm,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("salary:admin")),
):
    """锁定后全表只读。爆炸半径大（工资已发即成定论），按 admin 分权。

    锁定前过负数实发门（§6）：有 final 实发 < 0 的行必须先在明细表处理，
    宁可拦住不发，也不能让银行盘出现负金额。
    """
    row = _get_period_or_404(db, period_id)
    try:
        calc_service.assert_confirmable(db, row)
        row = period_service.confirm(
            db, row,
            expected_version=payload.expected_version,
            operator_id=_operator_id(current_user),
        )
    except calc_service.CalcError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except period_service.SalaryStaleVersion as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except period_service.SalaryPeriodError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(period_service.serialize_period(row))


# ---------------------------------------------------------------------------
# 社保 / 公积金导入（M2-c）
# ---------------------------------------------------------------------------

# 上传体积上限。3 月社保表 66 人约 30KB，10MB 已经宽出两个数量级；
# 设这个门是因为解析器会把整个工作簿读进内存，没有上限时一个几百 MB 的误传
# 就能把后端进程撑爆——那是全站不可用，不只是这一个接口失败。
_MAX_IMPORT_BYTES = 10 * 1024 * 1024


@router.post("/periods/{period_id}/imports/{kind}", summary="导入社保/公积金明细")
def import_period_file(
    period_id: int,
    kind: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("salary:write")),
):
    """上传 .xls/.xlsx 明细，解析后按身份证哈希匹配档案并落库（同批次同类型覆盖重导）。"""
    row = _get_period_or_404(db, period_id)
    content = file.file.read(_MAX_IMPORT_BYTES + 1)
    if len(content) > _MAX_IMPORT_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"文件超过 {_MAX_IMPORT_BYTES // 1024 // 1024}MB，请确认上传的是社保/公积金明细表",
        )
    try:
        summary = import_persist.persist(
            db, row, kind, content,
            filename=file.filename,
            operator_id=_operator_id(current_user),
        )
    except period_service.SalaryStaleVersion as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except SalaryImportError as exc:
        # 解析失败是「换个文件重传」，不是系统故障：400 + 原文案，不要包装成 500
        raise HTTPException(status_code=400, detail=str(exc))
    except period_service.SalaryPeriodError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok({"summary": summary, "period": period_service.serialize_period(row)})


@router.get("/periods/{period_id}/imports/{kind}", summary="导入明细行列表")
def list_period_import_rows(
    period_id: int,
    kind: str,
    match_status: str = Query(""),
    keyword: str = Query(""),
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*_READ_PERMS)),
):
    _get_period_or_404(db, period_id)
    try:
        data = import_persist.list_rows(
            db, period_id, kind, match_status=match_status, keyword=keyword, limit=limit
        )
    except SalaryImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(data)


# ---------------------------------------------------------------------------
# 考勤（M2-d）
# ---------------------------------------------------------------------------

@router.post("/periods/{period_id}/attendance/sync", summary="从钉钉同步考勤")
async def sync_period_attendance(
    period_id: int,
    payload: AttendanceSync,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("salary:write")),
):
    """拉取钉钉考勤报表列值并落库。

    **取数在这里做、落库在 service 做**：取数是 async HTTP，service 层保持同步且
    不发网络请求——否则它的测试要么打真钉钉、要么 mock 一整套 httpx。

    请假小时（事假/病假/年假）钉钉给不了，同步结果里会用 missing_leave_columns
    明说，由人工录入端点补。
    """
    row = _get_period_or_404(db, period_id)
    # 先拦三道再打钉钉：66 人 × 2 片 = 132 次调用要跑一分钟，
    # 跑完再被 service 拒掉等于白等，还白吃一次限流额度。
    # 这三道与 service 里的同名检查是重复的，重复是故意的——service 那份是
    # 唯一的正确性保证（并发下只有它在事务里说话），这份纯为省时间。
    try:
        attendance_service.assert_syncable(row)
    except attendance_service.AttendanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except period_service.SalaryPeriodError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    year, month = (int(x) for x in row.year_month.split("-"))
    # natural_days 建批次时已算好；为空时现算，不让一个缺字段挡住同步
    natural_days = row.natural_days or calendar.monthrange(year, month)[1]
    profiles_by_uid, duplicate_userids = attendance_service.profiles_by_userid(db)
    if duplicate_userids:
        detail = "、".join(
            f"{uid}（{'/'.join(names)}）" for uid, names in duplicate_userids.items()
        )
        raise HTTPException(
            status_code=400,
            detail=f"以下钉钉 userid 被多份员工档案共用，同步会让其中一人考勤为空：{detail}。"
                   "请先到员工档案里把绑定改对再同步。",
        )
    userids = sorted(profiles_by_uid)
    if not userids:
        raise HTTPException(
            status_code=400,
            detail="发薪名单里没有任何人绑定了钉钉 userid，请先在员工档案里补齐绑定",
        )

    from_date, to_date = attendance_source.month_range(year, month, natural_days)
    try:
        results, missing_leave = await attendance_source.fetch_many(
            userids, from_date, to_date
        )
    except attendance_source.AttendanceSourceError as exc:
        # 取数失败是「钉钉那边的事」，不是我们 500：给原文案让 HR 能自己判断
        raise HTTPException(status_code=502, detail=str(exc))

    try:
        summary = attendance_service.sync_from_dingtalk(
            db, row, {"results": results, "missing_leave": missing_leave},
            expected_version=payload.expected_version,
            operator_id=_operator_id(current_user),
        )
    except period_service.SalaryStaleVersion as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except period_service.SalaryPeriodError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except attendance_service.AttendanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok({"summary": summary, "period": period_service.serialize_period(row)})


@router.get("/periods/{period_id}/attendance", summary="批次考勤明细")
def list_period_attendance(
    period_id: int,
    keyword: str = Query(""),
    only_pending: bool = Query(False, description="只看请假小时还没录的人"),
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*_READ_PERMS)),
):
    _get_period_or_404(db, period_id)
    return ok(attendance_service.list_rows(
        db, period_id, keyword=keyword, only_pending=only_pending, limit=limit
    ))


@router.put("/periods/{period_id}/attendance/{employee_id}", summary="人工录入/修正考勤")
def upsert_period_attendance(
    period_id: int,
    employee_id: int,
    payload: AttendanceManualUpsert,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("salary:write")),
):
    """事假/病假小时的唯一录入口（钉钉取不到，见 attendance_source 约束 2/3）。

    未传的字段保持原值，不当作清零——HR 常常只改一格。
    """
    row = _get_period_or_404(db, period_id)
    body = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    if not body:
        raise HTTPException(status_code=400, detail="没有需要修改的字段")
    try:
        record = attendance_service.manual_upsert(
            db, row, employee_id, body,
            expected_version=payload.expected_version,
            operator_id=_operator_id(current_user),
        )
    except period_service.SalaryStaleVersion as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except attendance_service.AttendanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except period_service.SalaryPeriodError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    profile = db.query(SalaryEmployeeProfile).filter(
        SalaryEmployeeProfile.id == employee_id
    ).first()
    return ok(attendance_service.serialize_row(record, profile))


@router.get("/periods/{period_id}/anomalies", summary="异常面板")
def list_period_anomalies(
    period_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*_READ_PERMS)),
):
    """聚合本批次的全部待办异常。

    读接口，read 权限即可——**看得见问题的人应该比能改的人多**。
    响应里的 ready_to_calculate 由后端算，前端不要自己数 blocking_count，
    两边各数一次迟早会数出不一样的结果。
    """
    row = _get_period_or_404(db, period_id)
    return ok(anomaly_service.collect(db, row))


# ---------------------------------------------------------------------------
# 计算引擎与工资明细（M3）
# ---------------------------------------------------------------------------

@router.post("/periods/{period_id}/calculate", summary="计算/重算整批工资")
def calculate_period(
    period_id: int,
    payload: PeriodCalculate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("salary:write")),
):
    """整批计算。前置异常面板的 blocking 清完才给算（ready_to_calculate 门）。

    重算是幂等的：引擎列与 auto 列重写，manual 列原样保留（A2），
    「auto 变了但 manual 盖着」的行在 summary.override_changed 里点名。
    """
    row = _get_period_or_404(db, period_id)
    try:
        summary = calc_service.calculate_period(
            db, row,
            expected_version=payload.expected_version,
            operator_id=_operator_id(current_user),
        )
    except period_service.SalaryStaleVersion as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except calc_service.CalcError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except period_service.SalaryPeriodError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok({"summary": summary, "period": period_service.serialize_period(row)})


@router.get("/periods/{period_id}/records", summary="工资明细行（23 列）")
def list_period_records(
    period_id: int,
    keyword: str = Query(""),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*_READ_PERMS)),
):
    """整批明细，不分页（66 人一屏看完）。confirmed 后快照列优先于活档案。"""
    row = _get_period_or_404(db, period_id)
    return ok(calc_service.list_records(db, row.id, keyword=keyword))


@router.put("/periods/{period_id}/records/{employee_id}", summary="行内编辑手动列")
def edit_period_record(
    period_id: int,
    employee_id: int,
    payload: RecordManualEdit,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("salary:write")),
):
    """复核期改奖励/绩效/其他款/补贴/个税。行级乐观锁：版本不符返回 409。

    传 null = 清除人工覆盖（final 回落引擎值）；不传 = 不动该列。
    改完用引擎同一套公式重算该行小计/实发，补贴 auto 会按新生效值重判定。
    """
    row = _get_period_or_404(db, period_id)
    updates = payload.model_dump(
        exclude_unset=True, exclude={"expected_row_version", "modify_reason"})
    if not updates:
        raise HTTPException(status_code=400, detail="没有需要修改的字段")
    try:
        record = calc_service.edit_record_manual(
            db, row, employee_id, updates,
            expected_row_version=payload.expected_row_version,
            reason=payload.modify_reason,
            operator_id=_operator_id(current_user),
        )
    except period_service.SalaryStaleVersion as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except calc_service.CalcError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except period_service.SalaryPeriodError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    profile = db.query(SalaryEmployeeProfile).filter(
        SalaryEmployeeProfile.id == employee_id).first()
    return ok(calc_service.serialize_record(record, profile))


@router.post("/periods/{period_id}/unlock", summary="解锁已锁定批次")
def unlock_period(
    period_id: int,
    payload: PeriodUnlock,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("salary:admin")),
):
    """决策 A4：解锁重出，前次导出打作废水印。reason 必填且留痕。"""
    row = _get_period_or_404(db, period_id)
    try:
        row = period_service.unlock(
            db, row, payload.reason,
            expected_version=payload.expected_version,
            operator_id=_operator_id(current_user),
        )
    except period_service.SalaryStaleVersion as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except period_service.SalaryPeriodError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(period_service.serialize_period(row))
