"""Human-facing routes for governed customer change proposals."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_permission
from app.auth.service import get_live_user_authorization
from app.core.database import get_db
from app.core.response import ok, page_result
from app.customer import proposal_service, query_service
from app.customer.access_service import CustomerAccessDenied, require_customer_access
from app.customer.models import CustomerChangeProposal
from app.customer.schemas import (
    ProposalCreate, ProposalDecision, ProposalExecute, ProposalRebase,
)


router = APIRouter()
PROPOSAL_ADMIN = ("customer:admin", "customer:read_all")


def _user_id(user: dict) -> int:
    try:
        return int(user["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token格式错误") from None


def _not_found():
    raise HTTPException(status.HTTP_404_NOT_FOUND, "CUSTOMER_NOT_FOUND_OR_FORBIDDEN")


def _access(
    db, customer_id, user, *, action_permissions=PROPOSAL_ADMIN,
    manage_permissions=("customer:admin",),
):
    try:
        return require_customer_access(
            db, customer_id=customer_id, user=user,
            action_permissions=set(action_permissions),
            manage_permissions=set(manage_permissions), allow_public_pool=False,
        )
    except CustomerAccessDenied:
        _not_found()


def _service_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except proposal_service.ProposalNotFound:
        _not_found()
    except proposal_service.ProposalConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except (proposal_service.ProposalError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _sensitive_visible(row, accesses) -> bool:
    return bool(accesses) and all(
        row.data_classification in access.allowed_classifications()
        and row.visibility_scope in access.allowed_visibility_scopes()
        for access in accesses
    )


def _execution_sensitive_visible(row, accesses) -> bool:
    return bool(accesses) and all(
        access.can_manage
        and row.data_classification in access.allowed_classifications()
        for access in accesses
    )


def _view(row, accesses=()):
    data = proposal_service.serialize_proposal(row)
    if not _sensitive_visible(row, accesses):
        data["payload_json"] = None
        data["evidence_fact_ids"] = []
        data["action_hash"] = None
    for field in ("expires_at", "created_at", "updated_at"):
        data[field] = query_service.iso_beijing(data[field])
    return data


def _scope_query(db, user):
    source_ids = query_service._scoped_ids(
        db, user, read_permissions=PROPOSAL_ADMIN, include_public_pool=False,
    )
    target_ids = query_service._scoped_ids(
        db, user, read_permissions=PROPOSAL_ADMIN, include_public_pool=False,
    )
    return db.query(CustomerChangeProposal).filter(
        CustomerChangeProposal.customer_id.in_(source_ids),
        CustomerChangeProposal.target_customer_id.is_(None)
        | CustomerChangeProposal.target_customer_id.in_(target_ids),
    )


def _accesses(
    db, user, row, *, action_permissions=PROPOSAL_ADMIN,
    manage_permissions=("customer:admin",),
):
    result = [_access(
        db, row.customer_id, user, action_permissions=action_permissions,
        manage_permissions=manage_permissions,
    )]
    if row.target_customer_id is not None:
        result.append(_access(
            db, row.target_customer_id, user, action_permissions=action_permissions,
            manage_permissions=manage_permissions,
        ))
    return result


@router.get("/change-proposals")
def proposals(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db), user=Depends(require_permission("customer:admin")),
):
    query = _scope_query(db, user)
    total = query.count()
    rows = query.order_by(CustomerChangeProposal.updated_at.desc()).offset(
        (page - 1) * page_size,
    ).limit(page_size).all()
    return ok(page_result([
        _view(row, _accesses(db, user, row)) for row in rows
    ], total, page, page_size))


@router.post("/change-proposals", status_code=status.HTTP_201_CREATED)
def create_change_proposal(
    payload: ProposalCreate, db: Session = Depends(get_db),
    user=Depends(require_permission("customer:admin")),
):
    _access(db, payload.customer_id, user)
    if payload.target_customer_id is not None:
        _access(db, payload.target_customer_id, user)
    row = _service_call(
        proposal_service.create_proposal, db, **payload.model_dump(),
        proposed_by=_user_id(user),
    )
    db.commit()
    return ok(_view(row, _accesses(db, user, row)), code=201)


def _action(
    db, user, proposal_id, operation, *, execution_sensitive=False, **kwargs,
):
    candidate = _scope_query(db, user).filter(
        CustomerChangeProposal.id == proposal_id,
    ).one_or_none()
    if candidate is None:
        _not_found()
    accesses = _accesses(db, user, candidate)
    visible = _execution_sensitive_visible if execution_sensitive else _sensitive_visible
    if not visible(candidate, accesses):
        _not_found()
    row = _service_call(
        operation, db, proposal_id=proposal_id,
        actor_user_id=_user_id(user), **kwargs,
    )
    db.commit()
    return ok(_view(row, accesses))


@router.post("/change-proposals/{proposal_id}/submit")
def submit_change_proposal(
    proposal_id: int, db: Session = Depends(get_db),
    user=Depends(require_permission("customer:admin")),
):
    return _action(db, user, proposal_id, proposal_service.submit_proposal)


@router.post("/change-proposals/{proposal_id}/rebase")
def rebase_change_proposal(
    proposal_id: int, payload: ProposalRebase, db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    actor_user_id = _user_id(user)
    live_roles, live_permissions = get_live_user_authorization(db, actor_user_id)
    if "customer:admin" not in live_permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足，需要: customer:admin")
    live_user = {**user, "roles": live_roles, "permissions": live_permissions}
    return _action(
        db, live_user, proposal_id, proposal_service.rebase_proposal,
        execution_sensitive=True,
        profile_version_id=payload.profile_version_id,
        evidence_fact_ids=payload.evidence_fact_ids,
    )


@router.post("/change-proposals/{proposal_id}/approve")
def approve_change_proposal(
    proposal_id: int, _payload: ProposalDecision, db: Session = Depends(get_db),
    user=Depends(require_permission("customer:admin")),
):
    return _action(db, user, proposal_id, proposal_service.approve_proposal)


@router.post("/change-proposals/{proposal_id}/reject")
def reject_change_proposal(
    proposal_id: int, _payload: ProposalDecision, db: Session = Depends(get_db),
    user=Depends(require_permission("customer:admin")),
):
    return _action(db, user, proposal_id, proposal_service.reject_proposal)


@router.post("/change-proposals/{proposal_id}/execute")
def execute_change_proposal(
    proposal_id: int, payload: ProposalExecute, db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    candidate = db.query(CustomerChangeProposal).filter(
        CustomerChangeProposal.id == proposal_id,
    ).one_or_none()
    if candidate is None:
        _not_found()
    required_permission = {
        "merge": "customer:admin", "split": "customer:admin",
        "assign_primary": "customer:admin", "transfer_primary": "customer:admin",
        "set_dnc": "customer:manage_dnc", "remove_dnc": "customer:manage_dnc",
        "confirm_material_risk": "customer:confirm_material_risk",
    }.get(candidate.action_type)
    if required_permission is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "PROPOSAL_EXECUTOR_NOT_IMPLEMENTED")
    actor_user_id = _user_id(user)
    live_roles, live_permissions = get_live_user_authorization(db, actor_user_id)
    if required_permission not in live_permissions:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"权限不足，需要: {required_permission}",
        )
    live_user = {**user, "roles": live_roles, "permissions": live_permissions}
    accesses = _accesses(
        db, live_user, candidate, action_permissions=(required_permission,),
        manage_permissions=(required_permission,),
    )
    if not _execution_sensitive_visible(candidate, accesses):
        _not_found()
    row = _service_call(
        proposal_service.execute_proposal, db, proposal_id=proposal_id,
        actor_user_id=actor_user_id, idempotency_key=payload.idempotency_key,
    )
    db.commit()
    return ok(_view(row, accesses))
