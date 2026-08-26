"""Integration App administration and public invoice-integration routes."""

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
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
    CustomerSubmission,
    IntegrationAppCreate,
    IntegrationAppRotate,
    InvoiceSubmission,
    InvoiceValidationErrorEnvelope,
    ProductResolutionRequest,
)


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


class IntegrationValidationRoute(APIRoute):
    """Normalize schema failures only for public Integration App endpoints."""

    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def validation_envelope_handler(request: Request):
            try:
                return await original_handler(request)
            except RequestValidationError as exc:
                return _request_validation_error(exc)

        return validation_envelope_handler


public_router = APIRouter(route_class=IntegrationValidationRoute)
_VALIDATION_RESPONSES = {
    422: {
        "model": InvoiceValidationErrorEnvelope,
        "description": "Stable external invoice validation envelope",
    },
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
    summary="Validate an invoice submission without writes",
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
