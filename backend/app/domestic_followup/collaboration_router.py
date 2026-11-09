"""Customer followup collaboration endpoints."""
from contextlib import contextmanager
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok
from app.domestic_followup import collaboration_access as access
from app.domestic_followup import collaboration_admin as admin
from app.domestic_followup import collaboration_projection as views
from app.domestic_followup.collaboration_schemas import (
    CollaborationActionIn, CoordinationSettingsIn, InitializationIn, ScopeIn,
)
from app.domestic_followup.collaboration_service import apply_action
from app.domestic_followup.collaboration_tasks import ConflictError

router = APIRouter(prefix="/collaboration")
_require_read = require_any_permission(access.READ, access.COORDINATE)
_require_action = require_any_permission(access.WRITE, access.COORDINATE)
_require_coordinate = require_permission(access.COORDINATE)
_require_configure = require_permission(access.COORDINATE, access.ADMIN)
logger = logging.getLogger("commission")


@contextmanager
def _errors(db, *, writing=False):
    try:
        yield
        if writing:
            db.commit()
    except ConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (KeyError, IndexError):
        db.rollback()
        raise
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        logger.warning("Followup collaboration transaction conflicted", exc_info=True)
        print("Followup collaboration transaction conflicted", flush=True)
        raise HTTPException(status_code=409, detail="跟进责任或待办已变化，请刷新") from exc
    except Exception:
        db.rollback()
        logger.exception("Followup collaboration operation failed")
        print("Followup collaboration operation failed", flush=True)
        raise


@router.get("/settings/scopes")
def list_scopes(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
                db: Session = Depends(get_db), user=Depends(_require_configure)):
    with _errors(db):
        result = admin.list_scopes(db, user, page, page_size)
    return ok(result)


@router.get("/settings/users")
def scope_users(q: str = Query("", max_length=60), db: Session = Depends(get_db), user=Depends(_require_configure)):
    with _errors(db):
        result = admin.users_for_scope(db, user, q.strip())
    return ok(result)


@router.get("/settings/thresholds")
def settings(db: Session = Depends(get_db), user=Depends(_require_configure)):
    with _errors(db):
        result = admin.coordination_settings(db, user)
    return ok(result)


@router.put("/settings/thresholds")
def update_settings(payload: CoordinationSettingsIn, db: Session = Depends(get_db), user=Depends(_require_configure)):
    with _errors(db, writing=True):
        result = admin.coordination_settings(db, user, payload.pending_handoff_days)
    return ok(result)


@router.post("/settings/scopes")
def add_scope(payload: ScopeIn, db: Session = Depends(get_db), user=Depends(_require_configure)):
    with _errors(db, writing=True):
        result = admin.add_scope(db, user, payload)
    return ok(result)


@router.delete("/settings/scopes/{scope_id}")
def delete_scope(scope_id: int, db: Session = Depends(get_db), user=Depends(_require_configure)):
    with _errors(db, writing=True):
        result = admin.delete_scope(db, user, scope_id)
    return ok(result)


@router.get("/initialize")
def preview_initialization(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
                           db: Session = Depends(get_db), user=Depends(_require_coordinate)):
    with _errors(db):
        result = admin.preview_initialization(db, user, page, page_size)
    return ok(result)


@router.post("/initialize")
def initialize(payload: InitializationIn, db: Session = Depends(get_db), user=Depends(_require_coordinate)):
    with _errors(db, writing=True):
        result = admin.apply_initialization(db, user, payload.items)
    return ok(result)


@router.get("/coordination")
def coordination(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
                 db: Session = Depends(get_db), user=Depends(_require_coordinate)):
    with _errors(db):
        result = admin.coordination_queue(db, user, page, page_size)
    return ok(result)


@router.get("/{customer_id}")
def detail(customer_id: int, db: Session = Depends(get_db), user=Depends(_require_read)):
    with _errors(db):
        customer = views.read_customer(db, user, customer_id)
        result = views.project(db, user, customer)
    return ok(result)


@router.post("/{customer_id}/actions")
def act(customer_id: int, payload: CollaborationActionIn, db: Session = Depends(get_db), user=Depends(_require_action)):
    with _errors(db, writing=True):
        result = apply_action(db, user, customer_id, payload)
    return ok(result)


@router.get("/{customer_id}/candidates")
def candidates(customer_id: int, db: Session = Depends(get_db), user=Depends(_require_read)):
    with _errors(db):
        customer = views.read_customer(db, user, customer_id)
        result = views.candidates(db, user, customer)
    return ok(result)


@router.get("/{customer_id}/tasks")
def task_preflight(customer_id: int, action: str | None = Query(None, max_length=24),
                   db: Session = Depends(get_db), user=Depends(_require_read)):
    with _errors(db):
        customer = views.read_customer(db, user, customer_id)
        result = views.task_preflight(db, user, customer, action)
    return ok(result)


@router.get("/{customer_id}/events")
def events(customer_id: int, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
           db: Session = Depends(get_db), user=Depends(_require_read)):
    with _errors(db):
        customer = views.read_customer(db, user, customer_id)
        result = views.events(db, user, customer, page, page_size)
    return ok(result)
