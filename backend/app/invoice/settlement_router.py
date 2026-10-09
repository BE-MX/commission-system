"""Authenticated settlement APIs. All financial mutations are service-owned."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.auth.dependencies import get_current_user, require_permission
from app.core.database import get_db
from app.core.response import ok
from app.invoice import settlement_service as service, shipment_delivery, freight_delivery
from app.invoice.settlement_models import ShipmentOutbound, Receivable, SettlementEvent
from app.invoice.settlement_schemas import ShipmentQuote, ShipmentCreate, SettlementAction, SettlementRemoteReview, BatchCreate, FundingUpgrade
from app.receipt import batch_create_service, batch_service
from app.receipt import access
from app.receipt.router import execute

router = APIRouter()


class BatchStatusRoute(APIRoute):
    """Protect only the original-command inspector, including dependency failures."""
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            try:
                response = await handler(request)
            except RequestValidationError:
                # Do not echo amount, remark, proof IDs or the frozen command.
                response = JSONResponse(status_code=422, content={"detail": "原提交参数不完整，请保持原请求并核对"})
            except HTTPException as error:
                error.headers = {**(error.headers or {}), "Cache-Control": "private, no-store", "Pragma": "no-cache"}
                raise
            response.headers.update({"Cache-Control": "private, no-store", "Pragma": "no-cache"})
            return response
        return guarded


class ShipmentReadRoute(APIRoute):
    """Protect financial read/quote responses, including dependency/422 errors."""
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def guarded(request):
            try:
                response=await handler(request)
            except RequestValidationError:
                response=JSONResponse(status_code=422,content={'detail':'发货查询参数不完整，请检查后重新查询'})
            except HTTPException as error:
                error.headers={**(error.headers or {}),'Cache-Control':'private, no-store','Pragma':'no-cache'}
                raise
            response.headers.update({'Cache-Control':'private, no-store','Pragma':'no-cache'})
            return response
        return guarded


class ShipmentSubmissionRoute(APIRoute):
    """Private original-shipment responses, including dependencies and invalid bodies."""
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def guarded(request):
            try:
                response = await handler(request)
            except RequestValidationError:
                response = JSONResponse(status_code=422, content={'detail':'原发货参数不完整，请保持原请求并核对'})
            except HTTPException as error:
                error.headers = {**(error.headers or {}),'Cache-Control':'private, no-store','Pragma':'no-cache'}
                raise
            response.headers.update({'Cache-Control':'private, no-store','Pragma':'no-cache'})
            return response
        return guarded


shipment_submission_router = APIRouter(route_class=ShipmentSubmissionRoute)


shipment_read_router=APIRouter(route_class=ShipmentReadRoute)


class ShipmentStateRoute(APIRoute):
    """Only local state commands; private dependency and sanitized 422 replies."""
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def guarded(request):
            try:
                response = await handler(request)
            except RequestValidationError:
                response = JSONResponse(status_code=422, content={'detail': '状态操作参数不完整，请刷新原结算核对'})
            except HTTPException as error:
                error.headers = {**(error.headers or {}), 'Cache-Control': 'private, no-store', 'Pragma': 'no-cache'}
                raise
            response.headers.update({'Cache-Control': 'private, no-store', 'Pragma': 'no-cache'})
            return response
        return guarded


shipment_state_router = APIRouter(route_class=ShipmentStateRoute)


status_router = APIRouter(route_class=BatchStatusRoute)


@shipment_read_router.get("/shipments/capabilities")
def capability(db: Session=Depends(get_db),user=Depends(get_current_user)):
    from app.invoice.shipment_read_service import read
    return ok(read(db,user,kind='capabilities'))


@shipment_read_router.post("/invoices/{identity}/shipment-quotes")
def quote(identity: int, body: ShipmentQuote, db: Session=Depends(get_db),user=Depends(get_current_user)):
    return ok(service.quote(db,identity,body,user))


@shipment_submission_router.post("/invoices/{identity}/shipment-settlements")
def create(identity: int, body: ShipmentCreate, db: Session = Depends(get_db),
           user=Depends(get_current_user)):
    # JWT identifies the actor; the service rechecks every required current action.
    from app.invoice import shipment_create_service
    try:
        def apply():
            row = service.create(db, identity, body, user)
            return {**service.describe(db, row), 'request_key':row.request_key, 'quote_hash':row.quote_hash}
        return execute(db, apply)
    except SQLAlchemyError as error:
        shipment_create_service.result_unavailable(error)


@shipment_submission_router.post('/invoices/{identity}/shipment-settlements/submission-status',
    summary='Inspect the original shipment command without creating a settlement')
def shipment_submission_status(identity: int, body: ShipmentCreate, db: Session=Depends(get_db), user=Depends(get_current_user)):
    from app.invoice.shipment_create_service import submission_status
    return ok(submission_status(db, identity, body, user))


@shipment_read_router.get("/shipments/order/{identity}")
def for_order(identity: int,db: Session=Depends(get_db),user=Depends(get_current_user)):
    from app.invoice.shipment_read_service import read
    return ok(read(db,user,kind='order',identity=identity))


@shipment_read_router.get("/shipments/{identity}")
def detail(identity: int,db: Session=Depends(get_db),user=Depends(get_current_user)):
    from app.invoice.shipment_read_service import read
    return ok(read(db,user,kind='detail',identity=identity))


@shipment_state_router.post("/shipments/{identity}/cancel")
def cancel(identity: int, body: SettlementAction, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _change(db, identity, body, user, "cancel")


@shipment_state_router.post("/shipments/{identity}/upgrade-funding")
def upgrade_funding(identity: int, body: FundingUpgrade, db: Session=Depends(get_db), user=Depends(get_current_user)):
    from app.invoice import funding_upgrade_service, shipment_state_service
    try:
        return execute(db, lambda: funding_upgrade_service.upgrade(db,identity,body,user))
    except SQLAlchemyError as error:
        shipment_state_service.result_unavailable(error)


@shipment_state_router.post("/shipments/{identity}/pause")
def pause(identity: int, body: SettlementAction, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _change(db, identity, body, user, "pause")


@shipment_state_router.post("/shipments/{identity}/resume")
def resume(identity: int, body: SettlementAction, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _change(db, identity, body, user, "resume")


def _change(db, identity, body, user, action):
    from app.invoice import shipment_state_service
    try:
        return execute(db, lambda: shipment_state_service.change(
            db, identity, user, action, body.version, body.reason))
    except SQLAlchemyError as error:
        shipment_state_service.result_unavailable(error)


@shipment_state_router.post("/shipments/{identity}/confirm-outbound")
def confirm_outbound(identity: int, body: SettlementAction, db: Session = Depends(get_db),
                     user=Depends(get_current_user)):
    from app.invoice import shipment_confirmation_service,shipment_state_service
    try:
        return execute(db, lambda: shipment_confirmation_service.confirm(db,identity,body,user))
    except SQLAlchemyError as error:
        shipment_state_service.result_unavailable(error)


@shipment_state_router.post("/shipments/{identity}/reconcile-freight")
def reconcile_freight(identity: int, body: SettlementRemoteReview,
                      db: Session = Depends(get_db), user=Depends(get_current_user)):
    from app.invoice import freight_reconciliation_service, shipment_state_service
    try:
        return execute(db, lambda: freight_reconciliation_service.reconcile(db,identity,body,user))
    except SQLAlchemyError as error:
        shipment_state_service.result_unavailable(error)


@shipment_state_router.post("/shipments/{identity}/retry-freight")
def retry_freight(identity: int, body: SettlementAction,
                  db: Session = Depends(get_db), user=Depends(get_current_user)):
    from app.invoice import shipment_retry_service, shipment_state_service
    try:
        return execute(db, lambda: shipment_retry_service.retry(db,identity,body,user,kind='freight'))
    except SQLAlchemyError as error:
        shipment_state_service.result_unavailable(error)


@shipment_state_router.post("/shipments/{identity}/reconcile-outbound")
def reconcile_outbound(identity: int, body: SettlementRemoteReview,
                       db: Session = Depends(get_db), user=Depends(get_current_user)):
    from app.invoice import outbound_reconciliation_service, shipment_state_service
    try:
        return execute(db, lambda: outbound_reconciliation_service.reconcile(db,identity,body,user))
    except SQLAlchemyError as error:
        shipment_state_service.result_unavailable(error)


@shipment_state_router.post("/shipments/{identity}/retry-outbound")
def retry_outbound(identity: int, body: SettlementAction,
                  db: Session = Depends(get_db), user=Depends(get_current_user)):
    from app.invoice import shipment_retry_service, shipment_state_service
    try:
        return execute(db, lambda: shipment_retry_service.retry(db,identity,body,user,kind='outbound'))
    except SQLAlchemyError as error:
        shipment_state_service.result_unavailable(error)


@router.post("/receipts/batches")
def create_batch(body: BatchCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    def apply():
        row, current = batch_create_service.create(db, body, user)
        return {**batch_service.describe(db, row, current), "request_key": row.request_key}
    try:
        return execute(db, apply)
    except SQLAlchemyError as error:
        batch_create_service.result_unavailable(error)


@status_router.post("/receipts/batches/submission-status", summary="Inspect the original batch command without creating a payment")
def batch_submission_status(body: BatchCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return ok(batch_create_service.submission_status(db, body, user))


@router.get("/receipts/batches/{identity}")
def batch_detail(identity: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    try:
        return ok(batch_service.read(db, identity, user))
    except SQLAlchemyError as error:
        batch_service.unavailable(error)


@router.post("/receipts/batches/{identity}/void-entry")
def void_entry(identity: int, body: SettlementAction, db: Session = Depends(get_db), user=Depends(get_current_user)):
    try:
        return execute(db, lambda: batch_service.void_entry(db, identity, user, body.version, body.reason))
    except SQLAlchemyError as error:
        batch_service.unavailable(error)


router.include_router(status_router)


router.include_router(shipment_read_router)


router.include_router(shipment_state_router)


router.include_router(shipment_submission_router)
