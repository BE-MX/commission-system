"""Integration App administration routes."""

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.integration import service
from app.integration.schemas import IntegrationAppCreate


router = APIRouter()


@router.get("/admin/user-candidates", summary="Search eligible Integration App owners")
def get_user_candidates(
    q: str = Query(default="", max_length=50),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("integration:admin")),
):
    return ok({"items": service.list_user_candidates(db, q=q, limit=limit)})


@router.get("/admin/apps", summary="List Integration Apps without secret material")
def get_apps(
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("integration:admin")),
):
    items = service.list_apps(db)
    return ok({"total": len(items), "items": items})


@router.post("/admin/apps", summary="Create Integration App and return its token once")
def post_app(
    request: IntegrationAppCreate,
    db: Session = Depends(get_db),
    operator: dict = Depends(require_permission("integration:admin")),
):
    return ok(service.create_app(db, request, created_by=int(operator["sub"])))


@router.post("/admin/apps/{app_id}/rotate", summary="Atomically rotate an Integration App token")
def post_rotate_app(
    app_id: int = Path(ge=1),
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("integration:admin")),
):
    return ok(service.rotate_app_token(db, app_id))


@router.delete("/admin/apps/{app_id}", summary="Idempotently revoke an Integration App")
def delete_app(
    app_id: int = Path(ge=1),
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("integration:admin")),
):
    return ok(service.revoke_app(db, app_id), message="已吊销")
