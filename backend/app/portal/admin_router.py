"""Employee Bearer boundary; all effective permissions are reloaded inside services."""
import re
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.core.response import ok
from app.portal import admin_service as service
from app.portal.auth_service import require_enabled
from app.portal.errors import PortalError, reject
from app.portal.schemas import (PortalInput, CatalogImageInput, NotificationRetryInput, AccountUpdate, CustomerCreate, CustomerUpdate, CustomerCatalogUpdate, InvitationInput, ReasonInput, RebindInput, TransferInput, MappingInput, SiteUpdate, CatalogImport, CatalogUpdate, ProposalInput, ApproveInput, PiProposalInput, PublishPiInput, VoidPiInput)


class AdminRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def guarded(request):
            try:
                require_enabled()
                if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    reject("INVALID_INPUT", "请使用 JSON 格式提交。", 415)
                response = await handler(request)
            except (PortalError, RequestValidationError, HTTPException) as error:
                if isinstance(error, PortalError):
                    status, code, message = error.status, error.code, error.message
                    message = {"ACTION_FORBIDDEN": "当前员工无此操作权限。",
                        "INVALID_INPUT": "输入内容不符合要求，请检查字段。",
                        "RESOURCE_NOT_FOUND": "记录不存在或不在当前授权范围内。",
                        "MAPPING_CONFLICT": "客户型号、颜色或货号存在歧义，请调整后重试。",
                        "VERSION_REQUIRED": "请刷新页面后再操作。", "VERSION_CONFLICT": "记录已变化，请刷新确认。",
                        "IDENTITY_REVIEW_REQUIRED": "客户身份需要重新复核。", "ASSIGNMENT_CHANGED": "客户负责人已变化，请复核归属。",
                        "SERVICE_UNAVAILABLE": "客户门户暂未开放。",
                        "TRANSACTION_BUSY": "交易服务繁忙，请先核对原操作结果后再重试。"}.get(code, message)
                elif isinstance(error, HTTPException):
                    status, code, message = error.status_code, "AUTH_REQUIRED", "请重新登录方舟后操作。"
                else:
                    status, code, message = 422, "INVALID_INPUT", "请检查提交字段。"
                response = JSONResponse(status_code=status, content=ok(code=status, message=message,
                    data={"error_code": code, "trace_id": str(uuid4()), "retryable": status == 503, "issues": []}))
            response.headers["Cache-Control"] = "private, no-store"
            return response
        return guarded


router = APIRouter(route_class=AdminRoute)


def expected_version(if_match: str | None = Header(default=None, alias="If-Match")):
    if if_match is None:
        reject("VERSION_REQUIRED", "请刷新页面后再操作。", 428)
    if not re.fullmatch(r'"(?:0|[1-9][0-9]{0,18})"', if_match):
        reject("INVALID_INPUT", "If-Match 必须包含带引号的记录版本。", 422)
    return int(if_match[1:-1])


def idempotency_key(value: str | None = Header(default=None, alias="Idempotency-Key")):
    if value is None:
        reject("IDEMPOTENCY_KEY_REQUIRED", "缺少操作标识，请刷新重试。", 428)
    try:
        return UUID(value)
    except ValueError:
        reject("INVALID_INPUT", "操作标识必须为 UUID。", 422)


def _require_portal_employee(current_user=Depends(get_current_user)):
    # Decode identity only. Role and permission claims are never forwarded.
    try:
        identifier = int(current_user["sub"])
        if identifier <= 0:
            raise ValueError("Invalid employee identifier")
        return identifier
    except (KeyError, TypeError, ValueError):
        reject("AUTH_REQUIRED", "请重新登录方舟后操作。", 401)


@router.get("/onboarding/customers")
def onboarding_customers(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                         keyword: str | None = Query(None, max_length=100),
                         actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.onboarding_service import list_candidates
    data = list_candidates(db, actor, page=page, page_size=page_size, keyword=keyword)
    db.commit()
    return ok(data)


@router.get("/onboarding/customers/{customer_id}")
def onboarding_status(customer_id: int, actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.onboarding_service import status
    if not 1 <= customer_id <= 9223372036854775807:
        reject("INVALID_INPUT", "无效客户编号。", 422)
    data = status(db, actor, customer_id)
    db.commit()
    return ok(data)


@router.get("/onboarding/catalog")
def onboarding_catalog(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                       keyword: str | None = Query(None, max_length=100),
                       actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.onboarding_service import catalog_options
    data = catalog_options(db, actor, page=page, page_size=page_size, keyword=keyword)
    db.commit()
    return ok(data)


@router.get("/customers")
def customers(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
              status: Literal["draft", "enabled", "suspended", "review_required"] | None = None,
              keyword: str | None = Query(None, max_length=100),
              actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    data = service.list_customers(db, actor, page=page, page_size=page_size, status=status, keyword=keyword)
    db.commit()
    return ok(data)


@router.post("/customers", status_code=201)
def create_customer(body: CustomerCreate, actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    data = service.create_customer(db, actor, body)
    db.commit()
    return ok(data, code=201)


@router.patch("/customers/{access_id}")
def update_customer(access_id: UUID, body: CustomerUpdate, expected=Depends(expected_version),
                    actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    data = service.update_customer(db, actor, access_id, expected, body)
    db.commit()
    return ok(data)


@router.get("/customers/{access_id}/catalog")
def customer_catalog(access_id: UUID, actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.catalog_access_service import get_catalog
    data = get_catalog(db, actor, access_id)
    db.commit()
    return ok(data)


@router.patch("/customers/{access_id}/catalog")
def update_customer_catalog(access_id: UUID, body: CustomerCatalogUpdate, expected=Depends(expected_version),
                            actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.catalog_access_service import update_catalog
    data = update_catalog(db, actor, access_id, expected, body)
    db.commit()
    return ok(data)


@router.post("/customers/{access_id}/invitations")
def invite(access_id: UUID, body: InvitationInput, command_key=Depends(idempotency_key),
           actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    data = service.invite(db, actor, access_id, command_key, body)
    db.commit()
    code = 200 if data["replayed"] else 201
    return JSONResponse(status_code=code, content=ok(data, code=code))


@router.post("/invitations/{invitation_id}/revoke")
def revoke_invitation(invitation_id: UUID, body: ReasonInput, expected=Depends(expected_version),
                      actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    data = service.revoke_invitation(db, actor, invitation_id, expected, body.reason)
    db.commit()
    return ok(data)


@router.patch("/accounts/{account_id}")
def update_account(account_id: UUID, body: AccountUpdate, expected=Depends(expected_version),
                   actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    data = service.update_account(db, actor, account_id, expected, body)
    db.commit()
    return ok(data)


@router.get("/customers/{access_id}")
def customer_detail(access_id: UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                    actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    data = service.customer_detail(db, actor, access_id, page=page, page_size=page_size)
    db.commit()
    return ok(data)


@router.post("/customers/{access_id}/rebind")
def rebind_identity(access_id: UUID, body: RebindInput, expected=Depends(expected_version),
                    actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    data = service.rebind_identity(db, actor, access_id, expected, body)
    db.commit()
    return ok(data)


@router.get("/customers/{access_id}/binding-review")
def binding_review(access_id: UUID, actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.binding_review_service import context
    data = context(db, actor, access_id)
    db.commit()
    return ok(data)


@router.post("/customers/{access_id}/transfer")
def transfer_customer(access_id: UUID, body: TransferInput, expected=Depends(expected_version),
                      actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.ownership_service import transfer_customer as transfer
    data = transfer(db, actor, access_id, expected, body)
    db.commit()
    return ok(data)


@router.post("/customers/{access_id}/preview")
def customer_preview(access_id: UUID, body: PortalInput,
                     actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.mapping_service import customer_preview as preview
    data = preview(db, actor, access_id)
    db.commit()
    return ok(data)


@router.get("/customers/{access_id}/mapping")
def get_mapping(access_id: UUID, actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.mapping_service import get_mapping as read
    data = read(db, actor, access_id)
    db.commit()
    return ok(data)


@router.post("/customers/{access_id}/mapping/preview")
def preview_mapping(access_id: UUID, body: MappingInput,
                    actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.mapping_service import preview
    data = preview(db, actor, access_id, body)
    db.commit()
    return ok(data)


@router.post("/customers/{access_id}/mapping/publish", status_code=201)
def publish_mapping(access_id: UUID, body: MappingInput, expected=Depends(expected_version),
                    actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.mapping_service import publish
    data = publish(db, actor, access_id, expected, body)
    db.commit()
    return ok(data, code=201)


@router.get("/customers/{access_id}/mapping/notifications")
def mapping_notifications(access_id: UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                          actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.mapping_notification_admin import list_events
    data = list_events(db, actor, access_id, page=page, page_size=page_size)
    db.commit()
    return ok(data)


@router.post("/customers/{access_id}/mapping/notifications/{event_id}/retry")
def retry_mapping_notification(access_id: UUID, event_id: UUID, body: NotificationRetryInput,
                               command_key=Depends(idempotency_key), actor=Depends(_require_portal_employee),
                               db: Session = Depends(get_db)):
    from app.portal.mapping_notification_admin import retry
    data = retry(db, actor, access_id, event_id, command_key, body)
    db.commit()
    return ok(data)


@router.get("/settings")
def get_settings(actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.site_service import read_settings
    data = read_settings(db, actor)
    db.commit()
    return ok(data)


@router.patch("/settings")
def update_settings(body: SiteUpdate, expected=Depends(expected_version),
                    actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.site_service import update_settings as update
    data = update(db, actor, expected, body)
    db.commit()
    return ok(data)


@router.get("/catalog")
def catalog_items(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                  status: Literal["draft", "published", "disabled"] | None = None,
                  keyword: str | None = Query(None, max_length=100),
                  actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.catalog_admin_service import list_items
    data = list_items(db, actor, page=page, page_size=page_size, status=status, keyword=keyword)
    db.commit()
    return ok(data)


@router.get("/catalog/source")
def inspect_catalog_source(product_id: str = Query(..., min_length=1, max_length=19),
                           sku_id: str = Query(..., min_length=1, max_length=19),
                           product_kind: Literal["hair", "accessory"] = Query(...),
                           actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.catalog_admin_service import inspect_source
    data = inspect_source(db, actor, product_id=product_id, sku_id=sku_id, product_kind=product_kind)
    db.commit()
    return ok(data)


@router.get("/catalog/import-status")
def catalog_import_status(product_id: str = Query(..., min_length=1, max_length=19),
                          sku_id: str = Query(..., min_length=1, max_length=19),
                          actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.catalog_admin_service import lookup_import
    data = lookup_import(db, actor, product_id=product_id, sku_id=sku_id)
    db.commit()
    return ok(data)


@router.get("/catalog/{item_id}")
def catalog_item(item_id: UUID, actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.catalog_admin_service import get_item
    data = get_item(db, actor, item_id)
    db.commit()
    return ok(data)


@router.post("/catalog/import")
def import_catalog_item(body: CatalogImport, expected=Depends(expected_version),
                        actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.catalog_admin_service import import_item
    data = import_item(db, actor, expected, body)
    db.commit()
    return ok(data)


@router.patch("/catalog/{item_id}")
def update_catalog_item(item_id: UUID, body: CatalogUpdate, expected=Depends(expected_version),
                        actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.catalog_admin_service import update_item
    data = update_item(db, actor, item_id, expected, body)
    db.commit()
    return ok(data)


@router.get("/orders")
def orders(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
           status: Literal["submitted", "awaiting_customer", "ready_for_review", "invoice_created", "rejected", "cancelled"] | None = None,
           actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.order_queries import employee_list
    data = employee_list(db, actor, page=page, page_size=page_size, status=status)
    db.commit()
    return ok(data)


@router.get("/orders/{request_id}")
def order_detail(request_id: UUID, actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.order_queries import employee_detail
    data = employee_detail(db, actor, request_id)
    db.commit()
    return ok(data)


@router.get("/orders/{request_id}/review")
def review_order(request_id: UUID, actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.review_service import context
    data = context(db, actor, request_id)
    db.commit()
    return ok(data)


@router.get("/orders/{request_id}/proposal-catalog")
def proposal_catalog(request_id: UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                     keyword: str = Query("", max_length=100),
                     actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.proposal_preview_service import catalog
    data = catalog(db, actor, request_id, keyword=keyword, page=page, page_size=page_size)
    db.commit()
    return ok(data)


@router.post("/orders/{request_id}/proposal-preview")
def preview_proposal(request_id: UUID, body: ProposalInput, expected=Depends(expected_version),
                     actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.proposal_preview_service import preview
    data = preview(db, actor, request_id, expected, body)
    db.commit()
    return ok(data)


@router.post("/orders/{request_id}/proposals")
def create_proposal(request_id: UUID, body: ProposalInput, expected=Depends(expected_version),
                    actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal import proposal_service
    try:
        data = proposal_service.create(db, actor, request_id, expected, body)
        db.commit()
    except PortalError:
        db.rollback()
        raise
    return ok(data)


@router.post("/orders/{request_id}/approve")
def approve_order(request_id: UUID, body: ApproveInput, expected=Depends(expected_version),
                  actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.approval_service import execute
    return ok(execute(db, actor, request_id, expected, body))


def _pi_command(db, actor, request_id, expected, body, operation):
    try:
        data = operation(db, actor, request_id, expected, body)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(data)


@router.get("/orders/{request_id}/pi-review")
def review_pi(request_id: UUID, actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.pi_review_service import context
    data = context(db, actor, request_id)
    db.commit()
    return ok(data)


@router.post("/orders/{request_id}/pi-proposals")
def propose_pi(request_id: UUID, body: PiProposalInput, expected=Depends(expected_version),
               actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.pi_amendment_service import create
    return _pi_command(db, actor, request_id, expected, body, create)


@router.post("/orders/{request_id}/publish-pi")
def publish_pi(request_id: UUID, body: PublishPiInput, expected=Depends(expected_version),
               actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.pi_amendment_service import publish
    return _pi_command(db, actor, request_id, expected, body, publish)


@router.post("/orders/{request_id}/reject")
def reject_order(request_id: UUID, body: ReasonInput, expected=Depends(expected_version),
                 actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.order_rejection_service import reject_request
    return _pi_command(db, actor, request_id, expected, body, reject_request)


@router.post("/orders/{request_id}/void-pi")
def void_pi(request_id: UUID, body: VoidPiInput, expected=Depends(expected_version),
            actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.pi_void_service import void
    return _pi_command(db, actor, request_id, expected, body, void)



@router.get("/orders/{request_id}/audit")
def order_audit(request_id: UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.audit_query_service import list_events
    data = list_events(db, actor, request_id, page=page, page_size=page_size)
    db.commit()
    return ok(data)


@router.get("/orders/{request_id}/notifications")
def order_notifications(request_id: UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                        actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.notification_admin_service import list_events
    data = list_events(db, actor, request_id, page=page, page_size=page_size)
    db.commit()
    return ok(data)


@router.post("/orders/{request_id}/notifications/{event_id}/retry")
def retry_notification(request_id: UUID, event_id: UUID, body: NotificationRetryInput,
                       command_key=Depends(idempotency_key), actor=Depends(_require_portal_employee),
                       db: Session = Depends(get_db)):
    from app.portal.notification_admin_service import retry
    data = retry(db, actor, request_id, event_id, command_key, body)
    db.commit()
    return ok(data)


@router.get("/image-assets")
def image_assets(keyword: str = Query('', max_length=100), page: int = Query(1, ge=1),
                 page_size: int = Query(20, ge=1, le=100), actor=Depends(_require_portal_employee),
                 db: Session = Depends(get_db)):
    from app.portal.image_service import list_assets
    data = list_assets(db, actor, keyword=keyword, page=page, page_size=page_size)
    db.commit()
    return ok(data)


@router.patch("/catalog/{item_id}/image")
def bind_catalog_image(item_id: UUID, body: CatalogImageInput, expected=Depends(expected_version),
                       actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from app.portal.image_service import bind
    data = bind(db, actor, item_id, expected, body)
    db.commit()
    return ok(data)


@router.get("/image-assets/{asset_id}/preview")
def preview_image_asset(asset_id: int, actor=Depends(_require_portal_employee), db: Session = Depends(get_db)):
    from fastapi.responses import Response
    from app.portal.image_service import admin_preview
    content, reference = admin_preview(db, actor, asset_id)
    return Response(content, media_type='image/jpeg', headers={'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff', 'X-Portal-Image-Reference': reference})
