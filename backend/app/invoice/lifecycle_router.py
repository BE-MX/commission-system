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


def scope(db, identity, user, *permissions):
    from app.invoice.router import _linked_scope
    invoice, _, _ = _linked_scope(db, identity, user, "invoice:admin", *permissions)
    return invoice


@router.get("/invoices/{invoice_id}/lifecycle", summary="Read cancellation and outbound recovery state")
def detail(invoice_id: int, db: Session = Depends(get_db), user=Depends(require_permission("invoice:admin"))):
    from app.invoice.linked_sync_service import edit_version
    from app.invoice.models import OkkiOutboundTask
    from app.invoice import edit_authority
    invoice, user = edit_authority.prepare_local(db, invoice_id, user, "invoice:admin")
    from app.invoice import cancellation_facts, order_push_facts
    recovery = cancellation_facts.summary(db, invoice)
    order_recovery = order_push_facts.summary(db, invoice)
    task = db.query(OkkiOutboundTask).filter_by(invoice_id=invoice_id).first()
    return ok({"invoice_id": invoice.id, "invoice_no": invoice.invoice_no, "status": invoice.status,
               "version": edit_version(invoice), "cancellation": cancellation.public_state(invoice.cancellation),
               "recovery_summary": recovery, "order_push_summary": order_recovery,
               "outbound": {"status": task.status, "reason": task.reason} if task else None})


@router.post("/invoices/{invoice_id}/lifecycle", summary="Process reviewed invoice lifecycle action")
def apply(invoice_id: int, body: LifecycleAction, db: Session = Depends(get_db), user=Depends(require_permission("invoice:admin"))):
    if body.action == "remove":
        require_permission("invoice:delete")(user)
    if body.action in {"outbound_retry", "ack_outbound"}:
        from app.invoice import outbound_recovery
        if not body.confirmed:
            raise HTTPException(409, "请确认处理范围及核对依据")
        return ok(outbound_recovery.recover(db, invoice_id, user, body.action,
                                          body.reason.strip(), body.expected_version))
    if body.action == "remove":
        from app.invoice import cancellation_execution
        if not body.confirmed:
            raise HTTPException(409, "请确认处理范围及核对依据")
        return ok(cancellation.public_state(cancellation_execution.remove_authorized(db, invoice_id, user)))
    if body.action == "refresh":
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
    from app.invoice import edit_authority, legacy_sending
    invoice, user = edit_authority.prepare_local(db, invoice_id, user, "invoice:admin")
    legacy_sending.authorize(db, invoice)
    actor = int(user.get("id") or user["sub"])
    try:
        if (invoice.cancellation or {}).get("deletion") and (invoice.cancellation or {}).get("status") != "remote_deleted":
            raise ValueError("此订单已进入自动删除，请从订单发票列表的删除入口核对或继续原任务")
        if not body.confirmed:
            raise ValueError("请确认处理范围及核对依据")
        if body.action == "begin":
            result = cancellation.begin(db, invoice, body.reason.strip(), actor, body.expected_version)
        elif body.action == "retain":
            result = cancellation.retain(db, invoice, body.reason, actor, body.confirmed)
        elif body.action == "abort":
            result = cancellation.abort(db, invoice, actor, body.reason)
        else:
            raise ValueError("不支持的订单生命周期操作")
        db.commit()
        return ok(cancellation.public_state(result))
    except (ValueError, okki_client.OkkiApiError) as exc:
        db.rollback()
        logger.warning("Invoice lifecycle action rejected (%s)", type(exc).__name__)
        print(f"[invoice-lifecycle] rejected ({type(exc).__name__})", flush=True)
        raise HTTPException(409, str(exc)) from exc
