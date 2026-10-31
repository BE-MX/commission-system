"""Native commercial reporting administration."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, lazyload
from app.auth.dependencies import require_any_permission, require_permission
from app.auth.models import ArkUser
from app.core.database import get_db
from app.core.response import ok
from app.trade.models import SalesRoster
from app.trade.roster_service import serialize_roster, write_roster
from app.trade.schemas import RosterWrite, AttributionWrite

router = APIRouter()


@router.get("/projection-status")
def projection_state(db: Session = Depends(get_db), user=Depends(require_permission("employee:write"))):
    from app.trade.refresh_service import projection_status
    return ok(projection_status(db))


@router.get("/roster")
def roster(after_id: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
           db: Session = Depends(get_db),
           user=Depends(require_any_permission("employee:read", "employee:write"))):
    rows = db.execute(select(ArkUser, SalesRoster).options(lazyload(ArkUser.roles)).outerjoin(SalesRoster, SalesRoster.ark_user_id == ArkUser.id)
        .where(ArkUser.id > after_id).order_by(ArkUser.id).limit(limit)).all()
    return ok([serialize_roster(member, employee) for employee, member in rows])


@router.put("/roster/{user_id}")
def update_roster(user_id: int, body: RosterWrite, db: Session = Depends(get_db),
                  actor=Depends(require_permission("employee:write"))):
    try:
        row = write_roster(db, user_id, body, actor)
        result = serialize_roster(row, db.get(ArkUser, user_id))
        db.commit()
        return ok(result)
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else "名册关联冲突，请刷新核对") from exc
    except Exception:
        db.rollback()
        raise


@router.get("/departments")
def departments(db: Session = Depends(get_db), actor=Depends(require_any_permission("employee:read", "employee:write", "invoice:write"))):
    from app.trade.department_service import department_options
    return ok(department_options(db))


@router.put("/invoices/{invoice_id}/departments")
def attribute_departments(invoice_id: int, body: AttributionWrite, db: Session = Depends(get_db),
                          actor=Depends(require_permission("employee:write"))):
    from app.trade.department_service import assign_departments
    try:
        invoice = assign_departments(db, invoice_id, body, actor)
        result = {"invoice_id": invoice.id, "version": invoice.commerce_version, "departments": invoice.local_commercial["departments"]}
        db.commit()
        return ok(result)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except Exception:
        db.rollback()
        raise
