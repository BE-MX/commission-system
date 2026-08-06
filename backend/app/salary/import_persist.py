"""薪资模块 — 社保/公积金导入落库 + 档案匹配（M2-c）。

与 `import_service` 的分工是硬的：那边是纯函数解析器（docstring 里写明「不碰 session」），
这边负责事务、匹配、替换语义与留痕。混在一起会让解析器再也没法在没有数据库的环境下测。

三条设计红线：

1. **整批导入是一个事务，守卫在最后一条 SQL 上。**
   逐行 insert 全程不 commit，最后用 `period_service.guarded_write` 收口——
   它的 UPDATE 谓词里带 `status != 'confirmed'` 和 `status_version`。若这期间
   有人锁定了批次，rowcount==0 → 内部 `db.rollback()` 把**这批还没提交的行一起
   丢掉**。所以「锁定后还能把数据塞进已发工资的批次」这条路是被数据库堵死的，
   不是靠 Python 里那句 `assert_writable` 堵的（那句只负责早失败 + 给好文案）。

2. **同一份文件里身份证撞号，两行一起作废，不挑一行。**
   3 月公积金表的刘也/姜婷就是这种誊抄错误（设计文档 §2.5 错误 3）。两行哈希相同，
   挑任意一行落 matched，都会让真正的档案主人拿到别人的公积金扣款，而另一个人凭空
   消失——且金额总数还对得上，对账发现不了。所以标 `duplicate` 全部剔出计算，
   逼 HR 去改源表。宁可少扣，不可错扣。

3. **参保 ⊋ 发薪。** 8 个人只参保不发薪（§2.2）。他们必须落库（否则「个人合计对不上
   工资表社保合计」永远查不清），但绝不能进计算。判定只认档案的 `payroll_included`，
   不认源表的部门文本——曹其宽/张传明在社保表里挂着外贸部，按部门判就会把他们算进工资表。
"""

from __future__ import annotations

import logging
from collections import Counter
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.salary import import_service, period_service, pii
from app.salary.import_service import ParseResult, ParsedPersonRow, SalaryImportError
from app.salary.models import (
    SalaryEmployeeProfile,
    SalaryFundImport,
    SalaryInsuranceImport,
    SalaryPeriod,
)

logger = logging.getLogger("commission")

KIND_INSURANCE = "insurance"
KIND_FUND = "fund"
KINDS = (KIND_INSURANCE, KIND_FUND)
KIND_LABELS = {KIND_INSURANCE: "社保", KIND_FUND: "公积金"}

MATCH_MATCHED = "matched"
MATCH_NOT_PAYROLL = "not_payroll"
MATCH_UNMATCHED = "unmatched"
MATCH_DUPLICATE = "duplicate"

MATCH_LABELS = {
    MATCH_MATCHED: "已匹配",
    MATCH_NOT_PAYROLL: "参保未发薪",
    MATCH_UNMATCHED: "未匹配档案",
    MATCH_DUPLICATE: "身份证撞号（源表誊抄错误）",
}

# 只有 matched 的行进 M3 的减项。这个常量是给下游用的，别在别处再抄一份判断。
DEDUCTIBLE_STATUSES = (MATCH_MATCHED,)

_MODELS = {KIND_INSURANCE: SalaryInsuranceImport, KIND_FUND: SalaryFundImport}

# IN 子句分片：单次 5000 个 64 位哈希串约 320KB，虽在默认 max_allowed_packet 之内，
# 但没必要贴着上限跑。分片是零成本的保险。
_IN_CHUNK = 500

# 复核中不许重新导入：这时数已经在被人逐行核对，把社保数据换掉而不改状态，
# 复核者手上的结论就悄悄失效了。让他先退回「已计算」是一次明确的意思表示。
_BLOCKED_STATUSES = {
    period_service.STATUS_REVIEWING: (
        "批次正在复核中，重新导入会让已复核的数据失效。请先在批次页退回「已计算」再导入。"
    ),
}


# ---------------------------------------------------------------------------
# 匹配
# ---------------------------------------------------------------------------

def _load_profiles(db: Session, hashes: set[str]) -> dict[str, SalaryEmployeeProfile]:
    """按 id_card_hash 批量取档案。hash 列有唯一约束，一个哈希最多一条档案。"""
    out: dict[str, SalaryEmployeeProfile] = {}
    ordered = [h for h in hashes if h]
    for i in range(0, len(ordered), _IN_CHUNK):
        chunk = ordered[i : i + _IN_CHUNK]
        rows = (
            db.query(SalaryEmployeeProfile)
            .filter(SalaryEmployeeProfile.id_card_hash.in_(chunk))
            .all()
        )
        for row in rows:
            out[row.id_card_hash] = row
    return out


def classify(
    row: ParsedPersonRow,
    profiles: dict[str, SalaryEmployeeProfile],
    hash_counts: Counter,
) -> tuple[str, Optional[int]]:
    """给一行定匹配状态，返回 (match_status, employee_id)。

    判定顺序不能换：撞号必须排在「匹配到档案」之前。撞号的两行里往往有一行
    确实能匹配上档案（哈希本来就是从某个真人的身份证抄错来的），先判匹配就会把
    那一行放行，错误照旧进计算。
    """
    if not row.id_card_hash:
        return MATCH_UNMATCHED, None
    if hash_counts[row.id_card_hash] > 1:
        return MATCH_DUPLICATE, None
    profile = profiles.get(row.id_card_hash)
    if profile is None:
        return MATCH_UNMATCHED, None
    if not profile.payroll_included:
        return MATCH_NOT_PAYROLL, profile.id
    return MATCH_MATCHED, profile.id


# ---------------------------------------------------------------------------
# 落库
# ---------------------------------------------------------------------------

def _build_insurance(period_id: int, row: ParsedPersonRow, status: str,
                     employee_id: Optional[int]) -> SalaryInsuranceImport:
    return SalaryInsuranceImport(
        period_id=period_id,
        employee_id=employee_id,
        entity=row.entity,
        name=row.name,
        id_card_hash=row.id_card_hash,
        id_card_cipher=row.id_card_cipher,
        base_amount=row.base_amount,
        personal_total=row.personal_total,
        company_total=row.company_total,
        # 行级 warning 一并入库：异常面板要能告诉 HR「第 37 行分项之和对不上」，
        # 只留在解析结果的内存对象里，刷新页面就没了。
        detail_json={"sheet": row.sheet, "row_no": row.row_no,
                     **row.detail,
                     **({"warnings": row.warnings} if row.warnings else {})},
        match_status=status,
        dept_text=row.dept_text,
    )


def _build_fund(period_id: int, row: ParsedPersonRow, status: str,
                employee_id: Optional[int]) -> SalaryFundImport:
    return SalaryFundImport(
        period_id=period_id,
        employee_id=employee_id,
        name=row.name,
        id_card_hash=row.id_card_hash,
        id_card_cipher=row.id_card_cipher,
        base_amount=row.base_amount,
        personal_amount=row.personal_total,
        company_amount=row.company_total,
        match_status=status,
        dept_text=row.dept_text,
    )


def _next_status(period: SalaryPeriod) -> Optional[str]:
    """导入后该不该推进状态。返回 None 表示只写数据不动状态。

    - draft：**不推进也不拒绝**。财务给社保表的时间常常早于钉钉考勤定版，
      为了「必须先同步考勤」把人卡在门外是纯粹的流程洁癖。数据先落库，
      状态等考勤同步完再往下走。
    - attendance_synced / calculated：推进到 imported。calculated 退回 imported 是
      对的——重新导入让已算的数失效，状态必须回退，否则步骤条在骗人。
    - imported：自环不消耗版本号（重复导入是常态操作，每次 +1 会让所有打开着
      批次页的客户端拿 409，乐观锁的告警价值就被噪音淹掉）。
    """
    target = period_service.STATUS_IMPORTED
    if period.status == target:
        return None
    if period_service.can_transition(period.status, target):
        return target
    return None


def persist(
    db: Session,
    period: SalaryPeriod,
    kind: str,
    file_bytes: bytes,
    *,
    filename: Optional[str] = None,
    operator_id: Optional[int] = None,
) -> dict[str, Any]:
    """解析 + 落库 + 匹配档案，返回给前端的导入结果摘要。

    **替换语义**：同一批次同一类型再导一次，旧行全删后重写。HR 拿到修正版文件就该
    直接重传，让他先去找「删除上次导入」的按钮是多余的一步。删除与写入在同一个事务里，
    中途失败不会留下「旧的没了新的也没进」的空批次。
    """
    if kind not in KINDS:
        raise SalaryImportError(f"未知的导入类型 {kind!r}")
    period_service.assert_writable(period)
    blocked = _BLOCKED_STATUSES.get(period.status)
    if blocked:
        raise SalaryImportError(blocked)

    # 版本号在**开工前**取，不在收口前取。乐观锁要保护的正是「解析 + 落库」这几十秒的
    # 窗口；如果拖到最后一条 SQL 之前才读，中途 ORM 因为别人 commit 而刷新，读到的就是
    # 对方写完的新版本，guarded_write 拿它去比对必然相等——守卫在自己骗自己。
    from_status = period.status
    from_version = period.status_version

    parser = import_service.parse_insurance if kind == KIND_INSURANCE else import_service.parse_fund
    result: ParseResult = parser(file_bytes)
    if not result.rows:
        raise SalaryImportError(
            f"文件解析成功但没有识别出任何人员行（共 {len(result.sheets)} 个 sheet）。"
            "请确认上传的是明细表而不是汇总表。"
        )

    hash_counts = Counter(r.id_card_hash for r in result.rows if r.id_card_hash)
    profiles = _load_profiles(db, set(hash_counts))

    model = _MODELS[kind]
    # 先删后插，都不 commit——收口在末尾的 guarded_write 上（见模块 docstring 红线 1）
    replaced = db.query(model).filter(model.period_id == period.id).delete(
        synchronize_session=False
    )

    counts: Counter = Counter()
    matched_sum = Decimal("0.00")
    all_sum = Decimal("0.00")
    row_warnings: list[str] = []

    for row in result.rows:
        status, employee_id = classify(row, profiles, hash_counts)
        record = (
            _build_insurance(period.id, row, status, employee_id)
            if kind == KIND_INSURANCE
            else _build_fund(period.id, row, status, employee_id)
        )
        try:
            # 单行 savepoint：一行数据脏（比如金额列是全角字符）不该让另外 65 人
            # 全部导不进来（红线 6）
            with db.begin_nested():
                db.add(record)
        except Exception as exc:  # noqa: BLE001
            logger.warning("薪资导入单行落库失败 period=%s %s 第%s行: %s",
                           period.id, row.sheet, row.row_no, exc)
            print(f"[salary.import] row failed {row.sheet}#{row.row_no}: {exc}", flush=True)
            row_warnings.append(f"{row.sheet} 第{row.row_no}行（{row.name}）落库失败，已跳过")
            continue

        counts[status] += 1
        if row.personal_total is not None:
            all_sum += row.personal_total
            if status in DEDUCTIBLE_STATUSES:
                matched_sum += row.personal_total

    new_status = _next_status(period)
    values: dict[str, Any] = {}
    if new_status:
        values = {"status": new_status, "status_version": from_version + 1}
    else:
        # 状态不变时也必须发一条 UPDATE——它是整批数据的提交点兼锁定判据（红线 1）。
        # 空 values 会让 SQLAlchemy 生成非法 SQL，所以写一个幂等赋值占位。
        values = {"status": from_status}

    # 这一条 UPDATE 同时是「批次没被锁 / 没被人改过」的判据和整批数据的提交点。
    # 撞上了就 rollback，上面那些 insert 一并作废——不会留下半批数据。
    period_service.guarded_write(
        db, period, values,
        expected_version=from_version,
        conflict_message="批次已被锁定或被他人修改，本次导入未生效，请刷新后重试",
    )

    summary = {
        "kind": kind,
        "kind_label": KIND_LABELS[kind],
        "filename": filename,
        "row_count": sum(counts.values()),
        "replaced": replaced,
        "match_counts": {k: counts.get(k, 0) for k in
                         (MATCH_MATCHED, MATCH_NOT_PAYROLL, MATCH_UNMATCHED, MATCH_DUPLICATE)},
        # 两个合计分开给：matched 的是真正会进工资表的钱，全量的是跟源表合计行对账用的。
        # 只报一个数，「文件对得上但工资表少扣了 8 个人」这类问题就看不出来。
        "personal_total_matched": str(matched_sum),
        "personal_total_all": str(all_sum),
        "sheets": [
            {
                "sheet": s.sheet,
                "entity": s.entity,
                "person_count": s.person_count,
                "personal_sum": str(s.personal_sum),
                "personal_total_in_file": (
                    str(s.personal_total_in_file) if s.personal_total_in_file is not None else None
                ),
                "rates_observed": s.rates_observed,
                "warnings": s.warnings,
            }
            for s in result.sheets
        ],
        "warnings": result.warnings + row_warnings,
        "status": period.status,
        "status_version": period.status_version,
    }

    period_service.log_event(
        db, period, "import",
        from_status=from_status if new_status else None,
        to_status=new_status,
        payload={
            "kind": kind,
            "filename": filename,
            "row_count": summary["row_count"],
            "replaced": replaced,
            "match_counts": summary["match_counts"],
            "personal_total_matched": summary["personal_total_matched"],
            "warning_count": len(summary["warnings"]),
        },
        operator_id=operator_id,
    )
    return summary


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------

def serialize_row(row: Any, kind: str) -> dict[str, Any]:
    """导入行出站形态。**身份证只出脱敏串**——明文与密文都不进响应。

    这里要解密再打码，而不是直接不给：HR 面对「未匹配」的行，光看姓名没法判断是
    同名的新员工还是档案里身份证录错了，尾号四位是他唯一能核对的东西。
    解密失败（密钥换过）不抛错，给空串——一行看不清不该让整个异常面板打不开。
    """
    plain = pii.decrypt_pii(row.id_card_cipher)
    personal = getattr(row, "personal_total", None)
    if personal is None:
        personal = getattr(row, "personal_amount", None)
    company = getattr(row, "company_total", None)
    if company is None:
        company = getattr(row, "company_amount", None)
    detail = getattr(row, "detail_json", None) or {}
    return {
        "id": row.id,
        "kind": kind,
        "employee_id": row.employee_id,
        "name": row.name,
        "id_card_masked": pii.mask_pii(plain) if plain else "",
        "entity": getattr(row, "entity", None),
        "dept_text": row.dept_text,
        "base_amount": row.base_amount,
        "personal_amount": personal,
        "company_amount": company,
        "match_status": row.match_status,
        "match_label": MATCH_LABELS.get(row.match_status, row.match_status),
        "sheet": detail.get("sheet"),
        "row_no": detail.get("row_no"),
        "warnings": detail.get("warnings") or [],
    }


def list_rows(
    db: Session,
    period_id: int,
    kind: str,
    *,
    match_status: str = "",
    keyword: str = "",
    limit: int = 500,
) -> dict[str, Any]:
    """按批次+类型列导入行，附带各匹配状态的计数（异常面板的角标靠它）。

    计数走独立的 GROUP BY 而不是数返回的列表：列表带 limit，用它统计会在超过一页时
    把「未匹配 12 人」显示成「未匹配 3 人」，而这个数字正是 HR 判断能不能往下走的依据。
    """
    if kind not in KINDS:
        raise SalaryImportError(f"未知的导入类型 {kind!r}")
    model = _MODELS[kind]

    from sqlalchemy import func

    tally = dict(
        db.query(model.match_status, func.count(model.id))
        .filter(model.period_id == period_id)
        .group_by(model.match_status)
        .all()
    )

    q = db.query(model).filter(model.period_id == period_id)
    if match_status:
        q = q.filter(model.match_status == match_status)
    if keyword:
        q = q.filter(model.name.like(f"%{keyword}%"))
    rows = q.order_by(model.match_status, model.id).limit(limit).all()

    return {
        "kind": kind,
        "kind_label": KIND_LABELS[kind],
        "items": [serialize_row(r, kind) for r in rows],
        "match_counts": {
            k: int(tally.get(k, 0))
            for k in (MATCH_MATCHED, MATCH_NOT_PAYROLL, MATCH_UNMATCHED, MATCH_DUPLICATE)
        },
        "total": sum(int(v) for v in tally.values()),
        "truncated": len(rows) >= limit,
    }
