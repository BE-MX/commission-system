"""Separate machine and ai:admin routes with a bounded JSON reader."""

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.ai_gateway import admin_service, service
from app.ai_gateway.auth import require_app_key
from app.ai_gateway.errors import GatewayError, report_failure
from app.ai_gateway.schemas import AppCreate, AppPatch, ChatRequest, ResolveRequest


class GatewayRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def wrapped(request):
            try:
                response = await handler(request)
                response.headers["Cache-Control"] = "no-store"
                return response
            except GatewayError as exc:
                return exc.response(getattr(request.state, "gateway_request_id", None))
            except HTTPException as exc:
                return GatewayError(exc.status_code, "access_denied", "无权访问此接口").response()
            except (RequestValidationError, ValidationError):
                return GatewayError(422, "invalid_request", "请求参数不符合接口要求").response(
                    getattr(request.state, "gateway_request_id", None))
            except Exception as exc:
                report_failure(exc, getattr(request.state, "gateway_request_id", None))
                return GatewayError(503, "gateway_unavailable", "服务暂不可用，请勿自动重试").response(
                    getattr(request.state, "gateway_request_id", None))
        return wrapped


# Machine-to-machine endpoint: require_app_key + database application checks;
# intentionally no employee JWT permission, never shares the admin router.
router = APIRouter(route_class=GatewayRoute)
admin_router = APIRouter(route_class=GatewayRoute, dependencies=[Depends(require_permission("ai:admin"))])


@router.post("/chat")
async def chat(request: Request, key_hash: str = Depends(require_app_key), db: Session = Depends(get_db)):
    raw_id = request.headers.get("X-Request-ID", "")
    try:
        request_id = str(UUID(raw_id))
    except ValueError:
        raise GatewayError(422, "invalid_request", "X-Request-ID 必须是 UUID") from None
    request.state.gateway_request_id = request_id
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise GatewayError(422, "invalid_request", "请使用 application/json")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 65536:
            raise GatewayError(413, "payload_too_large", "请求体不能超过 64 KiB")
        body.extend(chunk)
    data = ChatRequest.model_validate_json(bytes(body))
    result = await run_in_threadpool(service.invoke, db, key_hash, request_id, data)
    return ok(result, code=0)


def admin_action(db, action, *args, **kwargs):
    try:
        return ok(action(db, *args, **kwargs))
    except Exception:
        db.rollback()
        raise


@admin_router.get("/options")
def options(db: Session = Depends(get_db)):
    return admin_action(db, admin_service.options)


@admin_router.get("/apps")
def list_apps(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
              search: str = Query("", max_length=100), db: Session = Depends(get_db)):
    return admin_action(db, admin_service.list_apps, page, page_size, search)


@admin_router.post("/apps")
def create_app(data: AppCreate, db: Session = Depends(get_db), actor=Depends(require_permission("ai:admin"))):
    return admin_action(db, admin_service.create_app, data, int(actor["sub"]))


@admin_router.get("/apps/{app_id}")
def get_app(app_id: int, db: Session = Depends(get_db)):
    return admin_action(db, admin_service.get_app, app_id)


@admin_router.patch("/apps/{app_id}")
def update_app(app_id: int, data: AppPatch, db: Session = Depends(get_db), actor=Depends(require_permission("ai:admin"))):
    return admin_action(db, admin_service.update_app, app_id, data, int(actor["sub"]))


@admin_router.post("/apps/{app_id}/rotate-key")
def rotate_key(app_id: int, db: Session = Depends(get_db), actor=Depends(require_permission("ai:admin"))):
    return admin_action(db, admin_service.rotate_key, app_id, int(actor["sub"]))


@admin_router.get("/apps/{app_id}/requests")
def list_requests(app_id: int, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                  status: Literal["pending", "success", "error", "timeout", "unknown"] | None = None,
                  date_from: date | None = None, date_to: date | None = None, db: Session = Depends(get_db)):
    if date_from and date_to and date_from > date_to:
        raise GatewayError(422, "invalid_request", "开始日期不能晚于结束日期")
    return admin_action(db, admin_service.list_requests, app_id, page, page_size, status, date_from, date_to)


@admin_router.post("/apps/{app_id}/requests/{request_id}/resolve")
def resolve(app_id: int, request_id: UUID, data: ResolveRequest, db: Session = Depends(get_db),
            actor=Depends(require_permission("ai:admin"))):
    return admin_action(db, admin_service.resolve_request, app_id, str(request_id), data.reason, int(actor["sub"]))
