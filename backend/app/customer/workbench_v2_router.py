"""Thin routes for the item workbench; domain services own transactions."""

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session
from app.auth.dependencies import require_any_permission
from app.core.database import get_db
from app.core.response import ok
from app.customer import daily_plan_service, work_item_query_service, work_item_service
from app.customer.workbench_schemas import AdmissionCreate, DelegationCreate, DelegationTransition, ItemFeedback, ItemTransition
from app.customer.workbench_schemas import ActionCorrection, DependencyCreate, ServiceAssetCreate, ServiceAssetRevoke

router = APIRouter()
READ = work_item_service.READ
WRITE = work_item_service.WRITE


@router.get("/customers/{customer_id}/service-assets")
def service_assets(customer_id: int, db: Session = Depends(get_db), user=Depends(require_any_permission(*READ))):
    from app.customer.service_asset_service import list_assets
    return ok(list_assets(db, user, customer_id))


@router.post("/customers/{customer_id}/service-assets")
def register_service_asset(customer_id: int, payload: ServiceAssetCreate,
                           idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
                           db: Session = Depends(get_db), user=Depends(require_any_permission(*WRITE))):
    from app.customer.service_asset_service import register_asset
    return _write(db, register_asset, user, customer_id, payload.model_dump(mode="json"), idempotency_key)


@router.post("/customers/{customer_id}/service-assets/{asset_id}/revoke")
def revoke_service_asset(customer_id: int, asset_id: int, payload: ServiceAssetRevoke,
                         idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
                         db: Session = Depends(get_db), user=Depends(require_any_permission(*WRITE))):
    from app.customer.service_asset_service import revoke_asset
    return _write(db, revoke_asset, user, customer_id, asset_id, payload.model_dump(mode="json"), idempotency_key)


@router.get("/customers/{customer_id}/maintenance-plan-sources")
def maintenance_sources(customer_id: int, db: Session = Depends(get_db), user=Depends(require_any_permission(*READ))):
    from app.customer.maintenance_source_service import list_sources
    return ok(list_sources(db, user, customer_id))


@router.post("/actions/{action_id}/corrections")
def correction(action_id: int, payload: ActionCorrection, idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
               db: Session = Depends(get_db), user=Depends(require_any_permission(*WRITE))):
    from app.customer.action_correction_service import correct_action
    return _write(db, correct_action, user, action_id, payload.model_dump(mode="json"), idempotency_key)


@router.post("/work-items/{item_id}/dependencies")
def dependency(item_id: int, payload: DependencyCreate, idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
               db: Session = Depends(get_db), user=Depends(require_any_permission(*WRITE))):
    from app.customer.work_item_source_service import attach_dependency
    return _write(db, attach_dependency, user, item_id, payload.model_dump(mode="json"), idempotency_key)


def _write(db, fn, *args):
    try:
        result = fn(db, *args)
        db.commit()
        return ok(result)
    except Exception:
        db.rollback()
        raise


@router.get("/workbench/items")
def list_items(view: str = Query("need_me", pattern="^(need_me|in_progress|ended)$"),
               customer_scope: str = Query("primary", pattern="^(primary|collaborator|authorized)$"),
               action_scope: str = Query("mine", pattern="^(mine|visible)$"),
               ended_state: str | None = Query(None, pattern="^(resolved|cancelled)$"),
               customer_id: int | None = Query(None, ge=1), keyword: str | None = Query(None, max_length=100),
               page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
               focus: str = Query("commitments", pattern="^(commitments|needs|reorder)$"),
               db: Session = Depends(get_db), user=Depends(require_any_permission(*READ))):
    try:
        result = work_item_query_service.list_items(db, user, view=view, customer_scope=customer_scope,
            action_scope=action_scope, ended_state=ended_state, customer_id=customer_id, keyword=keyword,
            page=page, page_size=page_size, focus=focus)
        # First visit persists the day's admissions, including an empty initial snapshot.
        db.commit()
        return ok(result)
    except Exception:
        db.rollback()
        raise


@router.get("/work-items/{item_id}")
def get_item(item_id: int, db: Session = Depends(get_db), user=Depends(require_any_permission(*READ))):
    return _write(db, work_item_query_service.get_item, user, item_id)


@router.post("/work-items/{item_id}/transitions")
def transition(item_id: int, payload: ItemTransition, idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
               db: Session = Depends(get_db), user=Depends(require_any_permission(*WRITE))):
    return _write(db, work_item_service.transition_item, user, item_id, payload.model_dump(mode="json"), idempotency_key)


@router.post("/workbench/daily-plan/admissions")
def admission(payload: AdmissionCreate, idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
              db: Session = Depends(get_db), user=Depends(require_any_permission(*WRITE))):
    return _write(db, daily_plan_service.admit_item, user, payload.model_dump(mode="json"), idempotency_key)


@router.post("/work-items/{item_id}/feedback")
def feedback(item_id: int, payload: ItemFeedback, idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
             db: Session = Depends(get_db), user=Depends(require_any_permission(*WRITE))):
    from app.customer.work_item_feedback_service import record_feedback
    return _write(db, record_feedback, user, item_id, payload.model_dump(mode="json"), idempotency_key)


@router.post("/work-items/{item_id}/delegations")
def delegation(item_id: int, payload: DelegationCreate, idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
               db: Session = Depends(get_db), user=Depends(require_any_permission(*WRITE))):
    from app.customer.delegation_service import create_delegation
    return _write(db, create_delegation, user, item_id, payload.model_dump(mode="json"), idempotency_key)


@router.post("/delegations/{delegation_id}/transitions")
def delegation_transition(delegation_id: int, payload: DelegationTransition,
                          idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
                          db: Session = Depends(get_db), user=Depends(require_any_permission(*WRITE))):
    from app.customer.delegation_service import transition_delegation
    return _write(db, transition_delegation, user, delegation_id, payload.model_dump(mode="json"), idempotency_key)
