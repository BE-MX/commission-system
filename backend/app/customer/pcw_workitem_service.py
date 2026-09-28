"""私海客户工作台（PCW）：经营事项与多轮行动基础服务。

设计依据 docs/requirements/private-customer-workbench-prototype/：
- schema-migrations.md 第 5 节：事项/行动轮次/维护实例在同一事务内联动；
- api-contracts.md 第 4.1、6 节：完成行动的版本前置、幂等与结果/后续原子性；
- development-spec.md PCW-01：done 仅代表本次动作完成，事项是否解决由独立状态决定。

CustomerWorkItem 以 (business_key, business_cycle) 跨日去重；CustomerAction 按
(work_item_id, action_round) 唯一。本模块是评估、监控、维护、样品、活动等
PCW 域创建与完成行动的统一入口，不重复实现 workflow_service 的通用校验。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Iterable, Mapping

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import beijing_now, to_beijing_naive
from app.customer import pcw_errors
from app.customer.models import (
    CustomerAccount,
    CustomerAction,
    CustomerEvent,
)
from app.customer.pcw_idempotency import run_with_receipt
from app.customer.pcw_models import CustomerWorkItem, MaintenanceOccurrence
from app.customer.workflow_service import (
    ACTION_CHANNELS,
    ACTION_OUTCOME_CODES,
    _account_for_update,
    _active_user,
    _fact_ids,
    _fingerprint,
)

logger = logging.getLogger(__name__)

WORK_ITEM_STATES = frozenset({"open", "awaiting_reply", "resolved", "cancelled"})
WORK_ITEM_TRANSITIONS = frozenset({"await_reply", "keep_open", "resolve"})
PCW_ACTION_POLICY_VERSION = "pcw_rules_v1"


def ensure_work_item(
    db: Session,
    *,
    customer_id: int,
    business_key: str,
    business_cycle: str,
    work_type: str,
    title: str,
    context: Mapping | None = None,
) -> CustomerWorkItem:
    """按稳定业务键取或建经营事项；并发/重复扫描返回同一行。"""
    existing = db.query(CustomerWorkItem).filter(
        CustomerWorkItem.business_key == business_key,
        CustomerWorkItem.business_cycle == business_cycle,
    ).one_or_none()
    if existing is not None:
        return existing
    row = CustomerWorkItem(
        customer_id=customer_id,
        business_key=business_key,
        business_cycle=business_cycle,
        work_type=work_type,
        state="open",
        title=title[:500],
        context_json={"schema_version": "pcw_work_item_context_v1", **dict(context or {})},
        next_action_round=1,
        row_version=1,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
        return row
    except IntegrityError as exc:
        winner = db.query(CustomerWorkItem).filter(
            CustomerWorkItem.business_key == business_key,
            CustomerWorkItem.business_cycle == business_cycle,
        ).one_or_none()
        if winner is not None:
            return winner
        raise pcw_errors.conflict(
            "并发写入冲突，请在新事务中重试", error_code="RETRY_NEW_TRANSACTION"
        ) from exc


def _event_ids_for_customer(
    db: Session, *, customer_id: int, values: Iterable[int]
) -> list[int]:
    event_ids = sorted(set(values))
    if any(type(value) is not int or value <= 0 for value in event_ids):
        raise pcw_errors.bad_request("来源事件ID不合法", error_code="SOURCE_EVENT_INVALID")
    if not event_ids:
        return []
    rows = db.query(CustomerEvent.id).filter(
        CustomerEvent.customer_id == customer_id,
        CustomerEvent.id.in_(event_ids),
    ).all()
    if {row.id for row in rows} != set(event_ids):
        raise pcw_errors.conflict(
            "来源事件不属于该客户", error_code="SOURCE_EVENT_CUSTOMER_MISMATCH"
        )
    return event_ids


def create_pcw_action(
    db: Session,
    *,
    work_item: CustomerWorkItem,
    owner_user_id: int | None,
    action_type: str,
    thread_group: str,
    priority: str,
    reason: str,
    next_action: str,
    channel: str | None = None,
    contact_id: int | None = None,
    opportunity_id: int | None = None,
    business_due_at: datetime | None = None,
    original_due_at: datetime | None = None,
    due_provenance: str | None = None,
    planned_at: datetime | None = None,
    source_event_ids: Iterable[int] = (),
    evidence_fact_ids: Iterable[int] = (),
    suggested_message: str | None = None,
    policy_version: str = PCW_ACTION_POLICY_VERSION,
    source_type: str = "rule",
    parent_action: CustomerAction | None = None,
) -> CustomerAction:
    """在事项行锁内分配行动轮次并创建 PCW 行动；按 (work_item_id, action_round) 幂等。

    指纹为 pcw_action_v1:事项:轮次，不含扫描日期，跨日重复评估复用同一行动。
    """
    item = db.query(CustomerWorkItem).filter(
        CustomerWorkItem.id == work_item.id,
    ).populate_existing().with_for_update().one_or_none()
    if item is None:
        raise pcw_errors.not_found("经营事项不存在", error_code="WORK_ITEM_NOT_FOUND")
    if item.state in {"resolved", "cancelled"}:
        raise pcw_errors.conflict(
            "经营事项已结束，不能在其下新建行动；新的业务周期应建立新事项",
            error_code="WORK_ITEM_CLOSED",
        )
    customer_id = int(item.customer_id)
    account = _account_for_update(db, customer_id)
    profile_version_id = account.current_profile_version_id
    if profile_version_id is None:
        raise pcw_errors.conflict(
            "客户档案尚未编译，先编译最小可信档案再生成行动",
            error_code="PROFILE_NOT_READY",
        )
    if owner_user_id is None:
        if thread_group != "public_pool":
            raise pcw_errors.conflict(
                "私海行动必须有明确的执行负责人", error_code="ACTION_OWNER_REQUIRED"
            )
    else:
        _active_user(db, owner_user_id)
    facts = _fact_ids(db, customer_id=customer_id, values=evidence_fact_ids)
    events = _event_ids_for_customer(db, customer_id=customer_id, values=source_event_ids)
    round_no = int(item.next_action_round)
    if parent_action is None and round_no > 1:
        parent_action = db.query(CustomerAction).filter(
            CustomerAction.work_item_id == item.id,
            CustomerAction.action_round == round_no - 1,
        ).one_or_none()
    due = to_beijing_naive(business_due_at) if business_due_at else None
    now = beijing_now()
    fingerprint = _fingerprint("pcw_action_v1", item.id, round_no)
    existing = db.query(CustomerAction).filter(
        CustomerAction.action_fingerprint == fingerprint,
    ).one_or_none()
    if existing is not None:
        return existing
    row = CustomerAction(
        customer_id=customer_id,
        owner_user_id=owner_user_id,
        opportunity_id=opportunity_id,
        contact_id=contact_id,
        action_type=action_type,
        thread_group=thread_group,
        channel=channel,
        priority=priority,
        reason=reason[:1000],
        next_action=next_action[:1000],
        suggested_message=suggested_message,
        planned_at=to_beijing_naive(planned_at) if planned_at else None,
        due_at=due,
        action_date=(due or now).date(),
        status="pending",
        feedback_json={"schema_version": "action_feedback_v1"},
        source_event_ids=events,
        evidence_fact_ids=facts,
        profile_version_id=int(profile_version_id),
        source_type=source_type,
        policy_version=policy_version,
        action_fingerprint=fingerprint,
        evidence_status="valid",
        generated_at=now,
        created_at=now,
        updated_at=now,
        work_item_id=item.id,
        action_round=round_no,
        parent_action_id=parent_action.id if parent_action is not None else None,
        row_version=1,
        original_due_at=to_beijing_naive(original_due_at) if original_due_at else due,
        business_due_at=due,
        due_provenance=due_provenance,
    )
    try:
        with db.begin_nested():
            db.add(row)
            item.next_action_round = round_no + 1
            item.row_version = int(item.row_version) + 1
            item.updated_at = now
            account.profile_input_seq = int(account.profile_input_seq) + 1
            account.updated_at = now
            db.flush()
        return row
    except IntegrityError as exc:
        db.expire(item)
        winner = db.query(CustomerAction).filter(
            CustomerAction.action_fingerprint == fingerprint,
        ).one_or_none()
        if winner is not None:
            return winner
        raise pcw_errors.conflict(
            "并发写入冲突，请在新事务中重试", error_code="RETRY_NEW_TRANSACTION"
        ) from exc


def _lock_action_for_actor(
    db: Session, *, action_id: int, actor_user_id: int, can_manage: bool
) -> tuple[CustomerAction, int]:
    """定位行动、锁账户、锁行动并校验执行人范围；返回 (行动, 逻辑客户ID)。"""
    from app.customer.logical_customer_service import (
        logical_owner_expression,
        logical_root_predicate,
    )

    action_owner = logical_owner_expression(CustomerAction, "action")
    candidate = db.query(
        CustomerAction, action_owner.label("logical_customer_id"),
    ).filter(CustomerAction.id == action_id).one_or_none()
    if candidate is None:
        raise pcw_errors.customer_not_found()
    _, logical_customer_id = candidate
    logical_customer_id = int(logical_customer_id)
    _account_for_update(db, logical_customer_id)
    action = db.query(CustomerAction).filter(
        CustomerAction.id == action_id,
        logical_root_predicate(CustomerAction, "action", logical_customer_id),
    ).populate_existing().with_for_update().one_or_none()
    if action is None:
        raise pcw_errors.customer_not_found()
    _active_user(db, actor_user_id)
    if not can_manage and action.owner_user_id != actor_user_id:
        raise pcw_errors.conflict(
            "只能由行动负责人或有管理权限的人操作", error_code="ACTION_OWNER_REQUIRED"
        )
    if not can_manage:
        from app.customer.models import CustomerAssignment

        assignment = db.query(CustomerAssignment.id).filter(
            CustomerAssignment.customer_id == logical_customer_id,
            CustomerAssignment.user_id == actor_user_id,
            CustomerAssignment.assignment_role.in_(("primary", "collaborator")),
            CustomerAssignment.assignment_status == "active",
            CustomerAssignment.effective_to.is_(None),
        ).first()
        if assignment is None:
            raise pcw_errors.conflict(
                "操作人不在该客户当前归属范围内", error_code="ACTION_ACTOR_FORBIDDEN"
            )
    return action, logical_customer_id


def _require_version(current: int, expected: int, error_code: str, detail_key: str) -> None:
    if int(current) != int(expected):
        raise pcw_errors.conflict(
            "版本已变化，请刷新后重新确认",
            error_code=error_code,
            details={detail_key: int(current)},
        )


def _check_contact_restricted(
    db: Session, *, customer_id: int, channel: str | None
) -> None:
    from app.sales_automation.public_pool_service import is_development_denied

    denied = is_development_denied(db, customer_id, "global", None)
    if not denied and channel:
        denied = is_development_denied(db, customer_id, "channel", channel)
    if denied:
        raise pcw_errors.conflict(
            "客户存在生效的联系限制，禁止登记触达结果",
            error_code="CONTACT_RESTRICTED",
        )


def _create_v2_followup(
    db: Session,
    *,
    action: CustomerAction,
    logical_customer_id: int,
    work_item: CustomerWorkItem | None,
    activity_event_id: int,
    next_step: str,
    next_step_due_at: datetime,
    followup_action_type: str,
    followup_channel: str,
) -> CustomerAction:
    if followup_action_type not in {"call", "email", "message", "meeting", "research", "review"}:
        raise pcw_errors.bad_request("后续行动类型不合法", error_code="FOLLOWUP_TYPE_INVALID")
    if followup_channel not in ACTION_CHANNELS:
        raise pcw_errors.bad_request("后续渠道不合法", error_code="FOLLOWUP_CHANNEL_INVALID")
    deadline = to_beijing_naive(next_step_due_at)
    if deadline <= beijing_now():
        raise pcw_errors.bad_request("后续期限必须晚于当前时间", error_code="FOLLOWUP_TIME_MUST_BE_FUTURE")
    if work_item is not None:
        return create_pcw_action(
            db,
            work_item=work_item,
            owner_user_id=action.owner_user_id,
            action_type=followup_action_type,
            thread_group=action.thread_group,
            priority=action.priority,
            reason="业务员登记跟进结果后安排的后续行动。",
            next_action=next_step,
            channel=followup_channel,
            contact_id=action.contact_id,
            opportunity_id=action.opportunity_id,
            business_due_at=deadline,
            due_provenance="human_followup",
            planned_at=deadline,
            source_event_ids=[activity_event_id],
            evidence_fact_ids=action.evidence_fact_ids or [],
            policy_version="human_followup_v1",
            source_type="manual",
            parent_action=action,
        )
    from types import SimpleNamespace

    from app.customer.followup_service import create_followup, followup_request

    request = followup_request(
        next_step=next_step, due_at=deadline,
        action_type=followup_action_type, channel=followup_channel,
    )
    activity_ref = SimpleNamespace(id=activity_event_id)
    return create_followup(db, action, activity_ref, logical_customer_id, request)


def complete_action_v2(
    db: Session,
    *,
    action_id: int,
    actor_user_id: int,
    can_manage: bool = False,
    expected_action_version: int,
    expected_work_item_version: int | None = None,
    expected_occurrence_version: int | None = None,
    work_item_transition: str | None = None,
    outcome_code: str,
    channel: str,
    occurred_at: datetime,
    summary: str,
    evidence_message_ids: Iterable[int] = (),
    next_step: str | None = None,
    next_step_due_at: datetime | None = None,
    followup_action_type: str = "message",
    followup_channel: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """完成行动并按事项/维护实例原子安排后续（api-contracts 4.1）。

    - 非 resolve 的事项转移必须给出下一步与期限；失败不产生任何部分写入。
    - 关联维护实例的行动必须携带 expected_occurrence_version。
    - 同 Idempotency-Key 重放返回同一后续行动；不同内容返回 409。
    """
    request_payload = {
        "action_id": action_id,
        "expected_action_version": expected_action_version,
        "expected_work_item_version": expected_work_item_version,
        "expected_occurrence_version": expected_occurrence_version,
        "work_item_transition": work_item_transition,
        "outcome_code": outcome_code,
        "channel": channel,
        "occurred_at": to_beijing_naive(occurred_at).isoformat(),
        "summary": summary,
        "evidence_message_ids": sorted(set(evidence_message_ids)),
        "next_step": next_step,
        "next_step_due_at": to_beijing_naive(next_step_due_at).isoformat() if next_step_due_at else None,
        "followup_action_type": followup_action_type,
        "followup_channel": followup_channel,
    }

    def _execute() -> dict:
        if outcome_code not in ACTION_OUTCOME_CODES:
            raise pcw_errors.bad_request("结果代码不合法", error_code="ACTION_OUTCOME_INVALID")
        if channel not in ACTION_CHANNELS:
            raise pcw_errors.bad_request("渠道不合法", error_code="ACTION_CHANNEL_INVALID")
        normalized_summary = (summary or "").strip()
        if not normalized_summary or len(normalized_summary) > 1000:
            raise pcw_errors.bad_request("结果摘要必填且不超过1000字", error_code="ACTION_SUMMARY_INVALID")
        if work_item_transition is not None and work_item_transition not in WORK_ITEM_TRANSITIONS:
            raise pcw_errors.bad_request("事项转移不合法", error_code="WORK_ITEM_TRANSITION_INVALID")
        occurred = to_beijing_naive(occurred_at)
        if occurred > beijing_now():
            raise pcw_errors.bad_request("发生时间不能晚于当前时间", error_code="ACTION_OCCURRED_AT_INVALID")

        action, logical_customer_id = _lock_action_for_actor(
            db, action_id=action_id, actor_user_id=actor_user_id, can_manage=can_manage
        )
        _require_version(action.row_version, expected_action_version,
                         "ACTION_VERSION_CONFLICT", "current_action_version")

        work_item: CustomerWorkItem | None = None
        if action.work_item_id is not None:
            work_item = db.query(CustomerWorkItem).filter(
                CustomerWorkItem.id == action.work_item_id,
            ).populate_existing().with_for_update().one_or_none()
            if work_item is None:
                raise pcw_errors.not_found("经营事项不存在", error_code="WORK_ITEM_NOT_FOUND")
            if expected_work_item_version is not None:
                _require_version(work_item.row_version, expected_work_item_version,
                                 "WORK_ITEM_VERSION_CONFLICT", "current_work_item_version")
            if work_item.state in {"resolved", "cancelled"}:
                raise pcw_errors.conflict(
                    "经营事项已结束，不能重复完成", error_code="WORK_ITEM_CLOSED"
                )

        if work_item is not None and work_item_transition != "resolve":
            # 验收红线：等待回复/继续保持必须安排下一步，失败不改变任何状态。
            if not (next_step and next_step.strip()) or next_step_due_at is None:
                raise pcw_errors.bad_request(
                    "未解决的结果必须填写下一步与期限",
                    error_code="NEXT_STEP_REQUIRED",
                )
        if work_item_transition == "resolve" and (next_step and next_step.strip()):
            raise pcw_errors.bad_request(
                "resolve 表示事项已解决，不能同时创建后续（会生成无法完成的死行动）",
                error_code="WORK_ITEM_TRANSITION_INVALID",
            )
        if work_item is not None and work_item_transition is not None and expected_work_item_version is None:
            raise pcw_errors.bad_request(
                "改变事项状态必须携带 expected_work_item_version",
                error_code="WORK_ITEM_VERSION_REQUIRED",
            )

        occurrence: MaintenanceOccurrence | None = None
        if action.id is not None:
            occurrence = db.query(MaintenanceOccurrence).filter(
                MaintenanceOccurrence.current_action_id == action.id,
            ).populate_existing().with_for_update().one_or_none()
        if occurrence is not None:
            if expected_occurrence_version is None:
                raise pcw_errors.bad_request(
                    "该行动关联维护实例，必须携带 expected_occurrence_version",
                    error_code="OCCURRENCE_VERSION_REQUIRED",
                )
            _require_version(occurrence.occurrence_version, expected_occurrence_version,
                             "OCCURRENCE_VERSION_CONFLICT", "current_occurrence_version")
            if occurrence.status in {"fulfilled", "cancelled"}:
                raise pcw_errors.conflict(
                    "维护实例已结束，不能重复完成", error_code="OCCURRENCE_CLOSED"
                )

        if action.status == "done":
            previous = (action.feedback_json or {}).get("completion", {})
            requested_next_step = next_step.strip() if next_step and next_step.strip() else None
            same_completion = (
                previous.get("next_step") == requested_next_step
                and previous.get("summary") == (summary or "").strip()
                and previous.get("outcome_code") == outcome_code
                and previous.get("channel") == channel
            )
            if not same_completion:
                raise pcw_errors.conflict(
                    "该行动已完成且完成内容不一致", error_code="ACTION_COMPLETION_CHANGED"
                )
            followup_id = previous.get("followup_action_id")
            return {
                "action": {"id": action.id, "status": action.status, "version": action.row_version},
                "followup_action": {"id": followup_id} if followup_id else None,
                "event_state": work_item.state if work_item is not None else None,
            }
        if action.status == "snoozed" and action.snoozed_until is not None and action.snoozed_until <= beijing_now():
            action.status = "pending"
        if action.status != "pending":
            raise pcw_errors.conflict("行动不在可完成状态", error_code="ACTION_NOT_PENDING")

        _check_contact_restricted(db, customer_id=logical_customer_id, channel=channel)

        from app.customer.fact_service import append_customer_event

        now = beijing_now()
        action.status = "done"
        action.completed_at = occurred
        action.completed_by = actor_user_id
        action.outcome_code = outcome_code
        action.updated_at = now
        action.row_version = int(action.row_version) + 1
        completion = {
            "channel": channel,
            "outcome_code": outcome_code,
            "summary": normalized_summary,
            "next_step": (next_step or "").strip() or None,
            "evidence_message_ids": sorted(set(evidence_message_ids)),
        }
        action.feedback_json = {
            **dict(action.feedback_json or {}),
            "completion": completion,
        }
        db.flush()

        activity_payload: dict[str, Any] = {
            "action_id": action.id,
            "customer_id": logical_customer_id,
            "channel": channel,
            "occurred_at": occurred.isoformat(),
            "outcome_code": outcome_code,
            "summary": normalized_summary,
            "next_step": completion["next_step"] or "",
        }
        if action.opportunity_id is not None:
            activity_payload["opportunity_id"] = action.opportunity_id
        if action.contact_id is not None:
            activity_payload["contact_id"] = action.contact_id
        activity = append_customer_event(
            db,
            customer_id=logical_customer_id,
            event_type="sales_activity.logged",
            event_source="manual",
            event_title="记录销售活动",
            event_summary=normalized_summary,
            event_payload=activity_payload,
            payload_schema_version="customer_event_v1",
            occurred_at=occurred,
            source_ref_type="action",
            source_ref_id=str(action.id),
            actor_user_id=actor_user_id,
        )
        completion["activity_event_id"] = activity.id

        followup: CustomerAction | None = None
        if next_step and next_step.strip() and next_step_due_at is not None:
            followup = _create_v2_followup(
                db,
                action=action,
                logical_customer_id=logical_customer_id,
                work_item=work_item,
                activity_event_id=activity.id,
                next_step=next_step.strip(),
                next_step_due_at=next_step_due_at,
                followup_action_type=followup_action_type,
                followup_channel=followup_channel or channel,
            )
            completion["followup_action_id"] = followup.id
        action.feedback_json = {**dict(action.feedback_json or {}), "completion": completion}

        if work_item is not None:
            if work_item_transition == "resolve":
                work_item.state = "resolved"
                work_item.resolved_at = now
                work_item.resolved_by = actor_user_id
            elif work_item_transition == "await_reply":
                work_item.state = "awaiting_reply"
            elif work_item_transition == "keep_open":
                work_item.state = "open"
            work_item.row_version = int(work_item.row_version) + 1
            work_item.updated_at = now

        if occurrence is not None:
            if followup is not None:
                occurrence.current_action_id = followup.id
                occurrence.occurrence_date = to_beijing_naive(next_step_due_at).date()
                occurrence.status = "due" if occurrence.occurrence_date <= now.date() else "planned"
            elif work_item_transition == "resolve":
                occurrence.status = "fulfilled"
                occurrence.fulfilled_at = now
                occurrence.fulfilled_by = actor_user_id
            occurrence.occurrence_version = int(occurrence.occurrence_version) + 1
            occurrence.updated_at = now
        db.flush()
        return {
            "action": {"id": action.id, "status": action.status, "version": action.row_version},
            "followup_action": {"id": followup.id, "version": followup.row_version} if followup is not None else None,
            "event_state": work_item.state if work_item is not None else None,
        }

    if idempotency_key:
        result, _replayed = run_with_receipt(
            db,
            actor_user_id=actor_user_id,
            operation_scope=f"action_complete:{action_id}",
            idempotency_key=idempotency_key,
            request_payload=request_payload,
            execute=_execute,
        )
        return result
    return _execute()


def snooze_action_v2(
    db: Session,
    *,
    action_id: int,
    actor_user_id: int,
    can_manage: bool = False,
    expected_action_version: int,
    snoozed_until: datetime,
) -> dict:
    """个人延后：只改 snoozed_until，保留 original_due_at 衡量逾期。"""
    action, _logical_customer_id = _lock_action_for_actor(
        db, action_id=action_id, actor_user_id=actor_user_id, can_manage=can_manage
    )
    _require_version(action.row_version, expected_action_version,
                     "ACTION_VERSION_CONFLICT", "current_action_version")
    if action.status != "pending":
        raise pcw_errors.conflict("只有待执行行动可以延后", error_code="ACTION_NOT_PENDING")
    until = to_beijing_naive(snoozed_until)
    if until <= beijing_now():
        raise pcw_errors.bad_request("延后时间必须晚于当前时间", error_code="SNOOZE_TIME_MUST_BE_FUTURE")
    action.status = "snoozed"
    action.snoozed_until = until
    action.row_version = int(action.row_version) + 1
    action.updated_at = beijing_now()
    db.flush()
    return {"id": action.id, "status": action.status, "version": action.row_version}


def dismiss_action_v2(
    db: Session,
    *,
    action_id: int,
    actor_user_id: int,
    can_manage: bool = False,
    expected_action_version: int,
    dismissal_reason: str,
) -> dict:
    """有理由忽略：原因必填，进入反馈与规则复盘。"""
    reason = (dismissal_reason or "").strip()
    if not reason:
        raise pcw_errors.bad_request("忽略必须填写原因", error_code="DISMISS_REASON_REQUIRED")
    action, _logical_customer_id = _lock_action_for_actor(
        db, action_id=action_id, actor_user_id=actor_user_id, can_manage=can_manage
    )
    _require_version(action.row_version, expected_action_version,
                     "ACTION_VERSION_CONFLICT", "current_action_version")
    if action.status != "pending":
        raise pcw_errors.conflict("只有待执行行动可以忽略", error_code="ACTION_NOT_PENDING")
    action.status = "dismissed"
    action.dismissal_reason = reason[:32]
    action.feedback_json = {
        **dict(action.feedback_json or {}),
        "dismiss": {"reason": reason, "at": beijing_now().isoformat()},
    }
    action.row_version = int(action.row_version) + 1
    action.updated_at = beijing_now()
    db.flush()
    return {"id": action.id, "status": action.status, "version": action.row_version}
