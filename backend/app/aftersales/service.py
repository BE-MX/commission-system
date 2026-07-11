"""售后单生命周期与条件审批状态机。"""

from datetime import date, datetime
import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.aftersales.models import (
    AfterSalesCase,
    AfterSalesAiRun,
    AfterSalesEvent,
    AfterSalesEvidence,
    AfterSalesReview,
)
from app.aftersales.notification_service import enqueue_notification
from app.aftersales.rules import classify_compensation, evaluate_evidence, next_status, validate_actions
from app.aftersales.schemas import CaseCreate
from app.auth.models import ArkRole, ArkUser, ArkUserExternalBinding, ArkUserRole
from app.core.config import get_settings
from app.models.employee import SupervisorRelationHistory


EDITABLE_STATUSES = {"draft", "ai_failed", "awaiting_sales_decision", "returned"}


class WorkflowOperationError(ValueError):
    pass


class ApprovalConfigurationError(WorkflowOperationError):
    pass


class VersionConflict(WorkflowOperationError):
    pass


def _is_replayed_event(db: Session, case_id: int, idempotency_key: str) -> bool:
    existing_case_id = (
        db.query(AfterSalesEvent.case_id)
        .filter(AfterSalesEvent.idempotency_key == idempotency_key)
        .scalar()
    )
    if existing_case_id is None:
        return False
    if existing_case_id != case_id:
        raise WorkflowOperationError("幂等键已用于其他售后单，请重新提交")
    return True


def _case_for_update(db: Session, case_id: int) -> AfterSalesCase:
    case = (
        db.query(AfterSalesCase)
        .filter(AfterSalesCase.id == case_id, AfterSalesCase.deleted_at.is_(None))
        .with_for_update()
        .first()
    )
    if case is None:
        raise WorkflowOperationError("售后单不存在")
    return case


def _require_creator(case: AfterSalesCase, user: ArkUser) -> None:
    if case.creator_user_id != user.id:
        raise WorkflowOperationError("只有售后单创建人可以执行此操作")


def _check_version(case: AfterSalesCase, expected_version: int) -> None:
    if case.version != expected_version:
        raise VersionConflict("售后单已被其他人更新，请刷新后重试")


def _event(
    db: Session,
    case: AfterSalesCase,
    event_type: str,
    actor: ArkUser,
    *,
    detail: dict | None = None,
    idempotency_key: str | None = None,
) -> AfterSalesEvent:
    event = AfterSalesEvent(
        case_id=case.id,
        event_type=event_type,
        actor_user_id=actor.id,
        actor_name_snapshot=actor.real_name,
        workflow_round=case.workflow_round,
        detail_json=detail,
        idempotency_key=idempotency_key,
    )
    db.add(event)
    return event


def _notification_payload(case: AfterSalesCase, title: str, content: str) -> dict:
    base_url = get_settings().AFTERSALES_DETAIL_BASE_URL.rstrip("/")
    return {
        "title": title,
        "content": content,
        "message_url": f"{base_url}/{case.id}",
    }


def _apply_payload(case: AfterSalesCase, payload: CaseCreate) -> None:
    values = payload.model_dump()
    values["secondary_issue_types_json"] = values.pop("secondary_issue_types")
    for key, value in values.items():
        setattr(case, key, value)


def _next_case_no(db: Session) -> str:
    prefix = f"AS-{date.today():%Y%m%d}-"
    highest = (
        db.query(func.max(AfterSalesCase.case_no))
        .filter(AfterSalesCase.case_no.like(f"{prefix}%"))
        .scalar()
    )
    try:
        sequence = int((highest or "").removeprefix(prefix)) + 1
    except ValueError:
        sequence = 1
    return f"{prefix}{sequence:03d}"


def create_case(db: Session, payload: CaseCreate, creator: ArkUser) -> AfterSalesCase:
    case = AfterSalesCase(
        case_no=_next_case_no(db),
        creator_user_id=creator.id,
        creator_name_snapshot=creator.real_name,
        current_status="draft",
        current_owner_user_id=creator.id,
    )
    _apply_payload(case, payload)
    db.add(case)
    db.flush()
    _event(db, case, "created", creator)
    db.flush()
    return case


def update_case(
    db: Session,
    case_id: int,
    payload: CaseCreate,
    actor: ArkUser,
) -> AfterSalesCase:
    case = _case_for_update(db, case_id)
    _require_creator(case, actor)
    if case.current_status not in EDITABLE_STATUSES:
        raise WorkflowOperationError("售后单已提交，业务字段已锁定")
    _apply_payload(case, payload)
    invalidate_evidence_waiver(case)
    case.version += 1
    _event(db, case, "updated", actor)
    db.flush()
    return case


def delete_draft(db: Session, case_id: int, actor: ArkUser) -> AfterSalesCase:
    case = _case_for_update(db, case_id)
    _require_creator(case, actor)
    if case.current_status != "draft":
        raise WorkflowOperationError("只有草稿可以删除")
    case.deleted_at = datetime.utcnow()
    case.current_status = "cancelled"
    case.current_owner_user_id = None
    case.version += 1
    _event(db, case, "cancelled", actor, detail={"reason": "创建人删除草稿"})
    db.flush()
    return case


def save_decision(
    db: Session,
    case_id: int,
    actor: ArkUser,
    *,
    responsibility_class: str,
    responsibility_reason: str,
    responsibility_override_reason: str | None,
    actions: list[dict],
    customer_reply_draft: str,
    requires_return: bool,
) -> AfterSalesCase:
    case = _case_for_update(db, case_id)
    _require_creator(case, actor)
    if case.current_status not in {"ai_failed", "awaiting_sales_decision", "returned"}:
        raise WorkflowOperationError("当前状态不能保存处理决定")
    if responsibility_class not in {"A", "B", "C", "D"}:
        raise WorkflowOperationError("责任判定必须是 A/B/C/D")
    if not actions:
        raise WorkflowOperationError("至少选择一项处理措施")
    latest_ai = (
        db.query(AfterSalesAiRun)
        .filter(AfterSalesAiRun.case_id == case.id, AfterSalesAiRun.status == "success")
        .order_by(AfterSalesAiRun.run_no.desc())
        .first()
    )
    ai_class = ((latest_ai.output_json or {}).get("responsibility") or {}).get("class") if latest_ai else None
    if ai_class and responsibility_class != ai_class and not (responsibility_override_reason or "").strip():
        raise WorkflowOperationError("修改 AI 责任判定必须填写原因")
    has_manual_sop_basis = (
        "无适用条款" in responsibility_reason
        or bool(re.search(r"SOP\s*(?:条款\s*[:：]\s*\S.{2,}|第?\s*\d+(?:\.\d+)+)", responsibility_reason, re.I))
    )
    if case.current_status == "ai_failed" and not has_manual_sop_basis:
        raise WorkflowOperationError("AI 失败时人工方案必须注明 SOP 条款，或填写“无适用条款”")
    if len(re.findall(r"[A-Za-z]{2,}", customer_reply_draft)) < 5:
        raise WorkflowOperationError("客户回复必须填写英文话术")
    has_compensation, total = classify_compensation(actions)
    if has_compensation and "subject to final internal approval" not in customer_reply_draft.lower():
        raise WorkflowOperationError("赔偿英文话术必须声明待内部最终审批")

    case.responsibility_class = responsibility_class
    case.responsibility_reason = responsibility_reason
    case.responsibility_override_reason = responsibility_override_reason
    case.selected_actions_json = actions
    case.has_compensation = has_compensation
    case.estimated_compensation_usd = total
    case.customer_reply_draft = customer_reply_draft
    case.requires_return = requires_return
    case.version += 1
    _event(
        db,
        case,
        "decision_saved",
        actor,
        detail={
            "responsibility_class": responsibility_class,
            "responsibility_reason": responsibility_reason,
            "responsibility_override_reason": responsibility_override_reason,
            "has_compensation": has_compensation,
            "estimated_compensation_usd": str(total),
        },
    )
    db.flush()
    return case


def _active_external_id(db: Session, user_id: int) -> str:
    bindings = (
        db.query(ArkUserExternalBinding)
        .filter(
            ArkUserExternalBinding.ark_user_id == user_id,
            ArkUserExternalBinding.provider == "okki",
            ArkUserExternalBinding.binding_status == "active",
            ArkUserExternalBinding.deleted_at.is_(None),
        )
        .all()
    )
    if len(bindings) != 1:
        raise ApprovalConfigurationError("业务员必须唯一绑定 OKKI 员工账号")
    return bindings[0].external_account_id


def _user_by_external_id(db: Session, external_id: str, role_label: str) -> ArkUser:
    users = (
        db.query(ArkUser)
        .join(ArkUserExternalBinding, ArkUserExternalBinding.ark_user_id == ArkUser.id)
        .filter(
            ArkUserExternalBinding.provider == "okki",
            ArkUserExternalBinding.external_account_id == external_id,
            ArkUserExternalBinding.binding_status == "active",
            ArkUserExternalBinding.deleted_at.is_(None),
            ArkUser.is_active.is_(True),
            ArkUser.deleted_at.is_(None),
        )
        .all()
    )
    if len(users) != 1:
        raise ApprovalConfigurationError(f"{role_label}无法唯一匹配方舟用户")
    if not users[0].dingtalk_id:
        raise ApprovalConfigurationError(f"{role_label}尚未绑定钉钉账号")
    return users[0]


def _resolve_supervisor(db: Session, creator: ArkUser) -> ArkUser:
    salesperson_id = _active_external_id(db, creator.id)
    relations = (
        db.query(SupervisorRelationHistory)
        .filter(
            SupervisorRelationHistory.salesperson_id == salesperson_id,
            SupervisorRelationHistory.is_current.is_(True),
        )
        .all()
    )
    if len(relations) != 1:
        raise ApprovalConfigurationError("直属主管关系缺失或不唯一")
    return _user_by_external_id(db, relations[0].supervisor_id, "直属主管")


def _resolve_director(db: Session) -> ArkUser:
    directors = (
        db.query(ArkUser)
        .join(ArkUserRole, ArkUserRole.user_id == ArkUser.id)
        .join(ArkRole, ArkRole.id == ArkUserRole.role_id)
        .filter(
            ArkRole.name == "sales_director",
            ArkUser.is_active.is_(True),
            ArkUser.deleted_at.is_(None),
        )
        .all()
    )
    if len(directors) != 1:
        raise ApprovalConfigurationError("销售总监必须且只能配置一人")
    if not directors[0].dingtalk_id:
        raise ApprovalConfigurationError("销售总监尚未绑定钉钉账号")
    return directors[0]


def refresh_evidence(db: Session, case: AfterSalesCase) -> None:
    rows = (
        db.query(AfterSalesEvidence)
        .filter(AfterSalesEvidence.case_id == case.id, AfterSalesEvidence.deleted_at.is_(None))
        .all()
    )
    evaluation = evaluate_evidence(
        case.primary_issue_type,
        case.batch_no,
        case.care_storage_note,
        [{"evidence_type": row.evidence_type} for row in rows],
    )
    case.evidence_score = evaluation.score
    case.evidence_is_sufficient = evaluation.is_sufficient
    case.evidence_missing_items_json = evaluation.missing_items


def invalidate_evidence_waiver(case: AfterSalesCase) -> None:
    """证据或登记事实变化后，旧豁免结论不再有效。"""
    case.evidence_waiver_approved = False
    case.evidence_waiver_reason = None
    case.evidence_waiver_decision_note = None
    case.evidence_waived_by_user_id = None
    case.evidence_waived_at = None


def request_evidence_waiver(
    db: Session,
    case_id: int,
    actor: ArkUser,
    *,
    reason: str,
    version: int,
    idempotency_key: str,
) -> AfterSalesCase:
    case = _case_for_update(db, case_id)
    if _is_replayed_event(db, case_id, idempotency_key):
        return case
    _require_creator(case, actor)
    _check_version(case, version)
    if case.current_status not in EDITABLE_STATUSES:
        raise WorkflowOperationError("当前状态不能申请证据豁免")
    if not reason.strip():
        raise WorkflowOperationError("申请证据豁免必须填写原因")
    refresh_evidence(db, case)
    if case.evidence_is_sufficient:
        raise WorkflowOperationError("证据已达到最低要求，无需申请豁免")

    supervisor = _resolve_supervisor(db, actor)
    invalidate_evidence_waiver(case)
    case.evidence_waiver_reason = reason.strip()
    case.supervisor_user_id_snapshot = supervisor.id
    case.current_status = "awaiting_evidence_waiver"
    case.current_owner_user_id = supervisor.id
    case.version += 1
    _event(
        db,
        case,
        "evidence_waiver_requested",
        actor,
        detail={"reason": reason.strip(), "missing_items": case.evidence_missing_items_json or []},
        idempotency_key=idempotency_key,
    )
    enqueue_notification(
        db,
        case,
        f"case:{case.id}:evidence-waiver:{case.version}:requested",
        supervisor,
        "evidence_waiver_requested",
        _notification_payload(case, "售后证据豁免待确认", f"{case.case_no}｜{reason.strip()}"),
    )
    db.flush()
    return case


def review_evidence_waiver(
    db: Session,
    case_id: int,
    actor: ArkUser,
    *,
    decision: str,
    comment: str,
    version: int,
    idempotency_key: str,
) -> AfterSalesCase:
    case = _case_for_update(db, case_id)
    if _is_replayed_event(db, case_id, idempotency_key):
        return case
    _check_version(case, version)
    if case.current_status != "awaiting_evidence_waiver":
        raise WorkflowOperationError("当前没有待确认的证据豁免")
    if actor.id != case.supervisor_user_id_snapshot:
        raise WorkflowOperationError("当前用户不是指定直属主管")
    if decision not in {"approve", "reject"}:
        raise WorkflowOperationError("证据豁免只能通过或拒绝")
    if not comment.strip():
        raise WorkflowOperationError("证据豁免审核必须填写意见")

    case.evidence_waiver_approved = decision == "approve"
    case.evidence_waiver_decision_note = comment.strip()
    case.evidence_waived_by_user_id = actor.id if decision == "approve" else None
    case.evidence_waived_at = datetime.utcnow() if decision == "approve" else None
    case.current_status = "awaiting_sales_decision" if decision == "approve" else "returned"
    case.current_owner_user_id = case.creator_user_id
    case.version += 1
    _event(
        db,
        case,
        f"evidence_waiver_{decision}",
        actor,
        detail={"comment": comment.strip()},
        idempotency_key=idempotency_key,
    )
    creator = db.get(ArkUser, case.creator_user_id)
    enqueue_notification(
        db,
        case,
        f"case:{case.id}:evidence-waiver:{case.version}:{decision}",
        creator,
        f"evidence_waiver_{decision}",
        _notification_payload(
            case,
            "售后证据豁免已通过" if decision == "approve" else "售后证据豁免已拒绝",
            f"{case.case_no}｜{actor.real_name}：{comment.strip()}",
        ),
    )
    db.flush()
    return case


def submit_case(
    db: Session,
    case_id: int,
    actor: ArkUser,
    *,
    version: int,
    idempotency_key: str,
) -> AfterSalesCase:
    case = _case_for_update(db, case_id)
    if _is_replayed_event(db, case_id, idempotency_key):
        return case
    _require_creator(case, actor)
    _check_version(case, version)
    if case.current_status not in {"awaiting_sales_decision", "returned", "ai_failed"}:
        raise WorkflowOperationError("当前状态不能提交审核")
    refresh_evidence(db, case)
    if not case.evidence_is_sufficient and not case.evidence_waiver_approved:
        missing = "、".join(case.evidence_missing_items_json or [])
        raise WorkflowOperationError(f"证据未达到最低要求：{missing}")
    if case.sales_evidence_confirmed is None:
        raise WorkflowOperationError("业务员尚未确认客户证据完整")
    if case.sales_evidence_confirmed is False and not case.evidence_waiver_approved:
        raise WorkflowOperationError("业务员确认客户证据不完整，请先申请主管豁免")
    if not case.responsibility_class or not case.selected_actions_json or not case.customer_reply_draft:
        raise WorkflowOperationError("请先完成责任判定、处理措施和客户回复")
    try:
        validate_actions(case.selected_actions_json)
    except ValueError as exc:
        raise WorkflowOperationError(str(exc)) from exc

    supervisor = _resolve_supervisor(db, actor)
    director = _resolve_director(db) if case.has_compensation else None
    case.supervisor_user_id_snapshot = supervisor.id
    case.director_user_id_snapshot = director.id if director else None
    case.current_status = "awaiting_supervisor"
    case.current_owner_user_id = supervisor.id
    case.workflow_round += 1
    case.version += 1
    _event(
        db,
        case,
        "submitted",
        actor,
        detail={"supervisor_user_id": supervisor.id, "director_user_id": director.id if director else None},
        idempotency_key=idempotency_key,
    )
    enqueue_notification(
        db,
        case,
        f"case:{case.id}:round:{case.workflow_round}:submitted",
        supervisor,
        "awaiting_supervisor",
        _notification_payload(
            case,
            "售后单待主管审核",
            f"{case.case_no}｜{case.customer_name_snapshot}｜{case.primary_issue_type}",
        ),
    )
    db.flush()
    return case


def withdraw_case(
    db: Session,
    case_id: int,
    actor: ArkUser,
    *,
    version: int,
) -> AfterSalesCase:
    case = _case_for_update(db, case_id)
    _require_creator(case, actor)
    _check_version(case, version)
    if case.current_status != "awaiting_supervisor":
        raise WorkflowOperationError("只有主管未审核的单据可以撤回")
    reviewed = (
        db.query(AfterSalesReview.id)
        .filter(
            AfterSalesReview.case_id == case.id,
            AfterSalesReview.workflow_round == case.workflow_round,
        )
        .first()
    )
    if reviewed:
        raise WorkflowOperationError("审批人已处理，不能撤回")
    case.current_status = "awaiting_sales_decision"
    case.current_owner_user_id = actor.id
    case.supervisor_user_id_snapshot = None
    case.director_user_id_snapshot = None
    case.version += 1
    _event(db, case, "withdrawn", actor)
    db.flush()
    return case


def review_case(
    db: Session,
    case_id: int,
    actor: ArkUser,
    *,
    decision: str,
    comment: str,
    version: int,
    idempotency_key: str,
    allow_proxy: bool = False,
    proxy_reason: str | None = None,
) -> AfterSalesCase:
    existing = (
        db.query(AfterSalesReview)
        .filter(AfterSalesReview.idempotency_key == idempotency_key)
        .first()
    )
    case = _case_for_update(db, case_id)
    if existing:
        if existing.case_id != case.id:
            raise WorkflowOperationError("幂等键已被其他售后单使用")
        return case
    _check_version(case, version)
    expected_reviewer_id = None
    role = None
    if case.current_status == "awaiting_supervisor":
        role = "supervisor"
        expected_reviewer_id = case.supervisor_user_id_snapshot
    elif case.current_status == "awaiting_director":
        role = "director"
        expected_reviewer_id = case.director_user_id_snapshot
    if role is None:
        raise WorkflowOperationError("当前状态不允许审核")
    is_proxy = actor.id != expected_reviewer_id
    if is_proxy and not allow_proxy:
        raise WorkflowOperationError("当前用户不是该售后单的指定审批人")
    if is_proxy and not (proxy_reason or "").strip():
        raise WorkflowOperationError("管理员代理审核必须填写代理原因")
    if decision in {"return", "reject"} and not comment.strip():
        raise WorkflowOperationError("退回或拒绝必须填写原因")

    has_compensation, total = classify_compensation(case.selected_actions_json or [])
    case.has_compensation = has_compensation
    case.estimated_compensation_usd = total
    new_status = next_status(case.current_status, role, decision, has_compensation)
    review = AfterSalesReview(
        case_id=case.id,
        workflow_round=case.workflow_round,
        reviewer_role=role,
        reviewer_user_id=actor.id,
        reviewer_name_snapshot=actor.real_name,
        decision=decision,
        remark=comment,
        compensation_snapshot_json={
            "actions": case.selected_actions_json,
            "estimated_compensation_usd": str(total),
        },
        idempotency_key=idempotency_key,
    )
    db.add(review)
    case.current_status = new_status
    if new_status == "awaiting_director":
        case.current_owner_user_id = case.director_user_id_snapshot
    else:
        case.current_owner_user_id = case.creator_user_id
    if new_status == "approved":
        case.approved_at = datetime.utcnow()
    case.version += 1
    if is_proxy:
        _event(
            db,
            case,
            "review_proxied",
            actor,
            detail={
                "role": role,
                "original_reviewer_user_id": expected_reviewer_id,
                "proxy_reason": proxy_reason.strip(),
            },
        )
    _event(db, case, f"review_{decision}", actor, detail={"role": role, "comment": comment})
    if new_status == "awaiting_director":
        recipient = db.get(ArkUser, case.director_user_id_snapshot)
        template_code = "awaiting_director"
        title = "赔偿售后单待销售总监终审"
        content = (
            f"{case.case_no}｜客户等级 {case.customer_grade}｜"
            f"预计赔偿 USD {case.estimated_compensation_usd}"
        )
    else:
        recipient = db.get(ArkUser, case.creator_user_id)
        template_code = {
            "approved": "approved",
            "returned": "returned",
            "rejected": "rejected",
        }[new_status]
        title = {
            "approved": "售后方案已审批通过",
            "returned": "售后单已退回补充",
            "rejected": "售后方案已拒绝",
        }[new_status]
        content = f"{case.case_no}｜{actor.real_name}：{comment or '已通过'}"
    enqueue_notification(
        db,
        case,
        f"case:{case.id}:round:{case.workflow_round}:{role}:{decision}",
        recipient,
        template_code,
        _notification_payload(case, title, content),
    )
    db.flush()
    return case


def transfer_approval(
    db: Session,
    case_id: int,
    actor: ArkUser,
    new_reviewer: ArkUser,
    *,
    reason: str,
    version: int,
    idempotency_key: str,
) -> AfterSalesCase:
    case = _case_for_update(db, case_id)
    if _is_replayed_event(db, case_id, idempotency_key):
        return case
    _check_version(case, version)
    if case.current_status not in {"awaiting_supervisor", "awaiting_director"}:
        raise WorkflowOperationError("只有待审核单据可以转交")
    if not reason.strip():
        raise WorkflowOperationError("转交审批必须填写原因")
    if not new_reviewer.is_active or new_reviewer.deleted_at is not None:
        raise WorkflowOperationError("新审批人不存在或已停用")
    if not new_reviewer.dingtalk_id:
        raise WorkflowOperationError("新审批人尚未绑定钉钉账号")

    role = "supervisor" if case.current_status == "awaiting_supervisor" else "director"
    old_reviewer_id = (
        case.supervisor_user_id_snapshot if role == "supervisor" else case.director_user_id_snapshot
    )
    if old_reviewer_id == new_reviewer.id:
        raise WorkflowOperationError("新审批人与当前审批人相同")
    old_reviewer = db.get(ArkUser, old_reviewer_id)
    if role == "supervisor":
        case.supervisor_user_id_snapshot = new_reviewer.id
    else:
        case.director_user_id_snapshot = new_reviewer.id
    case.current_owner_user_id = new_reviewer.id
    case.version += 1
    _event(
        db,
        case,
        "approval_transferred",
        actor,
        detail={
            "role": role,
            "from_user_id": old_reviewer_id,
            "to_user_id": new_reviewer.id,
            "reason": reason.strip(),
        },
        idempotency_key=idempotency_key,
    )
    recipients = {user.id: user for user in [old_reviewer, new_reviewer, db.get(ArkUser, case.creator_user_id)] if user}
    for recipient in recipients.values():
        enqueue_notification(
            db,
            case,
            f"case:{case.id}:round:{case.workflow_round}:transfer:{case.version}",
            recipient,
            "approval_transferred",
            _notification_payload(
                case,
                "售后审批已转交",
                f"{case.case_no}｜{old_reviewer.real_name if old_reviewer else '原审批人'} → {new_reviewer.real_name}｜{reason.strip()}",
            ),
        )
    db.flush()
    return case


def execute_case(
    db: Session,
    case_id: int,
    actor: ArkUser,
    execution_result: str,
    customer_feedback: str | None,
) -> AfterSalesCase:
    case = _case_for_update(db, case_id)
    _require_creator(case, actor)
    if case.current_status not in {"approved", "processing"}:
        raise WorkflowOperationError("只有审批完成的售后单可以登记执行结果")
    if not execution_result.strip():
        raise WorkflowOperationError("请填写执行结果")
    case.execution_result = execution_result
    case.customer_feedback = customer_feedback
    case.current_status = "processing"
    case.current_owner_user_id = actor.id
    case.version += 1
    _event(db, case, "execution_updated", actor)
    db.flush()
    return case


def close_case(
    db: Session,
    case_id: int,
    actor: ArkUser,
    customer_feedback: str,
) -> AfterSalesCase:
    case = _case_for_update(db, case_id)
    _require_creator(case, actor)
    if case.current_status != "processing" or not case.execution_result:
        raise WorkflowOperationError("请先登记执行结果再关闭")
    if not customer_feedback.strip():
        raise WorkflowOperationError("关闭前请记录客户反馈")
    case.customer_feedback = customer_feedback
    case.current_status = "closed"
    case.current_owner_user_id = None
    case.closed_at = datetime.utcnow()
    case.version += 1
    _event(db, case, "closed", actor)
    db.flush()
    return case


def reopen_case(
    db: Session,
    case_id: int,
    actor: ArkUser,
    reason: str,
) -> AfterSalesCase:
    case = _case_for_update(db, case_id)
    if case.current_status not in {"closed", "rejected"}:
        raise WorkflowOperationError("只有已关闭或已拒绝的售后单可以重新打开")
    if not reason.strip():
        raise WorkflowOperationError("重新打开必须填写原因")
    previous_resolution = {
        "execution_result": case.execution_result,
        "customer_feedback": case.customer_feedback,
        "approved_at": case.approved_at.isoformat() if case.approved_at else None,
        "closed_at": case.closed_at.isoformat() if case.closed_at else None,
    }
    case.current_status = "returned"
    case.current_owner_user_id = case.creator_user_id
    case.execution_result = None
    case.customer_feedback = None
    case.approved_at = None
    case.closed_at = None
    case.version += 1
    _event(
        db,
        case,
        "reopened",
        actor,
        detail={"reason": reason, "previous_resolution": previous_resolution},
    )
    db.flush()
    return case
