"""私海客户工作台（PCW-02）：客户档案普通修订与 AI 建议审核。

契约见 docs/requirements/private-customer-workbench-prototype/：
- api-contracts.md 4.2/6 节：字段白名单、版本前置（expected_profile_version_id +
  expected_profile_input_seq）、409 可见差异、Annotation v2 人工覆盖层；
- schema-migrations.md 第 1 节：普通修订复用 CustomerAnnotation content_schema_version=v2，
  纠错 correction+target_fact_id、补充 note；不伪造 confirmed 偏好事实；
- development-spec.md PCW-02：私人备注按作者隔离，不进入共享画像与 AI 共享上下文。

普通字段修订与治理（合并/身份重绑/归属变更/DNC/重大风险）严格分离：
治理字段一律 400 GOVERNED_FIELD_REQUIRED，继续走 CustomerChangeProposal 链。
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.time import beijing_now, to_beijing_naive
from app.customer import pcw_errors
from app.customer.models import (
    CustomerAccount,
    CustomerAnnotation,
    CustomerEvent,
    CustomerFact,
    CustomerProfileVersion,
)
from app.customer.pcw_idempotency import run_with_receipt
from app.customer.pcw_models import CustomerFactReview
from app.customer.pcw_suggestion_service import (
    SUGGESTION_OPEN_STATUSES,
    mark_suggestions_stale,
)
from app.customer.workflow_service import _account_for_update, _active_user

logger = logging.getLogger(__name__)

ANNOTATION_V2_SCHEMA = "annotation_v2"
REVISION_KIND = "profile_field_revision"

# 字段白名单：field_key → (value_type, profile 节, 子列表, 中文标签)
FIELD_WHITELIST: dict[str, tuple[str, str, str | None, str]] = {
    "preference.expressed.color": ("string", "preferences", "expressed", "颜色偏好"),
    "preference.expressed.product_family": ("string", "preferences", "expressed", "产品族偏好"),
    "preference.expressed.model": ("string", "preferences", "expressed", "型号偏好"),
    "preference.expressed.length": ("string", "preferences", "expressed", "长度偏好"),
    "preference.expressed.delivery_window": ("string", "preferences", "expressed", "交期偏好"),
    "preference.expressed.quantity": ("number", "preferences", "expressed", "采购量级"),
    "preference.expressed.price_range": ("object", "preferences", "expressed", "价格区间"),
    "profile.business_type": ("string", "business", None, "业务类型"),
}
# 治理字段前缀：普通业务修订无权写入，必须走既有治理提案链
GOVERNED_FIELD_PREFIXES = (
    "identity.",
    "ownership.",
    "policy.",
    "risk.",
    "commercial.",
    "contact.",
)
PRICE_RANGE_KEYS = frozenset({"min", "max", "currency"})


def _access_customer(
    db: Session,
    *,
    customer_id: int,
    actor_user_id: int,
    write: bool = False,
) -> int:
    """客户域鉴权 + 逻辑客户解析；失权/不存在一律 404（不泄漏存在性）。"""
    from app.auth.service import get_live_user_authorization
    from app.customer.access_service import CustomerAccessDenied, require_customer_access

    if type(actor_user_id) is not int or actor_user_id <= 0:
        raise pcw_errors.customer_not_found()
    roles, permissions = get_live_user_authorization(db, actor_user_id)
    user = {"sub": actor_user_id, "roles": roles, "permissions": permissions}
    try:
        access = require_customer_access(
            db,
            customer_id=customer_id,
            user=user,
            action_permissions=(
                ("customer_profile:write", "customer:admin")
                if write
                else ("customer_pcw:read", "customer_radar:read", "customer:read", "customer:read_all")
            ),
            manage_permissions=("customer:admin",),
        )
    except CustomerAccessDenied:
        raise pcw_errors.customer_not_found() from None
    return int(access.customer_id)


def _validate_field_key(field_key: str) -> tuple[str, str, str | None, str]:
    for prefix in GOVERNED_FIELD_PREFIXES:
        if field_key.startswith(prefix):
            raise pcw_errors.bad_request(
                "该字段属于治理范围，必须走变更提案流程",
                error_code="GOVERNED_FIELD_REQUIRED",
            )
    if field_key not in FIELD_WHITELIST:
        raise pcw_errors.bad_request(
            "该字段不在普通修订白名单内",
            error_code="FIELD_NOT_EDITABLE",
        )
    return FIELD_WHITELIST[field_key]


def _validate_value(value_type: str, value: Any) -> Any:
    if value_type == "string":
        if not isinstance(value, str) or not value.strip() or len(value) > 500:
            raise pcw_errors.bad_request(
                "字符串值必填且不超过500字符", error_code="REVISION_VALUE_INVALID"
            )
        return value.strip()
    if value_type == "number":
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise pcw_errors.bad_request(
                "数值不合法", error_code="REVISION_VALUE_INVALID"
            ) from exc
        if not number.is_finite() or number < 0:
            raise pcw_errors.bad_request(
                "数值必须是非负有限值", error_code="REVISION_VALUE_INVALID"
            )
        return format(number.normalize(), "f")
    if value_type == "object":
        if not isinstance(value, Mapping):
            raise pcw_errors.bad_request(
                "对象值结构不合法", error_code="REVISION_VALUE_INVALID"
            )
        unknown = set(value) - PRICE_RANGE_KEYS
        if unknown or not any(value.get(key) is not None for key in PRICE_RANGE_KEYS):
            raise pcw_errors.bad_request(
                "对象值只允许 min/max/currency 且至少一项有值",
                error_code="REVISION_VALUE_INVALID",
            )
        normalized: dict[str, Any] = {}
        for key in ("min", "max"):
            if value.get(key) is not None:
                try:
                    normalized[key] = format(Decimal(str(value[key])).normalize(), "f")
                except (InvalidOperation, ValueError, TypeError) as exc:
                    raise pcw_errors.bad_request(
                        "价格区间数值不合法", error_code="REVISION_VALUE_INVALID"
                    ) from exc
        if value.get("currency") is not None:
            currency = str(value["currency"]).strip()
            if not currency or len(currency) > 8:
                raise pcw_errors.bad_request(
                    "币种代码不合法", error_code="REVISION_VALUE_INVALID"
                )
            normalized["currency"] = currency.upper()
        return normalized
    raise pcw_errors.bad_request(
        "值类型未注册", error_code="REVISION_VALUE_INVALID"
    )


def _require_profile_versions(
    db: Session,
    *,
    customer_id: int,
    expected_profile_version_id: int,
    expected_profile_input_seq: int,
) -> CustomerAccount:
    """强版本前置：档案版本 ID 与输入序号必须同时匹配当前值。"""
    account = _account_for_update(db, customer_id)
    current_seq = int(account.profile_input_seq)
    current_version_id = account.current_profile_version_id
    if (
        int(expected_profile_input_seq) != current_seq
        or int(expected_profile_version_id) != int(current_version_id or 0)
    ):
        current_value = _current_field_entry(db, customer_id, None)
        raise pcw_errors.conflict(
            "档案版本已变化，请刷新后重新确认",
            error_code="PROFILE_VERSION_CONFLICT",
            details={
                "current_version_id": current_version_id,
                "current_input_seq": current_seq,
                "visible_diff": [current_value] if current_value else [],
            },
        )
    return account


def _current_field_entry(
    db: Session, customer_id: int, field_key: str | None
) -> dict | None:
    """构造 409 可见差异：当前人工修订/事实投影值（脱敏，不返回原文）。"""
    if not field_key:
        return None
    latest_revision = (
        db.query(CustomerAnnotation)
        .filter(
            CustomerAnnotation.customer_id == customer_id,
            CustomerAnnotation.status == "active",
            CustomerAnnotation.content_schema_version == "v2",
            CustomerAnnotation.annotation_type.in_(("correction", "note")),
        )
        .order_by(CustomerAnnotation.id.desc())
        .all()
    )
    for row in latest_revision:
        content = dict(row.content_json or {})
        if content.get("revision_kind") == REVISION_KIND and content.get("field_key") == field_key:
            return {
                "field_key": field_key,
                "current_value": content.get("value"),
                "source": "manual_revision",
                "annotation_id": row.id,
            }
    fact = (
        db.query(CustomerFact)
        .filter(
            CustomerFact.customer_id == customer_id,
            CustomerFact.fact_key == field_key,
            CustomerFact.effective_to.is_(None),
            CustomerFact.verification_status != "superseded",
        )
        .order_by(CustomerFact.observed_at.desc(), CustomerFact.id.desc())
        .first()
    )
    if fact is None:
        return None
    value_json = dict(fact.value_json or {})
    return {
        "field_key": field_key,
        "current_value": value_json.get("value"),
        "source": f"fact:{fact.fact_layer}:{fact.verification_status}",
        "fact_id": fact.id,
    }


def _revision_entry(*, annotation_id: int, field_key: str, value_type: str,
                    value: Any, reason: str, created_at) -> dict:
    """Annotation v2 人工修订投影条目；不伪造 confirmed 事实。"""
    return {
        "fact_id": None,
        "fact_key": field_key,
        "value": value,
        "value_type": value_type,
        "fact_layer": "manual_revision",
        "verification_status": "human_confirmed",
        "confidence": 1.0,
        "data_classification": "internal_business",
        "visibility_scope": "customer_team",
        "observed_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
        "source": "manual_revision",
        "annotation_id": annotation_id,
        "revision_kind": REVISION_KIND,
        "reason": reason,
        "fact_fingerprint": None,
    }


def _apply_overlay_to_profile(
    profile: dict,
    *,
    annotation_id: int,
    field_key: str,
    value_type: str,
    value: Any,
    reason: str,
    created_at,
    section: str,
    subsection: str | None,
) -> dict:
    """在当前 profile_json 上应用单条人工覆盖（与编译器 v2 投影同一形状）。"""
    entry = _revision_entry(
        annotation_id=annotation_id,
        field_key=field_key,
        value_type=value_type,
        value=value,
        reason=reason,
        created_at=created_at,
    )
    if subsection is None:
        business = dict(profile.get(section) or {})
        business["business_type"] = entry
        profile[section] = business
        return profile
    section_value = dict(profile.get(section) or {})
    entries = list(section_value.get(subsection) or [])
    # 同字段旧的人工修订退出当前值位置（保留历史条目供审计，标注被替代）
    for index, item in enumerate(entries):
        if item.get("fact_key") == field_key and item.get("revision_kind") == REVISION_KIND:
            replaced = dict(item)
            replaced["superseded_by_annotation_id"] = annotation_id
            entries[index] = replaced
        elif item.get("fact_key") == field_key:
            suppressed = dict(item)
            suppressed["superseded_by_annotation_id"] = annotation_id
            entries[index] = suppressed
    entries.insert(0, entry)
    section_value[subsection] = entries
    profile[section] = section_value
    return profile


def _publish_overlay_version(
    db: Session,
    *,
    account: CustomerAccount,
    profile: dict,
    trigger_event_id: int | None,
) -> CustomerProfileVersion:
    """单事务内发布带人工覆盖层的新档案版本（原事实与来源不改写）。

    与 profile_service.compile_customer_profile 的全量编译互补：
    全量编译同样投影 v2 覆盖（_apply_annotation_v2_overlay），两条路径收敛。
    """
    from app.customer.profile_service import (
        CANONICALIZATION_VERSION,
        COMPILER_VERSION,
        PROFILE_SCHEMA_VERSION,
        _PROFILE_SECTIONS,
        _change_summary,
        _section_hashes,
    )

    previous = None
    if account.current_profile_version_id is not None:
        previous = db.get(CustomerProfileVersion, account.current_profile_version_id)
    if previous is None:
        raise pcw_errors.conflict(
            "客户档案尚未编译，不能仅以修订创建首个档案版本",
            error_code="PROFILE_NOT_READY",
        )
    now = beijing_now()
    for section in _PROFILE_SECTIONS:
        profile.setdefault(section, {})
    hashes = _section_hashes(profile, {})
    import hashlib
    import json as _json

    payload = _json.dumps(
        {
            "profile_schema_version": PROFILE_SCHEMA_VERSION,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "compiler_version": COMPILER_VERSION + "+annotation_v2_overlay",
            "input_seq": int(account.profile_input_seq),
            "profile": profile,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    profile_fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    latest_version_no = (
        db.query(func.max(CustomerProfileVersion.version_no))
        .filter(CustomerProfileVersion.customer_id == account.id)
        .scalar()
        or 0
    )
    version = CustomerProfileVersion(
        customer_id=account.id,
        version_no=int(latest_version_no) + 1,
        profile_schema_version=PROFILE_SCHEMA_VERSION,
        canonicalization_version=CANONICALIZATION_VERSION,
        input_seq=int(account.profile_input_seq),
        profile_json=profile,
        section_hashes=hashes,
        section_data_as_of=dict(previous.section_data_as_of or {}),
        evidence_fact_ids=list(previous.evidence_fact_ids or []),
        change_summary=_change_summary(previous, hashes, profile),
        compiler_version=COMPILER_VERSION + "+annotation_v2_overlay",
        profile_fingerprint=profile_fingerprint,
        data_as_of=previous.data_as_of or now,
        trigger_event_id=trigger_event_id,
        compiled_at=now,
        created_at=now,
    )
    db.add(version)
    db.flush()
    account.current_profile_version_id = version.id
    account.profile_compiled_at = now
    account.updated_at = now
    db.flush()
    return version


def create_profile_revision(
    db: Session,
    *,
    customer_id: int,
    actor_user_id: int,
    actor_user: dict | None = None,
    expected_profile_version_id: int,
    expected_profile_input_seq: int,
    field_key: str,
    value_type: str,
    value: Any,
    reason: str,
    target_fact_id: int | None = None,
    evidence_refs: list[dict] | None = None,
    supersedes_annotation_id: int | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """普通字段修订：Annotation v2 + 新档案版本 + 修订事件，单事务原子。"""
    if actor_user is not None:
        from app.customer.access_service import CustomerAccessDenied, require_customer_access

        try:
            require_customer_access(
                db,
                customer_id=customer_id,
                user=actor_user,
                action_permissions=("customer_profile:write", "customer:admin"),
                manage_permissions=("customer:admin",),
            )
        except CustomerAccessDenied as exc:
            raise pcw_errors.customer_not_found() from exc
    _active_user(db, actor_user_id)
    expected_type, section, subsection, _label = _validate_field_key(field_key)
    if value_type != expected_type:
        raise pcw_errors.bad_request(
            "value_type 与字段注册类型不一致", error_code="REVISION_VALUE_TYPE_MISMATCH"
        )
    normalized_value = _validate_value(value_type, value)
    normalized_reason = (reason or "").strip()
    if not normalized_reason or len(normalized_reason) > 1000:
        raise pcw_errors.bad_request(
            "修订依据必填且不超过1000字", error_code="REVISION_REASON_INVALID"
        )

    request_payload = {
        "customer_id": customer_id,
        "expected_profile_version_id": expected_profile_version_id,
        "expected_profile_input_seq": expected_profile_input_seq,
        "field_key": field_key,
        "value_type": value_type,
        "value": normalized_value,
        "reason": normalized_reason,
        "target_fact_id": target_fact_id,
        "supersedes_annotation_id": supersedes_annotation_id,
    }

    def _execute() -> dict:
        account = _require_profile_versions(
            db,
            customer_id=customer_id,
            expected_profile_version_id=expected_profile_version_id,
            expected_profile_input_seq=expected_profile_input_seq,
        )
        if target_fact_id is not None:
            target_fact = db.query(CustomerFact).filter(
                CustomerFact.id == target_fact_id,
                CustomerFact.customer_id == customer_id,
            ).one_or_none()
            if target_fact is None:
                raise pcw_errors.not_found(
                    "被纠错事实不存在", error_code="TARGET_FACT_NOT_FOUND"
                )
        supersedes_annotation = None
        if supersedes_annotation_id is not None:
            supersedes_annotation = db.query(CustomerAnnotation).filter(
                CustomerAnnotation.id == supersedes_annotation_id,
                CustomerAnnotation.customer_id == customer_id,
            ).one_or_none()
            if supersedes_annotation is None:
                raise pcw_errors.not_found(
                    "被替代修订不存在", error_code="SUPERSEDES_ANNOTATION_NOT_FOUND"
                )
            if supersedes_annotation.status != "active":
                raise pcw_errors.conflict(
                    "被替代修订已失效", error_code="ANNOTATION_SUPERSEDED"
                )

        now = beijing_now()
        annotation_type = "correction" if target_fact_id is not None else "note"
        content = {
            "schema_version": ANNOTATION_V2_SCHEMA,
            "revision_kind": REVISION_KIND,
            "field_key": field_key,
            "value_type": value_type,
            "value": normalized_value,
            "reason": normalized_reason,
            "evidence_refs": list(evidence_refs or []),
            "supersedes_annotation_id": supersedes_annotation_id,
        }
        if target_fact_id is not None:
            content["target_fact_id"] = target_fact_id
        annotation = CustomerAnnotation(
            customer_id=customer_id,
            annotation_type=annotation_type,
            target_fact_id=target_fact_id,
            content_schema_version="v2",
            content_json=content,
            visibility="customer_team",
            data_classification="internal_business",
            status="active",
            authored_by=actor_user_id,
            created_at=now,
            updated_at=now,
        )
        db.add(annotation)
        db.flush()
        if supersedes_annotation is not None:
            supersedes_annotation.status = "revoked"
            supersedes_annotation.revoked_by = actor_user_id
            supersedes_annotation.revoked_at = now
            supersedes_annotation.updated_at = now

        # 输入序号推进后发布覆盖层版本（发布时点 CAS 语义：仅一次推进）
        account.profile_input_seq = int(account.profile_input_seq) + 1
        account.updated_at = now
        db.flush()
        previous_version_id = account.current_profile_version_id
        profile = dict(
            db.get(CustomerProfileVersion, account.current_profile_version_id).profile_json
        )
        profile = _apply_overlay_to_profile(
            profile,
            annotation_id=annotation.id,
            field_key=field_key,
            value_type=value_type,
            value=normalized_value,
            reason=normalized_reason,
            created_at=now,
            section=section,
            subsection=subsection,
        )
        version = _publish_overlay_version(
            db,
            account=account,
            profile=profile,
            trigger_event_id=None,
        )
        # 同字段的其他待处理建议变为 stale（人工确认优先，后续 AI 只能生成新冲突建议）
        _stale_open_suggestions_for_field(
            db, customer_id=customer_id, field_key=field_key,
            reason=f"human_revision:{annotation.id}",
        )
        from app.customer.fact_service import append_customer_event

        event = append_customer_event(
            db,
            customer_id=customer_id,
            event_type="profile.field_revised",
            event_source="manual",
            event_title="档案字段人工修订",
            event_summary=normalized_reason,
            event_payload={
                "annotation_id": annotation.id,
                "field_key": field_key,
                "value_type": value_type,
                "reason": normalized_reason,
                "profile_before": int(previous_version_id or 0),
                "profile_after": version.id,
            },
            payload_schema_version="customer_event_v1",
            occurred_at=now,
            source_ref_type="annotation",
            source_ref_id=str(annotation.id),
            actor_user_id=actor_user_id,
        )
        return {
            "revision_annotation_id": annotation.id,
            "profile_version_id": version.id,
            "profile_input_seq": int(account.profile_input_seq),
            "event_id": event.id,
        }

    if idempotency_key:
        result, _replayed = run_with_receipt(
            db,
            actor_user_id=actor_user_id,
            operation_scope=f"profile_revision:{customer_id}",
            idempotency_key=idempotency_key,
            request_payload=request_payload,
            execute=_execute,
        )
        return result
    return _execute()


def _stale_open_suggestions_for_field(
    db: Session, *, customer_id: int, field_key: str, reason: str
) -> int:
    rows = (
        db.query(CustomerFactReview)
        .join(CustomerFact, CustomerFact.id == CustomerFactReview.candidate_fact_id)
        .filter(
            CustomerFactReview.customer_id == customer_id,
            CustomerFactReview.status.in_(sorted(SUGGESTION_OPEN_STATUSES)),
            CustomerFact.fact_key == field_key,
        )
        .all()
    )
    now = beijing_now()
    for row in rows:
        row.status = "stale"
        row.decision_reason = ((row.decision_reason or "") + f"[stale] {reason}")[:1000]
        row.suggestion_version = int(row.suggestion_version) + 1
        row.updated_at = now
    if rows:
        db.flush()
    return len(rows)


def decide_suggestion(
    db: Session,
    *,
    review_id: int,
    actor_user_id: int,
    actor_user: dict | None = None,
    operation: str,
    expected_suggestion_version: int,
    expected_profile_version_id: int | None = None,
    expected_profile_input_seq: int | None = None,
    value: Any = None,
    reason: str | None = None,
    defer_until=None,
    idempotency_key: str | None = None,
) -> dict:
    """AI 建议决定：accept/edit_accept/reject/defer；同一建议仅一次有效决定。"""
    if actor_user is not None:
        from app.customer.access_service import CustomerAccessDenied, require_customer_access

        try:
            require_customer_access(
                db,
                customer_id=_review_customer_id(db, review_id),
                user=actor_user,
                action_permissions=("customer_profile:write", "customer:admin"),
                manage_permissions=("customer:admin",),
            )
        except CustomerAccessDenied as exc:
            raise pcw_errors.customer_not_found() from exc
    _active_user(db, actor_user_id)
    if operation not in {"accept", "edit_accept", "reject", "defer"}:
        raise pcw_errors.bad_request(
            "建议决定操作不合法", error_code="SUGGESTION_OPERATION_INVALID"
        )
    normalized_reason = (reason or "").strip() or None
    if operation == "reject" and not normalized_reason:
        raise pcw_errors.bad_request(
            "驳回必须填写原因", error_code="DECISION_REASON_REQUIRED"
        )
    if operation == "defer":
        if defer_until is None:
            raise pcw_errors.bad_request(
                "稍后处理必须填写提醒日期", error_code="DEFER_UNTIL_REQUIRED"
            )
        defer_at = to_beijing_naive(defer_until)
        if defer_at <= beijing_now():
            raise pcw_errors.bad_request(
                "提醒日期必须晚于当前时间", error_code="DEFER_UNTIL_MUST_BE_FUTURE"
            )
    else:
        defer_at = None

    request_payload = {
        "review_id": review_id,
        "operation": operation,
        "expected_suggestion_version": expected_suggestion_version,
        "expected_profile_version_id": expected_profile_version_id,
        "expected_profile_input_seq": expected_profile_input_seq,
        "value": value,
        "reason": normalized_reason,
        "defer_until": defer_at.isoformat() if defer_at else None,
    }

    def _execute() -> dict:
        review = (
            db.query(CustomerFactReview)
            .filter(CustomerFactReview.id == review_id)
            .populate_existing()
            .with_for_update()
            .one_or_none()
        )
        if review is None:
            raise pcw_errors.not_found(
                "建议不存在", error_code="SUGGESTION_NOT_FOUND"
            )
        if int(review.suggestion_version) != int(expected_suggestion_version):
            raise pcw_errors.conflict(
                "建议版本已变化",
                error_code="SUGGESTION_VERSION_CONFLICT",
                details={"current_suggestion_version": int(review.suggestion_version)},
            )
        if review.status in {"accepted", "rejected"}:
            raise pcw_errors.conflict(
                "建议已做出终态决定", error_code="SUGGESTION_ALREADY_DECIDED"
            )
        if review.status == "stale":
            raise pcw_errors.conflict(
                "建议依赖已失效，请等待新的分析结果", error_code="SUGGESTION_STALE"
            )
        fact = db.query(CustomerFact).filter(
            CustomerFact.id == review.candidate_fact_id,
        ).one_or_none()
        if fact is None:
            raise pcw_errors.conflict(
                "候选事实已不存在", error_code="SUGGESTION_STALE"
            )
        if fact.verification_status in {"superseded", "rejected"} or fact.effective_to is not None:
            raise pcw_errors.conflict(
                "候选事实已被取代，不能采纳", error_code="SUGGESTION_STALE"
            )
        now = beijing_now()
        result: dict[str, Any] = {"id": review.id, "operation": operation}

        if operation in {"accept", "edit_accept"}:
            if expected_profile_version_id is None or expected_profile_input_seq is None:
                raise pcw_errors.bad_request(
                    "采纳建议必须携带档案版本前置",
                    error_code="PROFILE_VERSION_REQUIRED",
                )
            if operation == "edit_accept":
                if value is None:
                    raise pcw_errors.bad_request(
                        "编辑采纳必须提供修订值", error_code="REVISION_VALUE_INVALID"
                    )
                _, _section, _subsection, _label = _validate_field_key(fact.fact_key)
                expected_type = FIELD_WHITELIST[fact.fact_key][0]
                normalized_value = _validate_value(expected_type, value)
            else:
                expected_type = FIELD_WHITELIST.get(fact.fact_key, (None,))[0]
                if expected_type is None:
                    raise pcw_errors.conflict(
                        "候选事实字段不在普通修订白名单内", error_code="SUGGESTION_STALE"
                    )
                value_json = dict(fact.value_json or {})
                normalized_value = _validate_value(expected_type, value_json.get("value"))
            revision = create_profile_revision(
                db,
                customer_id=int(review.customer_id),
                actor_user_id=actor_user_id,
                actor_user=None,
                expected_profile_version_id=int(expected_profile_version_id),
                expected_profile_input_seq=int(expected_profile_input_seq),
                field_key=fact.fact_key,
                value_type=expected_type,
                value=normalized_value,
                reason=normalized_reason or ("采纳AI建议" if operation == "accept" else "编辑采纳AI建议"),
                target_fact_id=fact.id,
                evidence_refs=[{"type": "fact", "id": fact.id}],
                idempotency_key=None,
            )
            review.status = "accepted"
            review.revision_annotation_id = revision["revision_annotation_id"]
            review.profile_revision_event_id = revision.get("event_id")
            result.update({
                "status": "accepted",
                "revision_annotation_id": revision["revision_annotation_id"],
                "profile_version_id": revision["profile_version_id"],
                "profile_input_seq": revision["profile_input_seq"],
            })
        elif operation == "reject":
            review.status = "rejected"
            review.decision_reason = normalized_reason
            result.update({"status": "rejected"})
        else:
            review.status = "deferred"
            review.defer_until = defer_at
            review.decision_reason = normalized_reason
            result.update({"status": "deferred", "defer_until": defer_at.isoformat()})

        review.reviewer_user_id = actor_user_id
        review.decided_at = now
        review.suggestion_version = int(review.suggestion_version) + 1
        review.updated_at = now
        db.flush()
        result["suggestion_version"] = int(review.suggestion_version)
        return result

    if idempotency_key:
        result, _replayed = run_with_receipt(
            db,
            actor_user_id=actor_user_id,
            operation_scope=f"suggestion_decision:{review_id}",
            idempotency_key=idempotency_key,
            request_payload=request_payload,
            execute=_execute,
        )
        return result
    return _execute()


def _review_customer_id(db: Session, review_id: int) -> int:
    row = db.query(CustomerFactReview.customer_id).filter(
        CustomerFactReview.id == review_id,
    ).one_or_none()
    if row is None:
        raise pcw_errors.not_found("建议不存在", error_code="SUGGESTION_NOT_FOUND")
    return int(row.customer_id)


def list_profile_revisions(
    db: Session,
    *,
    customer_id: int,
    actor_user_id: int,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """人工修订历史（Annotation v2），含新旧值与依据，按时间倒序分页。"""
    customer_id = _access_customer(db, customer_id=customer_id, actor_user_id=actor_user_id)
    query = db.query(CustomerAnnotation).filter(
        CustomerAnnotation.customer_id == customer_id,
        CustomerAnnotation.content_schema_version == "v2",
        CustomerAnnotation.annotation_type.in_(("correction", "note")),
    )
    total = query.count()
    rows = (
        query.order_by(CustomerAnnotation.id.desc())
        .offset(max(page - 1, 0) * page_size)
        .limit(page_size)
        .all()
    )
    items = []
    for row in rows:
        content = dict(row.content_json or {})
        if content.get("revision_kind") != REVISION_KIND:
            continue
        previous_entry = None
        if content.get("supersedes_annotation_id"):
            previous_entry = content["supersedes_annotation_id"]
        items.append({
            "annotation_id": row.id,
            "field_key": content.get("field_key"),
            "value_type": content.get("value_type"),
            "value": content.get("value"),
            "reason": content.get("reason"),
            "target_fact_id": row.target_fact_id,
            "supersedes_annotation_id": previous_entry,
            "status": row.status,
            "authored_by": row.authored_by,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def list_profile_suggestions(
    db: Session,
    *,
    customer_id: int,
    actor_user_id: int,
    actor_permissions: frozenset[str] | set[str] = frozenset(),
    status: str | None = None,
) -> dict:
    """AI 档案建议列表；越权事实剔除并计数，不返回源权限外内容。"""
    customer_id = _access_customer(db, customer_id=customer_id, actor_user_id=actor_user_id)
    query = db.query(CustomerFactReview, CustomerFact).join(
        CustomerFact, CustomerFact.id == CustomerFactReview.candidate_fact_id,
    ).filter(CustomerFactReview.customer_id == customer_id)
    if status:
        query = query.filter(CustomerFactReview.status == status)
    rows = query.order_by(CustomerFactReview.id.desc()).all()
    items = []
    masked_count = 0
    can_manage = "customer:admin" in set(actor_permissions) or "super_admin" in set(actor_permissions)
    for review, fact in rows:
        if fact.visibility_scope == "management" and not can_manage:
            masked_count += 1
            continue
        value_json = dict(fact.value_json or {})
        items.append({
            "id": review.id,
            "status": review.status,
            "suggestion_version": int(review.suggestion_version),
            "candidate_fact_id": fact.id,
            "field_key": fact.fact_key,
            "value": value_json.get("value"),
            "value_type": fact.value_type,
            "fact_layer": fact.fact_layer,
            "confidence": float(fact.confidence or 0),
            "observed_at": fact.observed_at.isoformat() if fact.observed_at else None,
            "decision_reason": review.decision_reason,
            "defer_until": review.defer_until.isoformat() if review.defer_until else None,
        })
    return {"items": items, "masked_count": masked_count}


def create_private_note(
    db: Session,
    *,
    customer_id: int,
    actor_user_id: int,
    text: str,
    idempotency_key: str | None = None,
) -> dict:
    """私人备注：仅作者可见，不进入共享画像编译与 AI 共享上下文。"""
    normalized = (text or "").strip()
    if not normalized or len(normalized) > 5000:
        raise pcw_errors.bad_request(
            "备注内容必填且不超过5000字", error_code="NOTE_TEXT_INVALID"
        )
    customer_id = _access_customer(db, customer_id=customer_id, actor_user_id=actor_user_id, write=True)

    def _execute() -> dict:
        _active_user(db, actor_user_id)
        now = beijing_now()
        note = CustomerAnnotation(
            customer_id=customer_id,
            annotation_type="note",
            content_schema_version="v1",
            content_json={"text": normalized},
            visibility="private",
            data_classification="internal_business",
            status="active",
            authored_by=actor_user_id,
            created_at=now,
            updated_at=now,
        )
        db.add(note)
        db.flush()
        return {"note_id": note.id, "created_at": now.isoformat()}

    if idempotency_key:
        result, _replayed = run_with_receipt(
            db,
            actor_user_id=actor_user_id,
            operation_scope=f"private_note:{customer_id}",
            idempotency_key=idempotency_key,
            request_payload={"text": normalized},
            execute=_execute,
        )
        return result
    return _execute()


def list_private_notes(
    db: Session,
    *,
    customer_id: int,
    actor_user_id: int,
) -> dict:
    customer_id = _access_customer(db, customer_id=customer_id, actor_user_id=actor_user_id)
    rows = (
        db.query(CustomerAnnotation)
        .filter(
            CustomerAnnotation.customer_id == customer_id,
            CustomerAnnotation.annotation_type == "note",
            CustomerAnnotation.visibility == "private",
            CustomerAnnotation.status == "active",
            CustomerAnnotation.authored_by == actor_user_id,
        )
        .order_by(CustomerAnnotation.id.desc())
        .all()
    )
    return {
        "items": [
            {
                "note_id": row.id,
                "text": dict(row.content_json or {}).get("text"),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }
