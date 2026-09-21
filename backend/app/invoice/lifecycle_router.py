"""Invoice cancellation and outbound recovery endpoints."""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.invoice import cancellation_service as cancellation, okki_client

router = APIRouter()
logger = logging.getLogger(__name__)


class LifecycleAction(BaseModel):
    action: str = Field(pattern="^(begin|refresh|remove|retain|abort|outbound_retry|ack_outbound)$")
    reason: str = Field(min_length=10, max_length=500)
    expected_version: str = Field(default="", max_length=64)
    confirmed: bool = False


def scope(db, identity, user):
    from app.invoice.router import _linked_scope
    return _linked_scope(db, identity, user)


@router.get("/invoices/{invoice_id}/lifecycle", summary="Read cancellation and outbound recovery state")
def detail(invoice_id: int, db: Session = Depends(get_db), user=Depends(require_permission("invoice:admin"))):
    from app.invoice.linked_sync_service import edit_version
    from app.invoice.models import OkkiOutboundTask
    invoice = scope(db, invoice_id, user)
    task = db.query(OkkiOutboundTask).filter_by(invoice_id=invoice_id).first()
    return ok({"invoice_id": invoice.id, "invoice_no": invoice.invoice_no, "status": invoice.status,
               "version": edit_version(invoice), "cancellation": invoice.cancellation,
               "outbound": {"status": task.status, "reason": task.reason} if task else None})


@router.post("/invoices/{invoice_id}/lifecycle", summary="Process reviewed invoice lifecycle action")
def apply(invoice_id: int, body: LifecycleAction, db: Session = Depends(get_db), user=Depends(require_permission("invoice:admin"))):
    invoice = scope(db, invoice_id, user)
    actor = int(user["sub"])
    try:
        if not body.confirmed:
            raise ValueError("请确认处理范围及核对依据")
        if body.action == "begin":
            result = cancellation.begin(db, invoice, body.reason.strip(), actor, body.expected_version)
        elif body.action == "refresh":
            result = cancellation.refresh(db, invoice, actor)
        elif body.action == "remove":
            result = cancellation.remove_remote(db, invoice, actor)
        elif body.action == "retain":
            result = cancellation.retain(db, invoice, body.reason, actor, body.confirmed)
        elif body.action == "abort":
            result = cancellation.abort(db, invoice, actor, body.reason)
        elif body.action == "ack_outbound":
            from app.invoice.linked_sync_service import acknowledge_outbound
            result = acknowledge_outbound(db, invoice, actor, body.reason, body.expected_version)
        else:
            from app.invoice.outbound_task_service import retry_reviewed
            result = retry_reviewed(db, invoice, actor, body.reason, body.expected_version)
        db.commit()
        return ok(result)
    except (ValueError, okki_client.OkkiApiError) as exc:
        db.rollback()
        logger.warning("Invoice lifecycle action rejected (%s)", type(exc).__name__)
        print(f"[invoice-lifecycle] rejected ({type(exc).__name__})", flush=True)
        raise HTTPException(409, str(exc)) from exc
