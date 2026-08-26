"""Integration App administration and public invoice-integration routes."""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import ok
from app.integration.auth import (
    SubmissionPrincipal,
    require_integration_scope,
    require_permission_current_integration_admin,
)
from app.integration import service, validation_service
from app.integration.schemas import (
    CustomerResolveSuccessEnvelope,
    CustomerSubmission,
    ExternalErrorEnvelope,
    IntegrationAppCreate,
    IntegrationAppRotate,
    InvoiceConflictEnvelope,
    InvoiceCreatedEnvelope,
    InvoiceCreateValidationErrorEnvelope,
    InvoiceReplayedEnvelope,
    InvoiceSubmission,
    InvoiceValidationErrorEnvelope,
    InvoiceValidationSuccessEnvelope,
    ProductResolveSuccessEnvelope,
    ProductResolutionRequest,
)


logger = logging.getLogger(__name__)
router = APIRouter()
# Machine-to-machine endpoints use a revocable Integration App token rather
# than a user JWT. The factory still rechecks the bound user's current scope.
_require_invoice_integration = require_integration_scope("invoice:write")


def _field_path(location: tuple) -> str:
    parts = list(location)
    if parts and parts[0] in {"body", "query", "path", "header", "cookie"}:
        parts.pop(0)
    result = ""
    for part in parts:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result += ("." if result else "") + str(part)
    return result or "request"


_SCHEMA_ERROR_MESSAGES = {
    "missing": "必填字段缺失，请补充该字段",
    "extra_forbidden": "接口不接受该字段，请删除后重试",
    "literal_error": "字段值不在允许范围，请按接口契约选择",
    "string_pattern_mismatch": "字段格式不符合要求，请按接口契约修正",
    "string_too_short": "字段长度过短，请按接口契约补充内容",
    "string_too_long": "字段长度过长，请按接口契约缩短内容",
    "too_short": "列表项数量不足，请按接口契约补充",
    "too_long": "列表项数量过多，请减少后重试",
    "greater_than": "数值必须大于接口规定的下限",
    "greater_than_equal": "数值不能低于接口规定的下限",
    "less_than": "数值必须小于接口规定的上限",
    "less_than_equal": "数值不能超过接口规定的上限",
    "int_type": "字段必须使用整数，请修正后重试",
    "int_parsing": "字段必须使用整数，请修正后重试",
    "int_from_float": "字段必须使用整数，请删除小数部分",
    "decimal_type": "金额必须使用合法十进制字符串",
    "decimal_parsing": "金额必须使用合法十进制字符串",
    "decimal_max_places": "金额小数位超过允许范围，请减少小数位",
    "decimal_whole_digits": "金额整数位超过允许范围，请缩小金额",
    "decimal_max_digits": "金额位数超过允许范围，请缩小金额",
    "finite_number": "金额必须是有限十进制字符串",
    "date_type": "日期必须使用 YYYY-MM-DD 格式",
    "date_parsing": "日期格式无效，请使用 YYYY-MM-DD",
    "date_from_datetime_parsing": "日期格式无效，请使用 YYYY-MM-DD",
    "date_from_datetime_inexact": "日期不能包含时间，请使用 YYYY-MM-DD",
    "string_type": "字段必须使用字符串，请修正后重试",
}


def _schema_error_message(error: dict, field: str) -> str:
    error_type = str(error.get("type") or "")
    mapped = _SCHEMA_ERROR_MESSAGES.get(error_type)
    if mapped:
        return mapped
    if error_type == "value_error":
        if field == "invoice_date":
            return "日期必须使用 YYYY-MM-DD 格式且为有效日期"
        raw_message = str(error.get("msg") or "")
        prefix = "Value error, "
        detail = raw_message[len(prefix):] if raw_message.startswith(prefix) else raw_message
        if any("\u4e00" <= character <= "\u9fff" for character in detail):
            return detail
    return "字段值无效，请按接口契约修正"


def _request_validation_error(exc: RequestValidationError) -> JSONResponse:
    issues = []
    for error in exc.errors():
        field = _field_path(tuple(error.get("loc") or ()))
        issues.append({
            "code": "SCHEMA_INVALID",
            "field": field,
            "message": _schema_error_message(error, field),
        })
    return JSONResponse(
        status_code=422,
        content={
            "code": 422,
            "message": "invoice validation failed",
            "data": {"issues": issues, "warnings": []},
        },
    )


_EXTERNAL_ORDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def _external_error_response(
    *,
    status_code: int,
    error_code: str,
    message: str,
    field: str,
    action: str,
    external_order_id: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    data = {"error_code": error_code, "field": field, "action": action}
    if external_order_id is not None:
        data["external_order_id"] = external_order_id
    return JSONResponse(
        status_code=status_code,
        content={"code": status_code, "message": message, "data": data},
        headers=headers,
    )


def _http_error_response(
    exc: HTTPException,
    *,
    external_order_id: str | None = None,
) -> JSONResponse:
    errors = {
        401: (
            "AUTHENTICATION_FAILED",
            "integration authentication failed",
            "authorization",
            "请检查服务端 Integration App Token 后重试",
        ),
        403: (
            "INTEGRATION_PERMISSION_DENIED",
            "integration permission denied",
            "authorization",
            "请联系管理员检查 Integration App scope 和绑定用户权限后重试",
        ),
        429: (
            "RATE_LIMITED",
            "integration request rate limited",
            "request",
            "请求过于频繁，请稍后使用相同 external_order_id 重试",
        ),
        503: (
            "SERVICE_UNAVAILABLE",
            "integration service unavailable",
            "request",
            "服务暂不可用，请稍后使用相同 external_order_id 查询或重试",
        ),
    }
    error_code, message, field, action = errors[exc.status_code]
    return _external_error_response(
        status_code=exc.status_code,
        error_code=error_code,
        message=message,
        field=field,
        action=action,
        external_order_id=external_order_id,
        headers=exc.headers,
    )


async def _external_order_id_from_request(request: Request) -> str | None:
    value = request.path_params.get("external_order_id")
    if value is None:
        try:
            body = await request.json()
        except (ValueError, RuntimeError):
            return None
        if isinstance(body, dict):
            value = body.get("external_order_id")
    if isinstance(value, str) and _EXTERNAL_ORDER_ID_PATTERN.fullmatch(value):
        return value
    return None


class IntegrationValidationRoute(APIRoute):
    """Normalize public Integration App failures without affecting admin routes."""

    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def validation_envelope_handler(request: Request):
            try:
                return await original_handler(request)
            except RequestValidationError as exc:
                return _request_validation_error(exc)
            except HTTPException as exc:
                if exc.status_code not in {401, 403, 429, 503}:
                    raise
                return _http_error_response(
                    exc,
                    external_order_id=await _external_order_id_from_request(request),
                )
            except OperationalError as exc:
                external_order_id = await _external_order_id_from_request(request)
                error_type = type(exc).__name__
                logger.error(
                    "Public integration dependency unavailable error_type=%s "
                    "external_order_id=%s",
                    error_type,
                    external_order_id or "-",
                )
                print(
                    "[integration] dependency unavailable "
                    f"error_type={error_type} "
                    f"external_order_id={external_order_id or '-'}",
                    flush=True,
                )
                return _external_error_response(
                    status_code=503,
                    error_code="SERVICE_UNAVAILABLE",
                    message="integration service unavailable",
                    field="request",
                    action="服务暂不可用，请稍后使用相同 external_order_id 查询或重试",
                    external_order_id=external_order_id,
                )
            except Exception as exc:
                external_order_id = await _external_order_id_from_request(request)
                error_type = type(exc).__name__
                logger.error(
                    "Unexpected public integration failure error_type=%s "
                    "external_order_id=%s",
                    error_type,
                    external_order_id or "-",
                )
                print(
                    "[integration] unexpected request failure "
                    f"error_type={error_type} "
                    f"external_order_id={external_order_id or '-'}",
                    flush=True,
                )
                return _external_error_response(
                    status_code=500,
                    error_code="INTERNAL_ERROR",
                    message="internal error",
                    field="request",
                    action="请保持相同 external_order_id 查询结果或重试",
                    external_order_id=external_order_id,
                )

        return validation_envelope_handler


public_router = APIRouter(route_class=IntegrationValidationRoute)
_PUBLIC_ERROR_RESPONSES = {
    401: {"model": ExternalErrorEnvelope, "description": "Authentication failed"},
    403: {"model": ExternalErrorEnvelope, "description": "Integration permission denied"},
    429: {"model": ExternalErrorEnvelope, "description": "Request rate limited"},
    500: {"model": ExternalErrorEnvelope, "description": "Unexpected server error"},
    503: {"model": ExternalErrorEnvelope, "description": "Dependency unavailable"},
}
_VALIDATION_RESPONSES = {
    **_PUBLIC_ERROR_RESPONSES,
    422: {
        "model": InvoiceValidationErrorEnvelope,
        "description": "Stable external invoice validation envelope",
    },
}
_CREATE_RESPONSES = {
    **_PUBLIC_ERROR_RESPONSES,
    200: {"model": InvoiceReplayedEnvelope, "description": "Idempotent replay"},
    409: {"model": InvoiceConflictEnvelope, "description": "External order conflict or processing"},
    422: {"model": InvoiceCreateValidationErrorEnvelope, "description": "Stable create rejection"},
}
_LOOKUP_RESPONSES = {
    **_PUBLIC_ERROR_RESPONSES,
    404: {"model": ExternalErrorEnvelope, "description": "No result in this App namespace"},
    409: {"model": InvoiceConflictEnvelope, "description": "Request is still processing"},
    422: {"model": InvoiceCreateValidationErrorEnvelope, "description": "Original stable rejection"},
}


def _validation_error(exc: validation_service.InvoiceValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": 422,
            "message": "invoice validation failed",
            "data": {"issues": exc.issues, "warnings": exc.warnings},
        },
    )


@public_router.post(
    "/v1/customers/resolve",
    summary="Resolve one existing OKKI customer exactly",
    response_model=CustomerResolveSuccessEnvelope,
    responses=_VALIDATION_RESPONSES,
)
def post_resolve_customer(
    request: CustomerSubmission,
    db: Session = Depends(get_db),
    _: SubmissionPrincipal = Depends(_require_invoice_integration),
):
    try:
        customer = validation_service.resolve_customer(db, request)
    except validation_service.InvoiceValidationError as exc:
        return _validation_error(exc)
    return ok({"customer": customer})


@public_router.post(
    "/v1/products/resolve",
    summary="Resolve one active catalog product exactly",
    response_model=ProductResolveSuccessEnvelope,
    responses=_VALIDATION_RESPONSES,
)
def post_resolve_product(
    request: ProductResolutionRequest,
    db: Session = Depends(get_db),
    _: SubmissionPrincipal = Depends(_require_invoice_integration),
):
    try:
        item = validation_service.resolve_product(db, request)
    except validation_service.InvoiceValidationError as exc:
        return _validation_error(exc)
    return ok({"item": item})


@public_router.post(
    "/v1/invoices/validate",
    summary="Validate without creating invoice/ingest records",
    response_model=InvoiceValidationSuccessEnvelope,
    responses=_VALIDATION_RESPONSES,
)
def post_validate_invoice(
    request: InvoiceSubmission,
    db: Session = Depends(get_db),
    _: SubmissionPrincipal = Depends(_require_invoice_integration),
):
    try:
        data = validation_service.validate_submission(db, request)
    except validation_service.InvoiceValidationError as exc:
        return _validation_error(exc)
    return ok(data)


def _create_validation_error(exc: service.ExternalInvoiceRejected) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": 422,
            "message": "invoice validation failed",
            "data": {
                "request_id": exc.row.public_id,
                "issues": exc.issues,
                "warnings": exc.warnings,
            },
        },
    )


def _conflict(row, *, changed: bool) -> JSONResponse:
    if changed:
        content = {
            "code": 409,
            "message": "external order conflict",
            "data": {
                "request_id": row.public_id,
                "external_order_id": row.external_order_id,
                "error_code": "EXTERNAL_ORDER_CHANGED",
                "action": "已创建订单内容不可覆盖，请为新订单使用新的 external_order_id",
            },
        }
    else:
        content = {
            "code": 409,
            "message": "external invoice processing",
            "data": {
                "request_id": row.public_id,
                "external_order_id": row.external_order_id,
                "error_code": "INVOICE_PROCESSING",
                "action": "请求正在处理，请稍后使用相同 external_order_id 重试或查询结果",
            },
        }
    return JSONResponse(status_code=409, content=content)


@public_router.post(
    "/v1/invoices",
    summary="Create one local Ark invoice idempotently",
    status_code=201,
    response_model=InvoiceCreatedEnvelope,
    responses=_CREATE_RESPONSES,
)
def post_create_invoice(
    request: InvoiceSubmission,
    response: Response,
    db: Session = Depends(get_db),
    principal: SubmissionPrincipal = Depends(_require_invoice_integration),
):
    try:
        data, replayed = service.create_external_invoice(db, request, principal)
    except service.ExternalOrderChanged as exc:
        return _conflict(exc.row, changed=True)
    except service.ExternalInvoiceProcessing as exc:
        return _conflict(exc.row, changed=False)
    except service.ExternalInvoiceRejected as exc:
        return _create_validation_error(exc)
    if replayed:
        return JSONResponse(
            status_code=200,
            content={"code": 200, "message": "invoice replayed", "data": data},
        )
    response.status_code = 201
    return {"code": 201, "message": "invoice created", "data": data}


@public_router.get(
    "/v1/invoices/by-external-id/{external_order_id}",
    summary="Recover one invoice result in the current App namespace",
    response_model=InvoiceReplayedEnvelope,
    responses=_LOOKUP_RESPONSES,
)
def get_invoice_by_external_id(
    external_order_id: str = Path(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
    db: Session = Depends(get_db),
    principal: SubmissionPrincipal = Depends(_require_invoice_integration),
):
    result_type, result = service.get_external_invoice_result(
        db,
        external_order_id,
        principal,
    )
    if result_type == "not_found":
        return _external_error_response(
            status_code=404,
            error_code="EXTERNAL_INVOICE_NOT_FOUND",
            message="external invoice not found",
            field="external_order_id",
            external_order_id=external_order_id,
            action="确认订单号和站点凭证后重试",
        )
    if result_type == "processing":
        return _conflict(result, changed=False)
    if result_type == "rejected":
        return JSONResponse(
            status_code=422,
            content={"code": 422, "message": "invoice validation failed", "data": result},
        )
    return {"code": 200, "message": "invoice replayed", "data": result}


router.include_router(public_router)


@router.get("/admin/user-candidates", summary="Search eligible Integration App owners")
def get_user_candidates(
    q: str = Query(default="", max_length=50),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission_current_integration_admin),
):
    return ok({"items": service.list_user_candidates(db, q=q, limit=limit)})


@router.get("/admin/apps", summary="List Integration Apps without secret material")
def get_apps(
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission_current_integration_admin),
):
    items = service.list_apps(db)
    return ok({"total": len(items), "items": items})


@router.post("/admin/apps", summary="Create Integration App and return its token once")
def post_app(
    request: IntegrationAppCreate,
    db: Session = Depends(get_db),
    operator: dict = Depends(require_permission_current_integration_admin),
):
    return ok(service.create_app(db, request, created_by=int(operator["sub"])))


@router.post("/admin/apps/{app_id}/rotate", summary="Atomically rotate an Integration App token")
def post_rotate_app(
    request: IntegrationAppRotate,
    app_id: int = Path(ge=1),
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission_current_integration_admin),
):
    return ok(service.rotate_app_token(
        db,
        app_id,
        current_token_suffix=request.current_token_suffix,
    ))


@router.delete("/admin/apps/{app_id}", summary="Idempotently revoke an Integration App")
def delete_app(
    app_id: int = Path(ge=1),
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission_current_integration_admin),
):
    return ok(service.revoke_app(db, app_id), message="已吊销")
