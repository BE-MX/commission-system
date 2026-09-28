"""PCW-06 维护日历/样品/物流关联/活动 HTTP 路由。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok
from app.customer import pcw_errors
from app.customer.access_service import CustomerAccessDenied
from app.customer.pcw_schemas import (
    CampaignActionsCreate,
    CampaignCreate,
    CampaignTransitionRequest,
    CampaignVersionRequest,
    MaintenancePlanCreate,
    MaintenancePlanPatch,
    SampleCaseCreate,
    SampleCasePatch,
    ShipmentOrderLinkCreate,
)

router = APIRouter()

PCW_READ = ("customer_pcw:read", "customer_radar:read", "customer:read_all")
PCW_WRITE = ("customer_pcw:write", "customer_radar:write", "customer:admin")
CAMPAIGN_ADMIN = ("customer_campaign:admin", "customer:admin")


def _user_id(user: dict) -> int:
    try:
        return int(user["sub"])
    except (KeyError, TypeError, ValueError):
        raise pcw_errors.forbidden("Token格式错误", error_code="TOKEN_INVALID") from None


def _perms(user: dict) -> frozenset[str]:
    return frozenset(set(user.get("permissions") or []) | set(user.get("roles") or []))


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except CustomerAccessDenied as exc:
        raise pcw_errors.customer_not_found() from exc


# ── 维护计划与日历 ─────────────────────────────────────────────


@router.get("/customers/{customer_id}/maintenance-plans")
def list_maintenance_plans(
    customer_id: int,
    plan_type: str | None = Query(None, max_length=16),
    status: str | None = Query(None, max_length=16),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_maintenance_service import list_plans

    return ok(_call(
        list_plans, db,
        customer_id=customer_id,
        actor_user_id=_user_id(user),
        plan_type=plan_type,
        status=status,
    ))


@router.post("/customers/{customer_id}/maintenance-plans")
def create_maintenance_plan(
    customer_id: int,
    payload: MaintenancePlanCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_WRITE)),
):
    from app.customer.pcw_maintenance_service import create_plan

    result = _call(
        create_plan, db,
        customer_id=customer_id,
        actor_user_id=_user_id(user),
        plan_type=payload.plan_type,
        title=payload.title,
        typed_payload=payload.typed_payload,
        timezone=payload.timezone,
        evidence_refs=payload.evidence_refs,
        owner_user_id=payload.owner_user_id,
        idempotency_key=idempotency_key,
    )
    db.commit()
    return ok(result)


@router.patch("/maintenance-plans/{plan_id}")
def patch_maintenance_plan(
    plan_id: int,
    payload: MaintenancePlanPatch,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_WRITE)),
):
    """状态修改与实例改约共用入口；改约与当前行动更新同事务（api-contracts §3/4.5）。"""
    from app.customer.pcw_maintenance_service import patch_plan, reschedule_occurrence

    if payload.occurrence_id is not None:
        if payload.occurrence_date is None or payload.expected_occurrence_version is None:
            raise pcw_errors.bad_request(
                "实例改约需要 occurrence_date 与 expected_occurrence_version",
                error_code="OCCURRENCE_VERSION_REQUIRED",
            )
        result = _call(
            reschedule_occurrence, db,
            occurrence_id=payload.occurrence_id,
            actor_user_id=_user_id(user),
            expected_plan_version=payload.expected_plan_version,
            expected_occurrence_version=payload.expected_occurrence_version,
            expected_action_version=payload.expected_action_version,
            new_date=payload.occurrence_date,
            reason=payload.reason or "",
            idempotency_key=idempotency_key,
        )
    else:
        result = _call(
            patch_plan, db,
            plan_id=plan_id,
            actor_user_id=_user_id(user),
            expected_plan_version=payload.expected_plan_version,
            status=payload.status,
            idempotency_key=idempotency_key,
        )
    db.commit()
    return ok(result)


@router.get("/maintenance-calendar")
def maintenance_calendar(
    customer_scope: str = Query("primary", pattern="^(primary|collaborator|authorized)$"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_maintenance_service import list_calendar

    return ok(_call(
        list_calendar, db,
        actor_user_id=_user_id(user),
        actor_permissions=_perms(user),
        customer_scope=customer_scope,
        date_from=date_from,
        date_to=date_to,
    ))


# ── 样品事项 ───────────────────────────────────────────────────


@router.get("/customers/{customer_id}/sample-cases")
def list_sample_cases(
    customer_id: int,
    stage: str | None = Query(None, max_length=24),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_maintenance_service import list_sample_cases

    return ok(_call(
        list_sample_cases, db,
        customer_id=customer_id,
        actor_user_id=_user_id(user),
        stage=stage,
        page=page,
        page_size=page_size,
    ))


@router.post("/customers/{customer_id}/sample-cases")
def create_sample_case(
    customer_id: int,
    payload: SampleCaseCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_WRITE)),
):
    from app.customer.pcw_maintenance_service import create_sample_case as service

    result = _call(
        service, db,
        customer_id=customer_id,
        actor_user_id=_user_id(user),
        sample_order_id=payload.sample_order_id,
        sample_item_ids=payload.sample_item_ids,
        evidence_refs=payload.evidence_refs,
        idempotency_key=idempotency_key,
    )
    db.commit()
    return ok(result)


@router.get("/sample-cases/{case_id}")
def get_sample_case(
    case_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_maintenance_service import get_sample_case as service

    return ok(_call(service, db, case_id=case_id, actor_user_id=_user_id(user)))


@router.patch("/sample-cases/{case_id}")
def patch_sample_case(
    case_id: int,
    payload: SampleCasePatch,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_WRITE)),
):
    from app.customer.pcw_maintenance_service import patch_sample_case as service

    result = _call(
        service, db,
        case_id=case_id,
        actor_user_id=_user_id(user),
        operation=payload.operation,
        expected_sample_version=payload.expected_sample_version,
        expected_occurrence_version=payload.expected_occurrence_version,
        expected_action_version=payload.expected_action_version,
        test_planned_date=payload.test_planned_date,
        reason=payload.reason,
        evidence_refs=payload.evidence_refs,
        feedback_text=payload.feedback_text,
        actual_date=payload.actual_date,
        idempotency_key=idempotency_key,
    )
    db.commit()
    return ok(result)


# ── 物流订单关联 ───────────────────────────────────────────────


@router.post("/shipment-order-links")
def create_shipment_order_link(
    payload: ShipmentOrderLinkCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_WRITE)),
):
    from app.customer.pcw_maintenance_service import create_shipment_order_link as service

    result = _call(
        service, db,
        actor_user_id=_user_id(user),
        shipment_id=payload.shipment_id,
        order_id=payload.order_id,
        order_item_id=payload.order_item_id,
        linked_quantity=payload.linked_quantity,
        linked_unit=payload.linked_unit,
        link_role=payload.link_role,
        evidence_refs=payload.evidence_refs,
        idempotency_key=idempotency_key,
    )
    db.commit()
    return ok(result)


# ── 新品/优惠活动 ──────────────────────────────────────────────


@router.get("/campaigns")
def list_campaigns(
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_maintenance_service import list_campaigns

    return ok(list_campaigns(db, actor_user_id=_user_id(user), actor_permissions=_perms(user)))


@router.post("/campaigns")
def create_campaign(
    payload: CampaignCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission(*CAMPAIGN_ADMIN)),
):
    from app.customer.pcw_maintenance_service import create_campaign as service

    result = _call(
        service, db,
        actor_user_id=_user_id(user),
        title=payload.title,
        campaign_type=payload.campaign_type,
        product_scope=payload.product_scope,
        market_scope=payload.market_scope,
        exclusions=payload.exclusions,
        content_refs=payload.content_refs,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        idempotency_key=idempotency_key,
    )
    db.commit()
    return ok(result)


@router.get("/campaigns/{campaign_id}")
def get_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_maintenance_service import get_campaign

    return ok(get_campaign(db, campaign_id=campaign_id, actor_user_id=_user_id(user)))


@router.patch("/campaigns/{campaign_id}")
def patch_campaign(
    campaign_id: int,
    payload: dict,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission(*CAMPAIGN_ADMIN)),
):
    from app.customer.pcw_maintenance_service import patch_campaign_draft

    result = _call(
        patch_campaign_draft, db,
        campaign_id=campaign_id,
        actor_user_id=_user_id(user),
        payload=payload,
    )
    db.commit()
    return ok(result)


@router.post("/campaigns/{campaign_id}/publications")
def publish_campaign(
    campaign_id: int,
    payload: CampaignVersionRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission(*CAMPAIGN_ADMIN)),
):
    from app.customer.pcw_maintenance_service import publish_campaign as service

    result = _call(
        service, db,
        campaign_id=campaign_id,
        actor_user_id=_user_id(user),
        expected_campaign_version=payload.expected_campaign_version,
        idempotency_key=idempotency_key,
    )
    db.commit()
    return ok(result)


@router.post("/campaigns/{campaign_id}/state-transitions")
def transition_campaign(
    campaign_id: int,
    payload: CampaignTransitionRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission(*CAMPAIGN_ADMIN)),
):
    from app.customer.pcw_maintenance_service import transition_campaign as service

    result = _call(
        service, db,
        campaign_id=campaign_id,
        actor_user_id=_user_id(user),
        target_status=payload.target_status,
        expected_campaign_version=payload.expected_campaign_version,
    )
    db.commit()
    return ok(result)


@router.post("/campaigns/{campaign_id}/preview")
def preview_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_READ)),
):
    from app.customer.pcw_maintenance_service import preview_campaign as service

    return ok(_call(
        service, db,
        campaign_id=campaign_id,
        actor_user_id=_user_id(user),
        actor_permissions=_perms(user),
    ))


@router.post("/campaigns/{campaign_id}/actions")
def create_campaign_actions(
    campaign_id: int,
    payload: CampaignActionsCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*PCW_WRITE)),
):
    from app.customer.pcw_maintenance_service import create_campaign_actions as service

    result = _call(
        service, db,
        campaign_id=campaign_id,
        actor_user_id=_user_id(user),
        preview_version=payload.preview_version,
        customer_ids=payload.customer_ids,
        actor_permissions=_perms(user),
        idempotency_key=idempotency_key,
    )
    db.commit()
    return ok(result)
