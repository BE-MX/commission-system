"""私海客户工作台（PCW）HTTP 路由。

契约：docs/requirements/private-customer-workbench-prototype/api-contracts.md。
薄路由：参数校验 → 服务层 → ok() 信封；业务错误统一 PcwError（main.py 已注册处理器）。
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok
from app.customer import pcw_errors
from app.customer.access_service import CustomerAccessDenied
from app.customer.pcw_schemas import (
    ActionCreate,
    BindingGovernanceUpdate,
    ConversationBindingCreate,
    EvaluationRunCreate,
    MonitorEventDecisionCreate,
    MonitorSubscriptionCreate,
    MonitorSubscriptionPatch,
    PrivateNoteCreate,
    ProfileRevisionCreate,
    SuggestionDecisionCreate,
)

router = APIRouter()

PCW_READ = ("customer_pcw:read", "customer_radar:read", "customer:read_all")
PCW_WRITE = ("customer_pcw:write", "customer_radar:write", "customer:admin")
PROFILE_WRITE = ("customer_profile:write", "customer:admin")


def _user_id(user: dict) -> int:
    try:
        value = int(user["sub"])
    except (KeyError, TypeError, ValueError):
        raise pcw_errors.forbidden("Token格式错误", error_code="TOKEN_INVALID") from None
    return value


def _perms(user: dict) -> frozenset[str]:
    return frozenset(set(user.get("permissions") or []) | set(user.get("roles") or []))


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except CustomerAccessDenied as exc:
        raise pcw_errors.customer_not_found() from exc


def _access_customer(db: Session, *, customer_id: int, user: dict, write: bool = False) -> int:
    """客户域鉴权 + 逻辑客户解析；失权/不存在一律 404，不泄漏存在性。"""
    from app.customer.access_service import require_customer_access

    action_permissions = (
        ("customer_pcw:write", "customer_radar:write", "customer:admin")
        if write
        else ("customer_pcw:read", "customer_radar:read", "customer:read", "customer:read_all")
    )
    try:
        access = require_customer_access(
            db,
            customer_id=customer_id,
            user=user,
            action_permissions=action_permissions,
            manage_permissions=("customer:admin",),
        )
    except CustomerAccessDenied as exc:
        raise pcw_errors.customer_not_found() from exc
    return int(access.customer_id)


# ── 工作台概览与每日评估 ──────────────────────────────────────────


@router.get("/workbench/overview")
def workbench_overview(
    customer_scope: str = Query("primary", pattern="^(primary|collaborator|authorized)$"),
    action_scope: str = Query("mine", pattern="^(mine|visible)$"),
    on_date: date | None = Query(None),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_overview_service import get_workbench_overview

    return ok(_call(
        get_workbench_overview,
        db,
        actor_user_id=_user_id(user),
        actor_permissions=_perms(user),
        customer_scope=customer_scope,
        action_scope=action_scope,
        on_date=on_date,
    ))


@router.post("/evaluation-runs")
def create_evaluation_run(
    payload: EvaluationRunCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("customer:admin")),
):
    from app.customer.pcw_evaluation_service import run_daily_evaluation

    def _execute() -> dict:
        run = _call(
            run_daily_evaluation,
            db,
            rule_version=payload.rule_version,
            run_kind=payload.run_kind,
            triggered_by=_user_id(user),
            dry_run=payload.dry_run,
            customer_ids=payload.customer_ids,
        )
        return {
            "run_uid": run.run_uid,
            "status": run.status,
            "business_date": run.business_date.isoformat(),
            "expected_count": run.expected_count,
            "rule_completed": run.rule_completed,
            "rule_failed": run.rule_failed,
        }

    if idempotency_key:
        from app.customer.pcw_idempotency import run_with_receipt

        result, _replayed = run_with_receipt(
            db,
            actor_user_id=_user_id(user),
            operation_scope="evaluation_runs",
            idempotency_key=idempotency_key,
            request_payload=payload.model_dump(mode="json"),
            execute=_execute,
        )
    else:
        result = _execute()
    db.commit()
    return JSONResponse(status_code=202, content=ok(result))


@router.get("/evaluation-runs/{run_uid}")
def get_evaluation_run(
    run_uid: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_evaluation_service import get_evaluation_run

    return ok(_call(
        get_evaluation_run, db, run_uid,
        actor_user_id=_user_id(user),
        actor_permissions=_perms(user),
    ))


# ── 行动创建（事项+轮次） ───────────────────────────────────────


@router.post("/customers/{customer_id}/actions")
def create_customer_action(
    customer_id: int,
    payload: ActionCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_WRITE)),
):
    from app.customer.pcw_workitem_service import create_pcw_action, ensure_work_item

    actor_user_id = _user_id(user)
    logical_customer_id = _access_customer(db, customer_id=customer_id, user=user, write=True)

    def _execute() -> dict:
        item = ensure_work_item(
            db,
            customer_id=logical_customer_id,
            business_key=payload.work_item_business_key,
            business_cycle=payload.work_item_business_cycle,
            work_type=payload.work_type,
            title=payload.title,
        )
        action = create_pcw_action(
            db,
            work_item=item,
            owner_user_id=actor_user_id,
            action_type=payload.action_type,
            thread_group=payload.thread_group,
            priority=payload.priority,
            reason=payload.reason,
            next_action=payload.next_action,
            channel=payload.channel,
            contact_id=payload.contact_id,
            opportunity_id=payload.opportunity_id,
            business_due_at=payload.business_due_at,
            original_due_at=payload.original_due_at,
            due_provenance=payload.due_provenance,
            suggested_message=payload.suggested_message,
            source_event_ids=payload.source_event_ids,
            evidence_fact_ids=payload.evidence_fact_ids,
            source_type="manual",
        )
        return {
            "action_id": action.id,
            "action_version": action.row_version,
            "work_item_id": item.id,
            "work_item_version": item.row_version,
            "action_round": action.action_round,
            "status": action.status,
        }

    if idempotency_key:
        from app.customer.pcw_idempotency import run_with_receipt

        result, _replayed = run_with_receipt(
            db,
            actor_user_id=actor_user_id,
            operation_scope=f"create_action:{customer_id}",
            idempotency_key=idempotency_key,
            request_payload=payload.model_dump(mode="json"),
            execute=_execute,
        )
    else:
        result = _execute()
    db.commit()
    return ok(result)


# ── 档案修订与建议审核 ──────────────────────────────────────────


@router.post("/customers/{customer_id}/profile-revisions")
def create_profile_revision(
    customer_id: int,
    payload: ProfileRevisionCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PROFILE_WRITE)),
):
    from app.customer.pcw_profile_service import create_profile_revision as service

    result = _call(
        service,
        db,
        customer_id=customer_id,
        actor_user_id=_user_id(user),
        actor_user=user,
        expected_profile_version_id=payload.expected_profile_version_id,
        expected_profile_input_seq=payload.expected_profile_input_seq,
        field_key=payload.field_key,
        value_type=payload.value_type,
        value=payload.value,
        reason=payload.reason,
        target_fact_id=payload.target_fact_id,
        evidence_refs=payload.evidence_refs,
        supersedes_annotation_id=payload.supersedes_annotation_id,
        idempotency_key=idempotency_key,
    )
    db.commit()
    return ok(result)


@router.get("/customers/{customer_id}/profile-revisions")
def list_profile_revisions(
    customer_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_profile_service import list_profile_revisions as service

    return ok(_call(
        service, db,
        customer_id=customer_id,
        actor_user_id=_user_id(user),
        page=page,
        page_size=page_size,
    ))


@router.get("/customers/{customer_id}/profile-suggestions")
def list_profile_suggestions(
    customer_id: int,
    status: str | None = Query(None, pattern="^(pending|accepted|rejected|deferred|stale)$"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_profile_service import list_profile_suggestions as service

    return ok(_call(
        service, db,
        customer_id=customer_id,
        actor_user_id=_user_id(user),
        actor_permissions=_perms(user),
        status=status,
    ))


@router.post("/profile-suggestions/{review_id}/decisions")
def decide_profile_suggestion(
    review_id: int,
    payload: SuggestionDecisionCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PROFILE_WRITE)),
):
    from app.customer.pcw_profile_service import decide_suggestion

    result = _call(
        decide_suggestion,
        db,
        review_id=review_id,
        actor_user_id=_user_id(user),
        actor_user=user,
        operation=payload.operation,
        expected_suggestion_version=payload.expected_suggestion_version,
        expected_profile_version_id=payload.expected_profile_version_id,
        expected_profile_input_seq=payload.expected_profile_input_seq,
        value=payload.value,
        reason=payload.reason,
        defer_until=payload.defer_until,
        idempotency_key=idempotency_key,
    )
    db.commit()
    return ok(result)


@router.post("/customers/{customer_id}/notes")
def create_private_note(
    customer_id: int,
    payload: PrivateNoteCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_WRITE)),
):
    from app.customer.pcw_profile_service import create_private_note as service

    result = _call(
        service, db,
        customer_id=customer_id,
        actor_user_id=_user_id(user),
        text=payload.text,
        idempotency_key=idempotency_key,
    )
    db.commit()
    return ok(result)


@router.get("/customers/{customer_id}/notes")
def list_private_notes(
    customer_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_profile_service import list_private_notes as service

    return ok(_call(
        service, db,
        customer_id=customer_id,
        actor_user_id=_user_id(user),
    ))


# ── 会话绑定与分析 ─────────────────────────────────────────────


@router.get("/conversation-bindings/pending")
def list_pending_bindings(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_conversation_service import list_pending_bindings as service

    return ok(_call(
        service, db,
        actor_user_id=_user_id(user),
        actor_permissions=_perms(user),
        page=page,
        page_size=page_size,
    ))


@router.post("/conversation-bindings")
def create_conversation_binding(
    payload: ConversationBindingCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_WRITE)),
):
    from app.customer.pcw_conversation_service import create_binding

    result = _call(
        create_binding, db,
        actor_user_id=_user_id(user),
        actor_permissions=_perms(user),
        source_system=payload.source_system,
        source_account_key=payload.source_account_key,
        source_conversation_id=payload.source_conversation_id,
        customer_id=payload.customer_id,
        contact_id=payload.contact_id,
        expected_binding_version=payload.expected_binding_version,
        evidence_refs=payload.evidence_refs,
        share_scope=payload.share_scope,
        idempotency_key=idempotency_key,
    )
    db.commit()
    return ok(result)


@router.post("/conversation-bindings/{binding_id}/rebind")
def rebind_conversation(
    binding_id: int,
    payload: BindingGovernanceUpdate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("customer:admin")),
):
    from app.customer.pcw_conversation_service import rebind

    result = _call(
        rebind, db,
        binding_id=binding_id,
        actor_user_id=_user_id(user),
        can_manage=True,
        new_customer_id=payload.new_customer_id,
        reason=payload.reason,
        idempotency_key=idempotency_key,
    )
    db.commit()
    return ok(result)


@router.post("/conversation-bindings/{binding_id}/unbind")
def unbind_conversation(
    binding_id: int,
    payload: BindingGovernanceUpdate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("customer:admin")),
):
    from app.customer.pcw_conversation_service import unbind

    result = _call(
        unbind, db,
        binding_id=binding_id,
        actor_user_id=_user_id(user),
        can_manage=True,
        reason=payload.reason,
        idempotency_key=idempotency_key,
    )
    db.commit()
    return ok(result)


@router.get("/customers/{customer_id}/conversations")
def list_customer_conversations(
    customer_id: int,
    channel: str | None = Query(None, max_length=24),
    contact_id: int | None = Query(None, gt=0),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_conversation_service import list_conversations

    return ok(_call(
        list_conversations, db,
        customer_id=customer_id,
        actor_user_id=_user_id(user),
        channel=channel,
        contact_id=contact_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    ))


@router.get("/conversations/{conversation_id}/messages")
def list_conversation_messages(
    conversation_id: int,
    cursor: str | None = Query(None, max_length=128),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_conversation_service import list_messages

    return ok(_call(
        list_messages, db,
        conversation_id=conversation_id,
        actor_user_id=_user_id(user),
        actor_permissions=_perms(user),
        cursor=cursor,
        limit=limit,
    ))


@router.post("/conversations/{conversation_id}/analysis-jobs")
def create_analysis_job(
    conversation_id: int,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    run_inline: bool = Query(False),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_WRITE)),
):
    from app.customer.pcw_conversation_service import create_analysis_job

    result = _call(
        create_analysis_job, db,
        conversation_id=conversation_id,
        actor_user_id=_user_id(user),
        actor_permissions=_perms(user),
        idempotency_key=idempotency_key,
        run_inline=run_inline,
    )
    db.commit()
    return JSONResponse(status_code=202, content=ok(result))


@router.get("/analysis-jobs/{job_id}")
def get_analysis_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_conversation_service import get_analysis_job

    return ok(_call(
        get_analysis_job, db,
        job_id=job_id,
        actor_user_id=_user_id(user),
        actor_permissions=_perms(user),
    ))


# ── 订单统计与复购窗口 ─────────────────────────────────────────


@router.get("/customers/{customer_id}/orders")
def list_customer_orders(
    customer_id: int,
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    order_type: str | None = Query(None, pattern="^(sample|bulk|mixed|unknown)$"),
    status: str | None = Query(None, max_length=32),
    product_family: str | None = Query(None, max_length=128),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_order_service import list_customer_orders

    return ok(_call(
        list_customer_orders, db,
        customer_id=customer_id,
        actor_user_id=_user_id(user),
        date_from=date_from,
        date_to=date_to,
        order_type=order_type,
        status=status,
        product_family=product_family,
        page=page,
        page_size=page_size,
    ))


@router.get("/customers/{customer_id}/orders/{order_id}")
def get_customer_order(
    customer_id: int,
    order_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_order_service import get_order_detail

    return ok(_call(
        get_order_detail, db,
        customer_id=customer_id,
        order_id=order_id,
        actor_user_id=_user_id(user),
    ))


@router.get("/customers/{customer_id}/order-analytics")
def get_order_analytics(
    customer_id: int,
    dimension: str = Query(..., pattern="^(product_family|model|color|length)$"),
    measure: str = Query(..., pattern="^(amount|quantity|order_coverage)$"),
    currency: str | None = Query(None, max_length=8),
    unit: str | None = Query(None, max_length=32),
    product_family: str | None = Query(None, max_length=128),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_order_service import get_order_analytics

    return ok(_call(
        get_order_analytics, db,
        customer_id=customer_id,
        actor_user_id=_user_id(user),
        dimension=dimension,
        measure=measure,
        currency=currency,
        unit=unit,
        product_family=product_family,
        date_from=date_from,
        date_to=date_to,
    ))


@router.get("/customers/{customer_id}/reorder-windows")
def get_reorder_windows(
    customer_id: int,
    state: str | None = Query(None, pattern="^(open|covered|superseded|closed)$"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_order_service import get_reorder_windows

    return ok(_call(
        get_reorder_windows, db,
        customer_id=customer_id,
        actor_user_id=_user_id(user),
        state=state,
    ))


# ── 监控订阅与事件 ─────────────────────────────────────────────


@router.get("/customers/{customer_id}/monitor-subscriptions")
def list_monitor_subscriptions(
    customer_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_monitor_service import list_subscriptions

    return ok(_call(
        list_subscriptions, db,
        customer_id=customer_id,
        actor_user_id=_user_id(user),
    ))


@router.post("/customers/{customer_id}/monitor-subscriptions")
def create_monitor_subscription(
    customer_id: int,
    payload: MonitorSubscriptionCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_WRITE)),
):
    from app.customer.pcw_monitor_service import create_subscription

    result = _call(
        create_subscription, db,
        customer_id=customer_id,
        actor_user_id=_user_id(user),
        channel=payload.channel,
        url=payload.url,
        interval_days=payload.interval_days,
        idempotency_key=idempotency_key,
    )
    db.commit()
    return ok(result)


@router.patch("/monitor-subscriptions/{subscription_id}")
def patch_monitor_subscription(
    subscription_id: int,
    payload: MonitorSubscriptionPatch,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_WRITE)),
):
    from app.customer.pcw_monitor_service import patch_subscription

    result = _call(
        patch_subscription, db,
        subscription_id=subscription_id,
        actor_user_id=_user_id(user),
        expected_subscription_version=payload.expected_subscription_version,
        enabled=payload.enabled,
        interval_days=payload.interval_days,
        idempotency_key=idempotency_key,
    )
    db.commit()
    return ok(result)


@router.post("/monitor-subscriptions/{subscription_id}/runs")
def run_monitor_subscription(
    subscription_id: int,
    force: bool = Query(False),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_WRITE)),
):
    from app.customer.pcw_monitor_service import run_subscription

    result = _call(
        run_subscription, db,
        subscription_id=subscription_id,
        actor_user_id=_user_id(user),
        force=force,
    )
    db.commit()
    return ok(result)


@router.get("/customers/{customer_id}/monitor-events")
def list_monitor_events(
    customer_id: int,
    status: str | None = Query(None, pattern="^(pending|confirmed|ignored)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_monitor_service import list_events

    return ok(_call(
        list_events, db,
        customer_id=customer_id,
        actor_user_id=_user_id(user),
        status=status,
        page=page,
        page_size=page_size,
    ))


@router.post("/monitor-events/{event_id}/decisions")
def decide_monitor_event(
    event_id: int,
    payload: MonitorEventDecisionCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_WRITE)),
):
    from app.customer.pcw_monitor_service import decide_event

    result = _call(
        decide_event, db,
        event_id=event_id,
        actor_user_id=_user_id(user),
        operation=payload.operation,
        expected_event_version=payload.expected_event_version,
        reason=payload.reason,
        idempotency_key=idempotency_key,
    )
    db.commit()
    return ok(result)
