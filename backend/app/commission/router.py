"""Native attribution administration, separate from current customer ownership."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auth.dependencies import require_permission
from app.commission.models import CommissionBasis
from app.commission.schemas import PolicyWrite, BasisResolve
from app.commission import service
from app.core.database import get_db
from app.core.response import ok
from app.invoice.native_authority import require_write
from app.invoice.read_authority import current_user as current_reader
from app.finance.router import write
from app.models.customer import CustomerCommissionSnapshot

router = APIRouter()


@router.get("/pending-bases")
def pending_bases(after_id: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                  db: Session = Depends(get_db), user=Depends(require_permission("commission:write"))):
    user = current_reader(db, user, 'commission:write')
    # SQL JSON NULL differs from SQL NULL on MySQL, so readiness is selected
    # by its explicit capture/resolve facts and inspected before serialization.
    rows = db.scalars(select(CommissionBasis).where(CommissionBasis.id > after_id,
        CommissionBasis.pending_reason.isnot(None), CommissionBasis.resolved_at.is_(None))
        .order_by(CommissionBasis.id).limit(limit)).all()
    return ok([{"id": row.id, "event_id": row.event_id, "customer_id": row.customer_id,
        "reason": row.pending_reason, "created_at": row.created_at} for row in rows])


@router.post("/bases/{basis_id}/resolve")
def resolve_basis(basis_id: int, body: BasisResolve, db: Session = Depends(get_db),
                  user=Depends(require_permission("commission:write"))):
    user = require_write(db, user, 'commission:write')
    return write(db, lambda: service.resolve(db, basis_id, body.snapshot_id, body.reason, user), lambda row: {"id": row.id})


@router.get("/customers/{customer_id}/policies")
def policies(customer_id: int, db: Session = Depends(get_db), user=Depends(require_permission("customer:write"))):
    user = current_reader(db, user, 'customer:write')
    rows = db.scalars(select(CustomerCommissionSnapshot).where(CustomerCommissionSnapshot.customer_id == f"ark:{customer_id}")
        .order_by(CustomerCommissionSnapshot.id.desc())).all()
    return ok([{col.name: getattr(row, col.name) for col in row.__table__.columns} for row in rows])


@router.post("/customers/{customer_id}/policies")
def create_policy(customer_id: int, body: PolicyWrite, db: Session = Depends(get_db),
                  user=Depends(require_permission("customer:write"))):
    user = require_write(db, user, 'customer:write')
    return write(db, lambda: service.write_policy(db, customer_id, body, user), lambda row: {"id": row.id})
