"""私海客户工作台（PCW-06）：日常维护日历（计划/实例/样品/活动/物流关联）。

契约见 docs/requirements/private-customer-workbench-prototype/：
- schema-migrations.md 第 5/6 节：六类维护 typed_payload 与稳定实例键；
  样品阶段 ordered→shipped→delivered→awaiting_test→testing→feedback_received→closed；
- api-contracts.md 4.5/6 节：样品改约三版本原子、活动 preview/actions 诚实分列；
- development-spec.md PCW-06：改约只更新日期不换实例身份；签收不自动开始测试；
  物流必须显式关联（多对多），收件人相似不是绑定依据；DNC 抑制推广。
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.service import get_live_user_authorization
from app.core.time import beijing_now, beijing_today, to_beijing_naive
from app.customer import pcw_errors
from app.customer.access_service import (
    CustomerAccessDenied,
    apply_customer_scope,
    require_customer_access,
)
from app.customer.models import (
    CustomerAccount,
    CustomerAssignment,
    CustomerListProjection,
    CustomerOrder,
    CustomerOrderItem,
)
from app.customer.logical_customer_service import logical_root_predicate
from app.customer.pcw_idempotency import run_with_receipt
from app.customer.pcw_models import (
    Campaign,
    MaintenanceOccurrence,
    MaintenancePlan,
    SampleCase,
    ShipmentOrderLink,
)
from app.customer.pcw_order_service import derive_order_type
from app.customer.pcw_workitem_service import create_pcw_action, ensure_work_item
from app.customer.workflow_service import _account_for_update
from app.tracking.models import ShipmentTracking

logger = logging.getLogger(__name__)

PLAN_TYPES = frozenset({"manual", "birthday", "holiday", "campaign", "shipping", "sample"})
SAMPLE_STAGES = (
    "ordered",
    "shipped",
    "delivered",
    "awaiting_test",
    "testing",
    "feedback_received",
    "closed",
)
SAMPLE_TRANSITIONS = {
    "ordered": {"shipped"},
    "shipped": {"delivered"},
    "delivered": {"awaiting_test"},
    "awaiting_test": {"testing"},
    "testing": {"feedback_received"},
    "feedback_received": {"closed"},
}
READ_PERMISSIONS = ("customer_pcw:read", "customer_radar:read", "customer:read_all")
WRITE_PERMISSIONS = ("customer_pcw:write", "customer_radar:write", "customer:admin")
MANAGE_PERMISSIONS = ("customer:admin",)


def _access_customer(db: Session, *, customer_id: int, actor_user_id: int,
                     write: bool = False) -> int:
    if type(actor_user_id) is not int or actor_user_id <= 0:
        raise pcw_errors.customer_not_found()
    roles, permissions = get_live_user_authorization(db, actor_user_id)
    user = {"sub": actor_user_id, "roles": roles, "permissions": permissions}
    try:
        access = require_customer_access(
            db,
            customer_id=customer_id,
            user=user,
            action_permissions=WRITE_PERMISSIONS if write else READ_PERMISSIONS,
            manage_permissions=MANAGE_PERMISSIONS,
        )
    except CustomerAccessDenied:
        raise pcw_errors.customer_not_found() from None
    return int(access.customer_id)


def _primary_owner(db: Session, customer_id: int) -> int | None:
    row = db.query(CustomerAssignment.user_id).filter(
        CustomerAssignment.customer_id == customer_id,
        CustomerAssignment.assignment_role == "primary",
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    ).first()
    return int(row.user_id) if row else None


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _as_datetime(value) -> datetime | None:
    """接受 ISO 字符串/datetime/date，统一转为北京 naive datetime。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return to_beijing_naive(value)
    if isinstance(value, date):
        return datetime.combine(value, time(0, 0))
    return to_beijing_naive(datetime.fromisoformat(str(value)))


def _as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return to_beijing_naive(value).date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


# ── 六类维护 typed_payload 校验（schema-migrations 第 6 节）────────


def _require_keys(payload: Mapping, required: set[str], optional: set[str] = frozenset()) -> None:
    if not isinstance(payload, Mapping):
        raise pcw_errors.bad_request("typed_payload 必须是对象", error_code="PLAN_PAYLOAD_INVALID")
    keys = set(payload) - {"_reschedule_history"}
    missing = required - keys
    extra = keys - required - optional
    if missing or extra:
        raise pcw_errors.bad_request(
            f"typed_payload 键不合法：缺少{sorted(missing)} 多余{sorted(extra)}",
            error_code="PLAN_PAYLOAD_INVALID",
        )


def _validate_typed_payload(plan_type: str, payload: Mapping) -> dict:
    if plan_type not in PLAN_TYPES:
        raise pcw_errors.bad_request("计划类型不合法", error_code="PLAN_TYPE_INVALID")
    data = dict(payload)
    if plan_type == "manual":
        _require_keys(data, {"scheduled_at", "purpose", "channel"})
        try:
            parsed = _as_datetime(data["scheduled_at"])
        except (TypeError, ValueError):
            parsed = None
        if parsed is None:
            raise pcw_errors.bad_request(
                "scheduled_at 不是合法时间", error_code="PLAN_PAYLOAD_INVALID"
            )
    elif plan_type == "birthday":
        # 2/29 必须显式 leap_day_policy（skip/feb28/mar1），缺失或非法都是
        # BIRTHDAY_LEAP_POLICY_REQUIRED；年份未知不推测。
        if data.get("month") == 2 and data.get("day") == 29 and data.get("leap_day_policy") not in {"skip", "feb28", "mar1"}:
            raise pcw_errors.bad_request(
                "2月29日生日必须显式指定闰日策略（skip/feb28/mar1），不排无策略实例",
                error_code="BIRTHDAY_LEAP_POLICY_REQUIRED",
            )
        _require_keys(data, {"contact_id", "month", "day", "local_contact_time", "leap_day_policy"})
        month, day = data["month"], data["day"]
        if type(month) is not int or not 1 <= month <= 12 or type(day) is not int or not 1 <= day <= 31:
            raise pcw_errors.bad_request("生日月日不合法", error_code="PLAN_PAYLOAD_INVALID")
        if data["leap_day_policy"] not in {"skip", "feb28", "mar1"}:
            if month == 2 and day == 29:
                raise pcw_errors.bad_request(
                    "2月29日生日必须显式指定闰日策略",
                    error_code="BIRTHDAY_LEAP_POLICY_REQUIRED",
                )
            raise pcw_errors.bad_request(
                "leap_day_policy 必须为 skip/feb28/mar1", error_code="PLAN_PAYLOAD_INVALID"
            )
    elif plan_type == "holiday":
        _require_keys(
            data,
            {"holiday_code", "calendar_region", "occurrence_local_date", "local_contact_time", "applicability_confirmed"},
        )
        if data["applicability_confirmed"] is not True:
            raise pcw_errors.bad_request(
                "节日计划必须已确认客户适用性",
                error_code="HOLIDAY_APPLICABILITY_REQUIRED",
            )
        try:
            date.fromisoformat(str(data["occurrence_local_date"]))
        except ValueError:
            raise pcw_errors.bad_request(
                "occurrence_local_date 不是合法日期", error_code="PLAN_PAYLOAD_INVALID"
            ) from None
    elif plan_type == "campaign":
        _require_keys(data, {"campaign_id", "campaign_version", "audience_decision_ref"})
    elif plan_type == "shipping":
        _require_keys(data, {"shipment_order_link_ids", "trigger_event_type", "shipment_event_id", "contact_channel"})
        if not isinstance(data["shipment_order_link_ids"], list):
            raise pcw_errors.bad_request(
                "shipment_order_link_ids 必须是数组", error_code="PLAN_PAYLOAD_INVALID"
            )
    elif plan_type == "sample":
        _require_keys(data, {"sample_case_id", "purpose"}, optional={"test_planned_date", "feedback_due_at"})
        has_test = data.get("test_planned_date") is not None
        has_feedback = data.get("feedback_due_at") is not None
        if has_test == has_feedback:
            raise pcw_errors.bad_request(
                "样品计划必须且只能提供 test_planned_date 或 feedback_due_at 之一",
                error_code="PLAN_PAYLOAD_INVALID",
            )
    return data


def _occurrence_key_for(plan: MaintenancePlan, payload: dict) -> str:
    plan_type = plan.plan_type
    if plan_type == "manual":
        return f"plan:{plan.id}:occ:{uuid.uuid4()}"
    if plan_type == "birthday":
        year = _birthday_next_year(payload)
        return f"plan:{plan.id}:bday:{year}"
    if plan_type == "holiday":
        local = date.fromisoformat(str(payload["occurrence_local_date"]))
        return f"plan:{plan.id}:hol:{payload['holiday_code']}:{local.year}"
    if plan_type == "campaign":
        return f"campaign:{payload['campaign_id']}:{plan.customer_id}:{uuid.uuid4()}"
    if plan_type == "shipping":
        # shipping payload 无 purpose 键（schema §6），purpose 位使用 trigger_event_type
        return f"shipment:{payload['shipment_event_id']}:{plan.customer_id}:{payload['trigger_event_type']}"
    # sample：sample_case_id + feedback_round + purpose（schema §6 稳定实例键）
    round_no = int(payload.get("_feedback_round") or 1)
    return f"sample:{payload['sample_case_id']}:round:{round_no}:{payload['purpose']}"


def _birthday_next_year(payload: dict) -> int | None:
    """下一发生年；2/29 无策略或 skip 策略找不到发生年时返回 None（不排）。"""
    month, day = int(payload["month"]), int(payload["day"])
    policy = payload.get("leap_day_policy")
    if month == 2 and day == 29 and policy not in {"skip", "feb28", "mar1"}:
        return None  # 2/29 无策略不排
    today = beijing_today()
    for year in range(today.year, today.year + 9):
        target = _birthday_date(year, month, day, policy)
        if target is not None and target >= today:
            return year
    return None


def _birthday_date(year: int, month: int, day: int, policy: str) -> date | None:
    if month == 2 and day == 29:
        if policy == "skip":
            try:
                return date(year, 2, 29)
            except ValueError:
                return None
        if policy == "feb28":
            return date(year, 2, 28)
        if policy == "mar1":
            return date(year, 3, 1)
        return None
    return date(year, month, day)


def _occurrence_date_for(plan: MaintenancePlan, payload: dict) -> date | None:
    plan_type = plan.plan_type
    if plan_type == "manual":
        return _as_datetime(payload["scheduled_at"]).date()
    if plan_type == "birthday":
        year = _birthday_next_year(payload)
        if year is None:
            return None  # 2/29 无策略（或无发生年）不排实例
        return _birthday_date(
            year, int(payload["month"]), int(payload["day"]), payload["leap_day_policy"]
        )
    if plan_type == "holiday":
        return date.fromisoformat(str(payload["occurrence_local_date"]))
    if plan_type == "sample":
        if payload.get("test_planned_date"):
            return _as_date(payload["test_planned_date"])
        due = _as_datetime(payload["feedback_due_at"])
        return due.date()
    # campaign/shipping：立即安排（当天）
    return beijing_today()


# ── 维护计划 ───────────────────────────────────────────────────


def _plan_dict(plan: MaintenancePlan) -> dict:
    return {
        "id": plan.id,
        "customer_id": plan.customer_id,
        "plan_type": plan.plan_type,
        "title": plan.title,
        "timezone": plan.timezone,
        "typed_payload": plan.typed_payload,
        "evidence_json": plan.evidence_json,
        "status": plan.status,
        "owner_user_id": plan.owner_user_id,
        "plan_version": int(plan.plan_version),
    }


def _occurrence_dict(row: MaintenanceOccurrence) -> dict:
    return {
        "id": row.id,
        "plan_id": row.plan_id,
        "occurrence_key": row.occurrence_key,
        "work_item_id": row.work_item_id,
        "current_action_id": row.current_action_id,
        "occurrence_date": row.occurrence_date.isoformat() if row.occurrence_date else None,
        "local_date": row.local_date.isoformat() if row.local_date else None,
        "status": row.status,
        "occurrence_version": int(row.occurrence_version),
    }


def create_plan(
    db: Session,
    *,
    customer_id: int,
    actor_user_id: int,
    plan_type: str,
    title: str,
    typed_payload: Mapping,
    timezone: str = "Asia/Shanghai",
    evidence_refs: list | None = None,
    owner_user_id: int | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """创建维护计划并生成首个稳定实例 + 事项 + 行动（同一事务）。"""
    logical_id = _access_customer(db, customer_id=customer_id, actor_user_id=actor_user_id, write=True)
    payload = _validate_typed_payload(plan_type, typed_payload)

    def _execute() -> dict:
        now = beijing_now()
        owner = owner_user_id or _primary_owner(db, logical_id)
        plan = MaintenancePlan(
            customer_id=logical_id,
            plan_type=plan_type,
            title=title[:500],
            timezone=timezone,
            typed_payload=payload,
            evidence_json={"refs": list(evidence_refs or [])},
            status="active",
            owner_user_id=owner,
            plan_version=1,
            created_by=actor_user_id,
            created_at=now,
            updated_at=now,
        )
        db.add(plan)
        db.flush()
        if plan_type == "sample":
            case = db.get(SampleCase, payload["sample_case_id"])
            if case is None or int(case.customer_id) != logical_id:
                raise pcw_errors.not_found(
                    "样品事项不存在", error_code="SAMPLE_CASE_NOT_FOUND"
                )
            payload["_feedback_round"] = int(case.feedback_round)
        occurrence = _materialize_occurrence(db, plan=plan, actor_user_id=actor_user_id, owner=owner)
        return {
            "plan": _plan_dict(plan),
            "occurrence": _occurrence_dict(occurrence) if occurrence is not None else None,
        }

    if idempotency_key:
        result, _replayed = run_with_receipt(
            db,
            actor_user_id=actor_user_id,
            operation_scope=f"maintenance_plan:{logical_id}",
            idempotency_key=idempotency_key,
            request_payload={
                "plan_type": plan_type,
                "title": title,
                "typed_payload": {k: v for k, v in payload.items() if not k.startswith("_")},
                "timezone": timezone,
            },
            execute=_execute,
        )
        return result
    return _execute()


def _materialize_occurrence(
    db: Session,
    *,
    plan: MaintenancePlan,
    actor_user_id: int,
    owner: int | None,
) -> MaintenanceOccurrence | None:
    """按稳定键创建实例 + 事项 + 行动；实例键已存在时返回既有（幂等）。

    2/29 无策略等不可排期情形返回 None（不虚构实例日期）。
    """
    payload = dict(plan.typed_payload or {})
    if plan.plan_type in {"manual", "campaign"}:
        # 这两类实例键含 uuid（schema 第 6 节：plan_id+occurrence_uuid），
        # 重物化不得换键重建：计划已有实例时直接复用首个未取消实例。
        existing_rows = (
            db.query(MaintenanceOccurrence)
            .filter(
                MaintenanceOccurrence.plan_id == plan.id,
                MaintenanceOccurrence.status != "cancelled",
            )
            .order_by(MaintenanceOccurrence.id)
            .all()
        )
        if existing_rows:
            return existing_rows[0]
    occ_date = _occurrence_date_for(plan, payload)
    if occ_date is None:
        return None
    occurrence_key = _occurrence_key_for(plan, payload)
    existing = db.query(MaintenanceOccurrence).filter(
        MaintenanceOccurrence.plan_id == plan.id,
        MaintenanceOccurrence.occurrence_key == occurrence_key,
    ).one_or_none()
    if existing is not None:
        return existing
    item = ensure_work_item(
        db,
        customer_id=plan.customer_id,
        business_key=f"maintenance:plan:{plan.id}",
        business_cycle=occurrence_key,
        work_type="maintenance",
        title=plan.title,
        context={"plan_type": plan.plan_type, "plan_id": plan.id},
    )
    action = create_pcw_action(
        db,
        work_item=item,
        owner_user_id=owner,
        action_type="call" if plan.plan_type == "shipping" else "message",
        thread_group="sample" if plan.plan_type == "sample" else "key_account",
        priority="normal",
        reason=f"维护计划「{plan.title}」（{plan.plan_type}）到期待执行。",
        next_action=plan.title,
        business_due_at=datetime.combine(occ_date, time(9, 0)),
        original_due_at=datetime.combine(occ_date, time(9, 0)),
        due_provenance=f"maintenance_{plan.plan_type}",
        source_type="rule",
        policy_version="pcw_maintenance_v1",
    )
    occurrence = MaintenanceOccurrence(
        plan_id=plan.id,
        occurrence_key=occurrence_key,
        work_item_id=item.id,
        current_action_id=action.id,
        occurrence_date=occ_date,
        status="due" if occ_date <= beijing_today() else "planned",
        occurrence_version=1,
        created_at=beijing_now(),
        updated_at=beijing_now(),
    )
    db.add(occurrence)
    db.flush()
    return occurrence


def list_plans(
    db: Session,
    *,
    customer_id: int,
    actor_user_id: int,
    plan_type: str | None = None,
    status: str | None = None,
) -> dict:
    logical_id = _access_customer(db, customer_id=customer_id, actor_user_id=actor_user_id)
    query = db.query(MaintenancePlan).filter(MaintenancePlan.customer_id == logical_id)
    if plan_type:
        query = query.filter(MaintenancePlan.plan_type == plan_type)
    if status:
        query = query.filter(MaintenancePlan.status == status)
    rows = query.order_by(MaintenancePlan.id.desc()).all()
    return {"items": [_plan_dict(row) for row in rows]}


def patch_plan(
    db: Session,
    *,
    plan_id: int,
    actor_user_id: int,
    expected_plan_version: int,
    status: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    plan = db.get(MaintenancePlan, plan_id)
    if plan is None:
        raise pcw_errors.customer_not_found()
    logical_id = _access_customer(db, customer_id=int(plan.customer_id), actor_user_id=actor_user_id, write=True)

    def _execute() -> dict:
        row = db.query(MaintenancePlan).filter(
            MaintenancePlan.id == plan_id,
        ).populate_existing().with_for_update().one()
        if int(row.plan_version) != int(expected_plan_version):
            raise pcw_errors.conflict(
                "计划版本已变化",
                error_code="PLAN_VERSION_CONFLICT",
                details={"current_plan_version": int(row.plan_version)},
            )
        if status is not None:
            allowed = {
                "active": {"paused", "closed"},
                "paused": {"active", "closed"},
                "closed": set(),
            }
            if status != row.status and status not in allowed.get(row.status, set()):
                raise pcw_errors.bad_request(
                    "计划状态转移不合法", error_code="PLAN_TRANSITION_INVALID"
                )
            row.status = status
            if status == "closed":
                now = beijing_now()
                for occ in db.query(MaintenanceOccurrence).filter(
                    MaintenanceOccurrence.plan_id == row.id,
                    MaintenanceOccurrence.status.in_(("planned", "due")),
                ).all():
                    occ.status = "cancelled"
                    occ.occurrence_version = int(occ.occurrence_version) + 1
                    occ.updated_at = now
        row.plan_version = int(row.plan_version) + 1
        row.updated_at = beijing_now()
        db.flush()
        return _plan_dict(row)

    if idempotency_key:
        result, _replayed = run_with_receipt(
            db,
            actor_user_id=actor_user_id,
            operation_scope=f"maintenance_plan_patch:{plan_id}",
            idempotency_key=idempotency_key,
            request_payload={"expected_plan_version": expected_plan_version, "status": status},
            execute=_execute,
        )
        return result
    return _execute()


def reschedule_occurrence(
    db: Session,
    *,
    occurrence_id: int,
    actor_user_id: int,
    expected_plan_version: int,
    expected_occurrence_version: int,
    new_date,
    reason: str,
    expected_action_version: int | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """改约：只更新日期不换实例身份；计划/实例/当前行动原子联动（行动行锁内）。"""
    occurrence = db.get(MaintenanceOccurrence, occurrence_id)
    if occurrence is None:
        raise pcw_errors.customer_not_found()
    plan = db.get(MaintenancePlan, occurrence.plan_id)
    if plan is None:
        raise pcw_errors.customer_not_found()
    _access_customer(db, customer_id=int(plan.customer_id), actor_user_id=actor_user_id, write=True)
    normalized_reason = (reason or "").strip()
    if not normalized_reason:
        raise pcw_errors.bad_request("改约必须填写原因", error_code="RESCHEDULE_REASON_REQUIRED")
    target = _as_date(new_date)
    if target is None:
        raise pcw_errors.bad_request("新日期不合法", error_code="RESCHEDULE_DATE_INVALID")

    def _execute() -> dict:
        occ = db.query(MaintenanceOccurrence).filter(
            MaintenanceOccurrence.id == occurrence_id,
        ).populate_existing().with_for_update().one()
        plan_row = db.query(MaintenancePlan).filter(
            MaintenancePlan.id == occ.plan_id,
        ).populate_existing().with_for_update().one()
        if int(plan_row.plan_version) != int(expected_plan_version):
            raise pcw_errors.conflict(
                "计划版本已变化",
                error_code="PLAN_VERSION_CONFLICT",
                details={"current_plan_version": int(plan_row.plan_version)},
            )
        if int(occ.occurrence_version) != int(expected_occurrence_version):
            raise pcw_errors.conflict(
                "实例版本已变化",
                error_code="OCCURRENCE_VERSION_CONFLICT",
                details={"current_occurrence_version": int(occ.occurrence_version)},
            )
        if occ.status in {"fulfilled", "cancelled"}:
            raise pcw_errors.conflict(
                "维护实例已结束，不能改约", error_code="OCCURRENCE_CLOSED"
            )
        from app.customer.models import CustomerAction

        action = None
        if occ.current_action_id is not None:
            action = db.query(CustomerAction).filter(
                CustomerAction.id == occ.current_action_id,
            ).populate_existing().with_for_update().one_or_none()
        if action is not None and action.status == "done":
            raise pcw_errors.bad_request(
                "已结束任务拒绝改约；请登记完成后创建后续",
                error_code="ACTION_ALREADY_DONE",
            )
        if action is not None and expected_action_version is not None and int(action.row_version) != int(expected_action_version):
            raise pcw_errors.conflict(
                "行动版本已变化",
                error_code="ACTION_VERSION_CONFLICT",
                details={"current_action_version": int(action.row_version)},
            )
        now = beijing_now()
        old_date = occ.occurrence_date
        occ.occurrence_date = target
        occ.status = "due" if target <= beijing_today() else "planned"
        occ.occurrence_version = int(occ.occurrence_version) + 1
        occ.updated_at = now
        action_version = None
        if action is not None and action.status in {"pending", "snoozed"}:
            action.business_due_at = datetime.combine(target, time(9, 0))
            action.row_version = int(action.row_version) + 1
            action.updated_at = now
            action_version = int(action.row_version)
        history = list((plan_row.typed_payload or {}).get("_reschedule_history") or [])
        history.append({
            "from": old_date.isoformat() if old_date else None,
            "to": target.isoformat(),
            "reason": normalized_reason[:500],
            "at": now.isoformat(),
            "by": actor_user_id,
        })
        payload = dict(plan_row.typed_payload or {})
        payload["_reschedule_history"] = history
        plan_row.typed_payload = payload
        plan_row.plan_version = int(plan_row.plan_version) + 1
        plan_row.updated_at = now
        db.flush()
        return {
            "occurrence_id": occ.id,
            "occurrence_version": int(occ.occurrence_version),
            "old_date": old_date.isoformat() if old_date else None,
            "new_date": target.isoformat(),
            "action_id": action.id if action is not None else None,
            "action_version": action_version,
            "original_due_at": _iso(action.original_due_at) if action is not None else None,
        }

    if idempotency_key:
        result, _replayed = run_with_receipt(
            db,
            actor_user_id=actor_user_id,
            operation_scope=f"maintenance_reschedule:{occurrence_id}",
            idempotency_key=idempotency_key,
            request_payload={
                "expected_plan_version": expected_plan_version,
                "expected_occurrence_version": expected_occurrence_version,
                "new_date": target.isoformat(),
                "reason": normalized_reason,
            },
            execute=_execute,
        )
        return result
    return _execute()


def list_calendar(
    db: Session,
    *,
    actor_user_id: int,
    actor_permissions: frozenset | set = frozenset(),
    customer_scope: str = "primary",
    date_from,
    date_to,
) -> dict:
    """按北京时间业务日分组的维护实例日历。"""
    roles, permissions = get_live_user_authorization(db, actor_user_id)
    if customer_scope not in {"primary", "collaborator", "authorized"}:
        raise pcw_errors.bad_request("customer_scope 不合法", error_code="SCOPE_INVALID")
    query = db.query(CustomerAssignment.customer_id).filter(
        CustomerAssignment.user_id == actor_user_id,
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    )
    if customer_scope == "primary":
        query = query.filter(CustomerAssignment.assignment_role == "primary")
    elif customer_scope == "collaborator":
        query = query.filter(CustomerAssignment.assignment_role == "collaborator")
    else:
        query = query.filter(CustomerAssignment.assignment_role.in_(("primary", "collaborator")))
    customer_ids = {int(row.customer_id) for row in query.all()}
    if not customer_ids:
        return {"days": [], "date_from": _iso(date_from), "date_to": _iso(date_to)}
    start = date.fromisoformat(str(date_from)) if date_from else beijing_today()
    end = date.fromisoformat(str(date_to)) if date_to else start + timedelta(days=30)
    rows = (
        db.query(MaintenanceOccurrence, MaintenancePlan)
        .join(MaintenancePlan, MaintenancePlan.id == MaintenanceOccurrence.plan_id)
        .filter(
            MaintenancePlan.customer_id.in_(sorted(customer_ids)),
            MaintenanceOccurrence.occurrence_date >= start,
            MaintenanceOccurrence.occurrence_date <= end,
        )
        .order_by(MaintenanceOccurrence.occurrence_date, MaintenanceOccurrence.id)
        .all()
    )
    days: dict[str, list] = {}
    for occ, plan in rows:
        day_key = occ.occurrence_date.isoformat() if occ.occurrence_date else "unknown"
        days.setdefault(day_key, []).append({
            **_occurrence_dict(occ),
            "plan_type": plan.plan_type,
            "title": plan.title,
            "customer_id": plan.customer_id,
            "owner_user_id": plan.owner_user_id,
            "local_date": _iso(occ.local_date),
        })
    return {
        "days": [{"date": key, "items": items} for key, items in sorted(days.items())],
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
    }


# ── 样品事项 ───────────────────────────────────────────────────


def _sample_dict(case: SampleCase) -> dict:
    return {
        "id": case.id,
        "customer_id": case.customer_id,
        "sample_order_id": case.sample_order_id,
        "sample_item_ids": list(case.sample_item_ids_json or []),
        "shipment_link_ids": list(case.shipment_link_ids_json or []),
        "stage": case.stage,
        "feedback_round": int(case.feedback_round),
        "test_planned_date": _iso(case.test_planned_date),
        "test_actual_date": _iso(case.test_actual_date),
        "feedback_received_at": _iso(case.feedback_received_at),
        "feedback_text": case.feedback_text,
        "work_item_id": case.work_item_id,
        "sample_version": int(case.sample_version),
    }


def _sample_case_or_404(db: Session, case_id: int) -> SampleCase:
    case = db.get(SampleCase, case_id)
    if case is None:
        raise pcw_errors.customer_not_found()
    return case


def create_sample_case(
    db: Session,
    *,
    customer_id: int,
    actor_user_id: int,
    sample_order_id: int,
    sample_item_ids: list[int],
    evidence_refs: list | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """创建样品事项；(order, item_set, round) 唯一，同键返回既有。"""
    logical_id = _access_customer(db, customer_id=customer_id, actor_user_id=actor_user_id, write=True)
    item_ids = sorted({int(item) for item in sample_item_ids})
    if not item_ids:
        raise pcw_errors.bad_request("样品明细必填", error_code="SAMPLE_ITEMS_REQUIRED")
    order = db.query(CustomerOrder).filter(
        CustomerOrder.id == sample_order_id,
        logical_root_predicate(CustomerOrder, "order", logical_id),
    ).one_or_none()
    if order is None:
        raise pcw_errors.customer_not_found()
    items = db.query(CustomerOrderItem).filter(
        CustomerOrderItem.order_id == order.id,
        CustomerOrderItem.id.in_(item_ids),
    ).all()
    if {int(row.id) for row in items} != set(item_ids):
        raise pcw_errors.bad_request(
            "样品明细不属于该订单", error_code="SAMPLE_ITEMS_INVALID"
        )
    order_type = derive_order_type(items)
    if order_type != "sample":
        raise pcw_errors.bad_request(
            "仅样品订单可创建样品事项，未知类型不可强转",
            error_code="SAMPLE_ORDER_REQUIRED",
        )
    item_set_hash = hashlib.sha256(
        json.dumps(item_ids, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    def _execute() -> dict:
        existing = db.query(SampleCase).filter(
            SampleCase.sample_order_id == order.id,
            SampleCase.item_set_hash == item_set_hash,
            SampleCase.feedback_round == 1,
        ).one_or_none()
        if existing is not None:
            return {"case": _sample_dict(existing), "created": False}
        now = beijing_now()
        case = SampleCase(
            customer_id=logical_id,
            sample_order_id=order.id,
            item_set_hash=item_set_hash,
            sample_item_ids_json=item_ids,
            stage="ordered",
            feedback_round=1,
            sample_version=1,
            created_by=actor_user_id,
            created_at=now,
            updated_at=now,
        )
        try:
            with db.begin_nested():
                db.add(case)
                db.flush()
        except IntegrityError:
            winner = db.query(SampleCase).filter(
                SampleCase.sample_order_id == order.id,
                SampleCase.item_set_hash == item_set_hash,
                SampleCase.feedback_round == 1,
            ).one_or_none()
            if winner is not None:
                return {"case": _sample_dict(winner), "created": False}
            raise
        return {"case": _sample_dict(case), "created": True}

    if idempotency_key:
        result, _replayed = run_with_receipt(
            db,
            actor_user_id=actor_user_id,
            operation_scope=f"sample_case:{logical_id}",
            idempotency_key=idempotency_key,
            request_payload={
                "sample_order_id": sample_order_id,
                "item_set_hash": item_set_hash,
                "evidence_refs": list(evidence_refs or []),
            },
            execute=_execute,
        )
        return result
    return _execute()


def patch_sample_case(
    db: Session,
    *,
    case_id: int,
    actor_user_id: int,
    operation: str,
    expected_sample_version: int,
    expected_occurrence_version: int | None = None,
    expected_action_version: int | None = None,
    test_planned_date=None,
    reason: str | None = None,
    evidence_refs: list | None = None,
    feedback_text: str | None = None,
    actual_date=None,
    idempotency_key: str | None = None,
) -> dict:
    """样品阶段流转与改约；非法转移 400，版本不符 409，已结束行动拒绝改约。"""
    case = _sample_case_or_404(db, case_id)
    _access_customer(db, customer_id=int(case.customer_id), actor_user_id=actor_user_id, write=True)
    if operation not in {"reschedule", "start_test", "record_feedback", "close"}:
        raise pcw_errors.bad_request("样品操作不合法", error_code="SAMPLE_OPERATION_INVALID")

    def _execute() -> dict:
        row = db.query(SampleCase).filter(
            SampleCase.id == case_id,
        ).populate_existing().with_for_update().one()
        if int(row.sample_version) != int(expected_sample_version):
            raise pcw_errors.conflict(
                "样品事项版本已变化",
                error_code="SAMPLE_VERSION_CONFLICT",
                details={"current_sample_version": int(row.sample_version)},
            )
        now = beijing_now()
        if operation == "reschedule":
            if row.stage not in {"delivered", "awaiting_test"}:
                raise pcw_errors.bad_request(
                    "当前阶段不允许改约", error_code="SAMPLE_TRANSITION_INVALID"
                )
            if test_planned_date is None or not (reason or "").strip() or not evidence_refs:
                raise pcw_errors.bad_request(
                    "改约必须提供计划日期、原因与证据", error_code="SAMPLE_RESCHEDULE_INVALID"
                )
            target = _as_date(test_planned_date)
            if target is None:
                raise pcw_errors.bad_request(
                    "改约日期不合法", error_code="SAMPLE_RESCHEDULE_INVALID"
                )
            row.test_planned_date = target
            # 维护实例/当前行动联动（若存在则必须携带版本前置）
            linked = db.query(MaintenancePlan).filter(
                MaintenancePlan.plan_type == "sample",
                MaintenancePlan.customer_id == row.customer_id,
            ).all()
            occurrence = None
            for plan in linked:
                payload = dict(plan.typed_payload or {})
                if int(payload.get("sample_case_id") or 0) == int(row.id):
                    # 精确到本样品事项的未结束实例（多实例计划不许改错）
                    occurrence = db.query(MaintenanceOccurrence).filter(
                        MaintenanceOccurrence.plan_id == plan.id,
                        MaintenanceOccurrence.status.in_(("planned", "due")),
                    ).populate_existing().with_for_update().order_by(MaintenanceOccurrence.id.desc()).first()
                    if occurrence is not None:
                        break
            result_occurrence = None
            if occurrence is not None:
                if expected_occurrence_version is None or expected_action_version is None:
                    raise pcw_errors.bad_request(
                        "改约关联维护实例，必须携带 expected_occurrence_version 与 expected_action_version",
                        error_code="OCCURRENCE_VERSION_REQUIRED",
                    )
                if int(occurrence.occurrence_version) != int(expected_occurrence_version):
                    raise pcw_errors.conflict(
                        "维护实例版本已变化",
                        error_code="OCCURRENCE_VERSION_CONFLICT",
                        details={"current_occurrence_version": int(occurrence.occurrence_version)},
                    )
                from app.customer.models import CustomerAction

                action = None
                if occurrence.current_action_id is not None:
                    action = db.query(CustomerAction).filter(
                        CustomerAction.id == occurrence.current_action_id,
                    ).populate_existing().with_for_update().one_or_none()
                if action is not None and action.status == "done":
                    raise pcw_errors.bad_request(
                        "已结束任务拒绝改约；请登记完成后创建后续",
                        error_code="ACTION_ALREADY_DONE",
                    )
                if action is not None:
                    if int(action.row_version) != int(expected_action_version):
                        raise pcw_errors.conflict(
                            "行动版本已变化",
                            error_code="ACTION_VERSION_CONFLICT",
                            details={"current_action_version": int(action.row_version)},
                        )
                    action.business_due_at = datetime.combine(target, time(9, 0))
                    action.row_version = int(action.row_version) + 1
                    action.updated_at = now
                occurrence.occurrence_date = target
                occurrence.occurrence_version = int(occurrence.occurrence_version) + 1
                occurrence.updated_at = now
                result_occurrence = _occurrence_dict(occurrence)
                result_occurrence["business_due_at"] = (
                    datetime.combine(target, time(9, 0)).isoformat()
                )
                result_occurrence["action_version"] = (
                    int(action.row_version) if action is not None else None
                )
            row.sample_version = int(row.sample_version) + 1
            row.updated_at = now
            db.flush()
            result = {"case": _sample_dict(row)}
            if result_occurrence is not None:
                result["occurrence"] = result_occurrence
            return result

        if operation == "start_test":
            if row.stage != "awaiting_test":
                raise pcw_errors.bad_request(
                    "仅待测试阶段可开始测试", error_code="SAMPLE_TRANSITION_INVALID"
                )
            if actual_date is None or not evidence_refs:
                raise pcw_errors.bad_request(
                    "开始测试必须提供实际日期与客户证据", error_code="SAMPLE_START_TEST_INVALID"
                )
            row.test_actual_date = _as_date(actual_date)
            row.stage = "testing"
        elif operation == "record_feedback":
            if row.stage != "testing":
                raise pcw_errors.bad_request(
                    "仅测试中可登记反馈", error_code="SAMPLE_TRANSITION_INVALID"
                )
            if not (feedback_text or "").strip() or actual_date is None:
                raise pcw_errors.bad_request(
                    "登记反馈必须提供内容与日期", error_code="SAMPLE_FEEDBACK_INVALID"
                )
            row.feedback_text = feedback_text.strip()[:2000]
            row.feedback_received_at = now
            row.stage = "feedback_received"
        else:  # close
            if row.stage not in {"feedback_received", "ordered", "shipped", "delivered", "awaiting_test", "testing"}:
                raise pcw_errors.bad_request(
                    "非法关闭", error_code="SAMPLE_TRANSITION_INVALID"
                )
            if row.stage != "feedback_received" and not (reason or "").strip():
                raise pcw_errors.bad_request(
                    "未收到反馈关闭必须提供明确取消依据", error_code="SAMPLE_CLOSE_REASON_REQUIRED"
                )
            row.stage = "closed"
        row.sample_version = int(row.sample_version) + 1
        row.updated_at = now
        db.flush()
        return {"case": _sample_dict(row)}

    if idempotency_key:
        result, _replayed = run_with_receipt(
            db,
            actor_user_id=actor_user_id,
            operation_scope=f"sample_case_patch:{case_id}",
            idempotency_key=idempotency_key,
            request_payload={
                "operation": operation,
                "expected_sample_version": expected_sample_version,
                "test_planned_date": _iso(test_planned_date) if test_planned_date else None,
                "reason": reason,
                "feedback_text": feedback_text,
                "actual_date": _iso(actual_date) if actual_date else None,
            },
            execute=_execute,
        )
        return result
    return _execute()


def sync_sample_logistics(db: Session, *, case_id: int) -> dict:
    """物流事实推进样品阶段：发出/签收来自物流；签收不自动开始测试。

    链路 ordered→shipped→delivered→awaiting_test：任一 shipped_at→shipped；
    任一 delivered_at（未齐）→delivered；全部 delivered_at→awaiting_test。
    testing 及以后不再被物流推进。
    """
    case = _sample_case_or_404(db, case_id)
    if case.stage in {"testing", "feedback_received", "closed"}:
        return {"case": _sample_dict(case), "advanced": False, "reason": "STAGE_LOCKED"}
    link_ids = [int(item) for item in (case.shipment_link_ids_json or [])]
    if not link_ids:
        return {"case": _sample_dict(case), "advanced": False, "reason": "NO_SHIPMENT_LINKS"}
    links = db.query(ShipmentOrderLink).filter(ShipmentOrderLink.id.in_(link_ids)).all()
    shipment_ids = [int(link.shipment_id) for link in links]
    shipments = db.query(ShipmentTracking).filter(
        ShipmentTracking.id.in_(shipment_ids)
    ).all() if shipment_ids else []
    any_shipped = any(row.shipped_at is not None for row in shipments)
    any_delivered = any(row.delivered_at is not None for row in shipments)
    all_delivered = bool(shipments) and all(row.delivered_at is not None for row in shipments)
    advanced = False
    now = beijing_now()
    if all_delivered and case.stage in {"ordered", "shipped", "delivered"}:
        case.stage = "awaiting_test"
        advanced = True
    elif any_delivered and case.stage in {"ordered", "shipped"}:
        case.stage = "delivered"
        advanced = True
    elif any_shipped and case.stage == "ordered":
        case.stage = "shipped"
        advanced = True
    if advanced:
        case.sample_version = int(case.sample_version) + 1
        case.updated_at = now
        db.flush()
    return {"case": _sample_dict(case), "advanced": advanced}


def get_sample_case(db: Session, *, case_id: int, actor_user_id: int) -> dict:
    case = _sample_case_or_404(db, case_id)
    _access_customer(db, customer_id=int(case.customer_id), actor_user_id=actor_user_id)
    return {"case": _sample_dict(case)}


def list_sample_cases(
    db: Session,
    *,
    customer_id: int,
    actor_user_id: int,
    stage: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    logical_id = _access_customer(db, customer_id=customer_id, actor_user_id=actor_user_id)
    query = db.query(SampleCase).filter(SampleCase.customer_id == logical_id)
    if stage:
        query = query.filter(SampleCase.stage == stage)
    total = query.count()
    rows = query.order_by(SampleCase.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [_sample_dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}


# ── 物流订单关联 ───────────────────────────────────────────────


def create_shipment_order_link(
    db: Session,
    *,
    actor_user_id: int,
    shipment_id: int,
    order_id: int,
    order_item_id: int | None = None,
    linked_quantity=None,
    linked_unit: str | None = None,
    link_role: str = "full",
    evidence_refs: list | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """物流运单与订单显式多对多关联；收件人相似绝不是绑定依据。"""
    if not evidence_refs:
        raise pcw_errors.bad_request(
            "关联必须提供确认依据", error_code="LINK_EVIDENCE_REQUIRED"
        )
    shipment = db.get(ShipmentTracking, shipment_id)
    if shipment is None:
        raise pcw_errors.not_found("运单不存在", error_code="SHIPMENT_NOT_FOUND")
    order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).one_or_none()
    if order is None:
        raise pcw_errors.customer_not_found()
    _access_customer(db, customer_id=int(order.customer_id), actor_user_id=actor_user_id, write=True)
    if order_item_id is not None:
        item = db.query(CustomerOrderItem).filter(
            CustomerOrderItem.id == order_item_id,
            CustomerOrderItem.order_id == order.id,
        ).one_or_none()
        if item is None:
            raise pcw_errors.bad_request(
                "明细不属于该订单", error_code="LINK_ITEM_INVALID"
            )
    quantity_str = None
    if linked_quantity is not None:
        try:
            quantity = Decimal(str(linked_quantity))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise pcw_errors.bad_request(
                "关联数量不合法", error_code="LINK_QUANTITY_INVALID"
            ) from exc
        if not quantity.is_finite() or quantity <= 0:
            raise pcw_errors.bad_request(
                "关联数量必须为正", error_code="LINK_QUANTITY_INVALID"
            )
        quantity_str = format(quantity.normalize(), "f")

    def _execute() -> dict:
        existing = db.query(ShipmentOrderLink).filter(
            ShipmentOrderLink.shipment_id == shipment_id,
            ShipmentOrderLink.order_id == order_id,
            ShipmentOrderLink.order_item_id == order_item_id,
            ShipmentOrderLink.link_role == link_role,
        ).one_or_none()
        if existing is not None:
            if (existing.linked_quantity or None) != (quantity_str or None):
                raise pcw_errors.conflict(
                    "同一关联键已有不同数量的关联", error_code="LINK_CONFLICT"
                )
            return {"link_id": existing.id, "created": False}
        if quantity_str is not None:
            # 累计关联数量不得超出订单有效数量（双方已知才校验）
            target_qty = None
            if order_item_id is not None:
                item_row = db.get(CustomerOrderItem, order_item_id)
                target_qty = item_row.quantity if item_row is not None else None
            else:
                totals = db.query(func.sum(CustomerOrderItem.quantity)).filter(
                    CustomerOrderItem.order_id == order.id,
                ).scalar()
                target_qty = totals
            if target_qty is not None:
                linked_rows = db.query(ShipmentOrderLink).filter(
                    ShipmentOrderLink.order_id == order.id,
                    ShipmentOrderLink.order_item_id == order_item_id,
                    ShipmentOrderLink.state == "active",
                ).all()
                already = sum(
                    Decimal(row.linked_quantity)
                    for row in linked_rows
                    if row.linked_quantity
                )
                if already + quantity > Decimal(str(target_qty)):
                    raise pcw_errors.bad_request(
                        "累计关联数量超出订单有效数量",
                        error_code="LINK_QUANTITY_EXCEEDED",
                    )
        now = beijing_now()
        link = ShipmentOrderLink(
            shipment_id=shipment_id,
            order_id=order.id,
            order_item_id=order_item_id,
            linked_quantity=quantity_str,
            linked_unit=linked_unit,
            link_role=link_role,
            evidence_json={"refs": list(evidence_refs or [])},
            state="active",
            link_version=1,
            created_by=actor_user_id,
            created_at=now,
            updated_at=now,
        )
        db.add(link)
        db.flush()
        return {"link_id": link.id, "created": True}

    if idempotency_key:
        result, _replayed = run_with_receipt(
            db,
            actor_user_id=actor_user_id,
            operation_scope=f"shipment_link:{shipment_id}",
            idempotency_key=idempotency_key,
            request_payload={
                "order_id": order_id,
                "order_item_id": order_item_id,
                "linked_quantity": quantity_str,
                "linked_unit": linked_unit,
                "link_role": link_role,
            },
            execute=_execute,
        )
        return result
    return _execute()


# ── 新品/优惠活动 ──────────────────────────────────────────────


def _campaign_dict(campaign: Campaign, *, derived_status: str | None = None) -> dict:
    return {
        "id": campaign.id,
        "title": campaign.title,
        "campaign_type": campaign.campaign_type,
        "product_scope": campaign.product_scope_json,
        "market_scope": campaign.market_scope_json,
        "exclusions": campaign.exclusions_json,
        "content_refs": campaign.content_refs_json,
        "effective_from": _iso(campaign.effective_from),
        "effective_to": _iso(campaign.effective_to),
        "status": derived_status or campaign.status,
        "audience_rule_version": campaign.audience_rule_version,
        "campaign_version": int(campaign.campaign_version),
    }


def _derived_status(campaign: Campaign) -> str:
    if campaign.status == "active" and campaign.effective_to is not None and campaign.effective_to < beijing_now():
        return "expired"
    return campaign.status


def create_campaign(
    db: Session,
    *,
    actor_user_id: int,
    title: str,
    campaign_type: str,
    product_scope: Mapping,
    effective_from,
    effective_to,
    market_scope: Mapping | None = None,
    exclusions: Mapping | None = None,
    content_refs: Mapping | None = None,
    idempotency_key: str | None = None,
) -> dict:
    if campaign_type not in {"new_product", "offer"}:
        raise pcw_errors.bad_request("活动类型不合法", error_code="CAMPAIGN_TYPE_INVALID")

    def _execute() -> dict:
        now = beijing_now()
        campaign = Campaign(
            title=title[:200],
            campaign_type=campaign_type,
            product_scope_json=dict(product_scope or {}),
            market_scope_json=dict(market_scope or {}),
            exclusions_json=dict(exclusions or {}),
            content_refs_json=dict(content_refs or {}),
            effective_from=_as_datetime(effective_from),
            effective_to=_as_datetime(effective_to),
            status="draft",
            audience_rule_version="pcw_campaign_audience_v1",
            campaign_version=1,
            owner_user_id=actor_user_id,
            created_by=actor_user_id,
            created_at=now,
            updated_at=now,
        )
        db.add(campaign)
        db.flush()
        return {"campaign": _campaign_dict(campaign)}

    if idempotency_key:
        result, _replayed = run_with_receipt(
            db,
            actor_user_id=actor_user_id,
            operation_scope="campaign_create",
            idempotency_key=idempotency_key,
            request_payload={
                "title": title,
                "campaign_type": campaign_type,
                "product_scope": dict(product_scope or {}),
                "effective_from": _iso(_as_datetime(effective_from)),
                "effective_to": _iso(_as_datetime(effective_to)),
            },
            execute=_execute,
        )
        return result
    return _execute()


def publish_campaign(
    db: Session,
    *,
    campaign_id: int,
    actor_user_id: int,
    expected_campaign_version: int,
    idempotency_key: str | None = None,
) -> dict:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise pcw_errors.customer_not_found()

    def _execute() -> dict:
        row = db.query(Campaign).filter(
            Campaign.id == campaign_id,
        ).populate_existing().with_for_update().one()
        if int(row.campaign_version) != int(expected_campaign_version):
            raise pcw_errors.conflict(
                "活动版本已变化",
                error_code="CAMPAIGN_VERSION_CONFLICT",
                details={"current_campaign_version": int(row.campaign_version)},
            )
        if row.status != "draft":
            raise pcw_errors.conflict(
                "仅草稿可发布", error_code="CAMPAIGN_TRANSITION_INVALID"
            )
        if not (row.product_scope_json or {}):
            raise pcw_errors.bad_request(
                "活动必须声明适用产品范围", error_code="CAMPAIGN_SCOPE_REQUIRED"
            )
        if row.effective_to is not None and row.effective_to < beijing_now():
            raise pcw_errors.bad_request(
                "活动有效期已过", error_code="CAMPAIGN_EXPIRED"
            )
        row.status = "active"
        row.published_at = beijing_now()
        row.campaign_version = int(row.campaign_version) + 1
        row.updated_at = beijing_now()
        db.flush()
        return {"campaign": _campaign_dict(row)}

    if idempotency_key:
        result, _replayed = run_with_receipt(
            db,
            actor_user_id=actor_user_id,
            operation_scope=f"campaign_publish:{campaign_id}",
            idempotency_key=idempotency_key,
            request_payload={"expected_campaign_version": expected_campaign_version},
            execute=_execute,
        )
        return result
    return _execute()


def transition_campaign(
    db: Session,
    *,
    campaign_id: int,
    actor_user_id: int,
    target_status: str,
    expected_campaign_version: int,
) -> dict:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise pcw_errors.customer_not_found()
    row = db.query(Campaign).filter(
        Campaign.id == campaign_id,
    ).populate_existing().with_for_update().one()
    if int(row.campaign_version) != int(expected_campaign_version):
        raise pcw_errors.conflict(
            "活动版本已变化",
            error_code="CAMPAIGN_VERSION_CONFLICT",
            details={"current_campaign_version": int(row.campaign_version)},
        )
    allowed = {
        "active": {"paused", "closed"},
        "paused": {"active", "closed"},
        "draft": {"closed"},
        "closed": set(),
    }
    if target_status not in allowed.get(row.status, set()):
        raise pcw_errors.bad_request(
            "活动状态转移不合法", error_code="CAMPAIGN_TRANSITION_INVALID"
        )
    row.status = target_status
    row.campaign_version = int(row.campaign_version) + 1
    row.updated_at = beijing_now()
    db.flush()
    return {"campaign": _campaign_dict(row)}


def _preview_snapshot(db: Session, *, campaign: Campaign, actor_user_id: int,
                      actor_permissions) -> tuple[list[dict], list[dict]]:
    can_manage = "customer:admin" in set(actor_permissions) or "super_admin" in set(actor_permissions)
    if can_manage:
        customer_ids = {
            int(row.id)
            for row in db.query(CustomerAccount.id).filter(
                CustomerAccount.record_status == "active"
            ).all()
        }
    else:
        customer_ids = {
            int(row.customer_id)
            for row in db.query(CustomerAssignment.customer_id).filter(
                CustomerAssignment.user_id == actor_user_id,
                CustomerAssignment.assignment_role == "primary",
                CustomerAssignment.assignment_status == "active",
                CustomerAssignment.effective_to.is_(None),
            ).all()
        }
    product_scope = dict(campaign.product_scope_json or {})
    market_scope = dict(campaign.market_scope_json or {})
    exclusions = dict(campaign.exclusions_json or {})
    excluded_ids = {int(item) for item in (exclusions.get("customer_ids") or [])}
    families = set(product_scope.get("product_families") or [])
    markets = set(market_scope.get("countries") or [])
    eligible: list[dict] = []
    excluded: list[dict] = []
    from app.sales_automation.public_pool_service import is_development_denied

    for customer_id in sorted(customer_ids):
        reasons: list[str] = []
        if customer_id in excluded_ids:
            reasons.append("excluded_by_rule")
        if is_development_denied(db, customer_id, "global", None):
            reasons.append("dnc_active")
        projection = db.query(CustomerListProjection).filter(
            CustomerListProjection.customer_id == customer_id,
        ).one_or_none()
        if families and (projection is None or projection.primary_product_family not in families):
            reasons.append("product_mismatch")
        if markets and (projection is None or projection.primary_market not in markets):
            reasons.append("market_mismatch")
        if reasons:
            excluded.append({"customer_id": customer_id, "reasons": reasons})
        else:
            eligible.append({"customer_id": customer_id, "reasons": ["matched"]})
    return eligible, excluded


def preview_campaign(
    db: Session,
    *,
    campaign_id: int,
    actor_user_id: int,
    actor_permissions=frozenset(),
) -> dict:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise pcw_errors.customer_not_found()
    derived = _derived_status(campaign)
    if derived not in {"active"}:
        raise pcw_errors.bad_request(
            "活动未处于生效状态", error_code="CAMPAIGN_NOT_ACTIVE"
        )
    eligible, excluded = _preview_snapshot(
        db, campaign=campaign, actor_user_id=actor_user_id, actor_permissions=actor_permissions
    )
    # sha256(campaign_id+campaign_version+effective范围+actor+规则版本)：
    # 与 api-contracts §4.5/任务约定一致；名单变化由逐客户实时重校验补偿
    preview_version = hashlib.sha256(
        ":".join([
            str(int(campaign.id)),
            str(int(campaign.campaign_version)),
            _iso(campaign.effective_from) or "",
            _iso(campaign.effective_to) or "",
            str(int(actor_user_id)),
            "pcw_campaign_audience_v1",
        ]).encode("utf-8")
    ).hexdigest()
    return {
        "preview_version": preview_version,
        "eligible": eligible,
        "excluded": excluded,
        "expires_at": (beijing_now() + timedelta(hours=2)).isoformat(),
    }


def create_campaign_actions(
    db: Session,
    *,
    campaign_id: int,
    actor_user_id: int,
    preview_version: str,
    customer_ids: list[int],
    actor_permissions=frozenset(),
    idempotency_key: str | None = None,
) -> dict:
    """批量为名单客户建活动任务；逐客户独立事务，结果诚实分列。"""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise pcw_errors.customer_not_found()
    fresh = preview_campaign(
        db,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        actor_permissions=actor_permissions,
    )
    if fresh["preview_version"] != preview_version:
        raise pcw_errors.conflict(
            "预览已过期，请重新预览", error_code="PREVIEW_STALE"
        )
    eligible_ids = {int(item["customer_id"]) for item in fresh["eligible"]}
    excluded_reasons = {
        int(item["customer_id"]): list(item["reasons"])
        for item in fresh["excluded"]
    }
    created: list[int] = []
    existing: list[int] = []
    suppressed: list[dict] = []
    failed: list[dict] = []
    for customer_id in customer_ids:
        cid = int(customer_id)
        if cid not in eligible_ids:
            # 名单成员资格来自本次预览（契约 4.5）；排除项带真实原因，范围外标注 not_in_preview
            reason = ",".join(excluded_reasons.get(cid) or ["not_in_preview"])
            suppressed.append({"customer_id": cid, "reason": reason})
            continue

        def _one(campaign=campaign, cid=cid) -> dict:
            status = _create_one_campaign_action(
                db,
                campaign=campaign,
                customer_id=cid,
                actor_user_id=actor_user_id,
                preview_version=preview_version,
            )
            return {"status": status}

        try:
            with db.begin_nested():
                result, replayed = run_with_receipt(
                    db,
                    actor_user_id=actor_user_id,
                    operation_scope=f"campaign:{campaign_id}:customer:{cid}",
                    idempotency_key=f"campaign-action-{campaign_id}-{cid}-{preview_version[:24]}",
                    request_payload={"campaign_id": campaign_id, "preview_version": preview_version},
                    execute=_one,
                )
            status = result.get("status")
            if replayed or status == "existing":
                existing.append(cid)
            elif status == "created":
                created.append(cid)
            else:
                suppressed.append({"customer_id": cid, "reason": status})
        except pcw_errors.PcwError as exc:  # 单客户失败隔离，批量不部分假成功
            logger.warning(
                "pcw campaign action failed customer=%s error=%s", cid, exc,
                exc_info=True,
            )
            print(f"[pcw-campaign] customer={cid} failed: {exc}", flush=True)
            failed.append({"customer_id": cid, "error_code": exc.error_code})
        except Exception as exc:  # 单客户失败隔离，批量不部分假成功
            logger.warning(
                "pcw campaign action failed customer=%s error=%s", cid, exc,
                exc_info=True,
            )
            print(f"[pcw-campaign] customer={cid} failed: {exc}", flush=True)
            failed.append({"customer_id": cid, "error_code": type(exc).__name__})
    db.flush()
    return {
        "created": created,
        "existing": existing,
        "suppressed": suppressed,
        "failed": failed,
    }


def _create_one_campaign_action(
    db: Session,
    *,
    campaign: Campaign,
    customer_id: int,
    actor_user_id: int,
    preview_version: str,
) -> str:
    from app.sales_automation.public_pool_service import is_development_denied

    if _derived_status(campaign) != "active":
        return "campaign_not_active"
    # 实时重校验受众资格与 DNC：新增限制/排除抑制本次触达，不假成功
    product_scope = dict(campaign.product_scope_json or {})
    market_scope = dict(campaign.market_scope_json or {})
    exclusions = dict(campaign.exclusions_json or {})
    if customer_id in {int(item) for item in (exclusions.get("customer_ids") or [])}:
        return "excluded_by_rule"
    if is_development_denied(db, customer_id, "global", None):
        return "dnc_active"
    families = set(product_scope.get("product_families") or [])
    markets = set(market_scope.get("countries") or [])
    projection = db.query(CustomerListProjection).filter(
        CustomerListProjection.customer_id == customer_id,
    ).one_or_none()
    if families and (projection is None or projection.primary_product_family not in families):
        return "product_mismatch"
    if markets and (projection is None or projection.primary_market not in markets):
        return "market_mismatch"
    payload = {
        "campaign_id": campaign.id,
        "campaign_version": int(campaign.campaign_version),
        "audience_decision_ref": preview_version,
        "_feedback_round": 1,
    }
    plan = MaintenancePlan(
        customer_id=customer_id,
        plan_type="campaign",
        title=f"活动触达：{campaign.title}"[:500],
        timezone="Asia/Shanghai",
        typed_payload={k: v for k, v in payload.items() if not k.startswith("_")},
        evidence_json={"refs": [{"type": "campaign", "id": campaign.id}]},
        status="active",
        owner_user_id=_primary_owner(db, customer_id),
        plan_version=1,
        created_by=actor_user_id,
        created_at=beijing_now(),
        updated_at=beijing_now(),
    )
    db.add(plan)
    db.flush()
    occurrence = _materialize_occurrence(
        db,
        plan=plan,
        actor_user_id=actor_user_id,
        owner=plan.owner_user_id,
    )
    return "created" if occurrence is not None else "existing"


def list_campaigns(db: Session, *, actor_user_id: int, actor_permissions=frozenset()) -> dict:
    """管理员见全部（含草稿）；业务员仅见 active/paused/closed 的已发布活动。"""
    query = db.query(Campaign)
    if "customer:admin" not in set(actor_permissions) and "super_admin" not in set(actor_permissions):
        query = query.filter(Campaign.status.in_(("active", "paused", "closed")))
    rows = query.order_by(Campaign.id.desc()).all()
    return {"items": [_campaign_dict(row, derived_status=_derived_status(row)) for row in rows]}


def get_campaign(db: Session, *, campaign_id: int, actor_user_id: int) -> dict:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise pcw_errors.customer_not_found()
    return {"campaign": _campaign_dict(campaign, derived_status=_derived_status(campaign))}


def patch_campaign_draft(db: Session, *, campaign_id: int, actor_user_id: int, payload: Mapping) -> dict:
    """仅 draft 可改名单规则；生效后只能走发布/状态转移。"""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise pcw_errors.customer_not_found()
    row = db.query(Campaign).filter(
        Campaign.id == campaign_id,
    ).populate_existing().with_for_update().one()
    if row.status != "draft":
        raise pcw_errors.conflict(
            "仅草稿可修改名单规则", error_code="CAMPAIGN_TRANSITION_INVALID"
        )
    expected = payload.get("expected_campaign_version")
    if expected is None or int(row.campaign_version) != int(expected):
        raise pcw_errors.conflict(
            "活动版本已变化",
            error_code="CAMPAIGN_VERSION_CONFLICT",
            details={"current_campaign_version": int(row.campaign_version)},
        )
    allowed_fields = {
        "title": "title",
        "product_scope": "product_scope_json",
        "market_scope": "market_scope_json",
        "exclusions": "exclusions_json",
        "content_refs": "content_refs_json",
        "effective_from": "effective_from",
        "effective_to": "effective_to",
    }
    changed = False
    for key, column in allowed_fields.items():
        if key not in payload:
            continue
        value = payload[key]
        if key in {"effective_from", "effective_to"}:
            value = _as_datetime(value)
        elif key == "title":
            value = str(value)[:200]
        elif value is not None:
            value = dict(value)
        setattr(row, column, value)
        changed = True
    if not changed:
        raise pcw_errors.bad_request("没有可更新字段", error_code="CAMPAIGN_PATCH_EMPTY")
    row.campaign_version = int(row.campaign_version) + 1
    row.updated_at = beijing_now()
    db.flush()
    return {"campaign": _campaign_dict(row)}
