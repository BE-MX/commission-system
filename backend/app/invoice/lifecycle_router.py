"""Invoice cancellation and outbound recovery endpoints."""
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.invoice import cancellation_service as cancellation, okki_client

class LifecycleRoute(APIRoute):
    """Keep private recovery responses uncached, including dependency rejections."""
    def get_route_handler(self):
        original = super().get_route_handler()
        async def uncached(request):
            try:
                response = await original(request)
            except StarletteHTTPException as error:
                error.headers = {**(error.headers or {}), "Cache-Control":"private, no-store"}
                raise
            response.headers["Cache-Control"] = "private, no-store"
            return response
        return uncached


router = APIRouter(route_class=LifecycleRoute)
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
    from app.portal.authority import get_settings
    if get_settings().PORTAL_ENABLED:
        from app.invoice import edit_authority
        invoice, user = edit_authority.prepare_local(db, invoice_id, user, "invoice:admin")
    else:
        invoice = scope(db, invoice_id, user)
    from app.invoice import cancellation_facts, order_push_facts
    recovery = cancellation_facts.summary(db, invoice) if get_settings().PORTAL_ENABLED else None
    order_recovery = order_push_facts.summary(db, invoice) if get_settings().PORTAL_ENABLED else None
    task = db.query(OkkiOutboundTask).filter_by(invoice_id=invoice_id).first()
    return ok({"invoice_id": invoice.id, "invoice_no": invoice.invoice_no, "status": invoice.status,
               "version": edit_version(invoice), "cancellation": cancellation.public_state(invoice.cancellation),
               "recovery_summary": recovery, "order_push_summary": order_recovery,
               "outbound": {"status": task.status, "reason": task.reason} if task else None})


@router.post("/invoices/{invoice_id}/lifecycle", summary="Process reviewed invoice lifecycle action")
def apply(invoice_id: int, body: LifecycleAction, db: Session = Depends(get_db), user=Depends(require_permission("invoice:admin"))):
    from app.portal.authority import get_settings
    if body.action in {"outbound_retry", "ack_outbound"} and get_settings().PORTAL_ENABLED:
        from app.invoice import outbound_recovery
        if not body.confirmed:
            raise HTTPException(409, "请确认处理范围及核对依据")
        return ok(outbound_recovery.recover(db, invoice_id, user, body.action,
                                          body.reason.strip(), body.expected_version))
    if body.action == "remove" and get_settings().PORTAL_ENABLED:
        from app.invoice import cancellation_execution
        if not body.confirmed:
            raise HTTPException(409, "请确认处理范围及核对依据")
        return ok(cancellation.public_state(cancellation_execution.remove_authorized(db, invoice_id, user)))
    if body.action == "refresh" and get_settings().PORTAL_ENABLED:
        if not body.confirmed:
            raise HTTPException(409, "请确认处理范围及核对依据")
        try:
            result = cancellation.refresh_authorized(db, invoice_id, user)
            db.commit()
            return ok(cancellation.public_state(result))
        except ValueError:
            db.rollback()
            logger.warning("Cancellation reconciliation rejected by current state")
            print("[invoice-cancel] reconciliation rejected by current state", flush=True)
            raise HTTPException(409, "当前取消流程不可核对，请重新读取") from None
    if body.action in {"begin", "retain", "abort"}:
        from app.invoice import edit_authority
        invoice, user = edit_authority.prepare_local(db, invoice_id, user, "invoice:admin")
    else:
        invoice = scope(db, invoice_id, user)
    actor = int(user.get("id") or user["sub"])
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
        return ok(cancellation.public_state(result))
    except (ValueError, okki_client.OkkiApiError) as exc:
        db.rollback()
        logger.warning("Invoice lifecycle action rejected (%s)", type(exc).__name__)
        print(f"[invoice-lifecycle] rejected ({type(exc).__name__})", flush=True)
        raise HTTPException(409, str(exc)) from exc
