"""Customer-scoped enrichment entry points."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission
from app.core.database import get_db
from app.core.response import ok
from app.customer import enrichment_service, pcw_errors
from app.customer.access_service import CustomerAccessDenied

router = APIRouter()


@router.get("/customers/{customer_id}/enrichment")
def get_enrichment(
    customer_id: int, db: Session = Depends(get_db),
    user=Depends(require_any_permission(*enrichment_service.READ_PERMISSIONS)),
):
    try:
        return ok(enrichment_service.latest_enrichment(db, customer_id, user))
    except CustomerAccessDenied as exc:
        raise pcw_errors.customer_not_found() from exc


@router.post("/customers/{customer_id}/enrichment")
def create_enrichment(
    customer_id: int, db: Session = Depends(get_db),
    user=Depends(require_any_permission(*enrichment_service.WRITE_PERMISSIONS)),
):
    try:
        result = enrichment_service.request_enrichment(db, customer_id, user)
        db.commit()
        return ok(result)
    except CustomerAccessDenied as exc:
        db.rollback()
        raise pcw_errors.customer_not_found() from exc
    except Exception:
        db.rollback()
        raise
