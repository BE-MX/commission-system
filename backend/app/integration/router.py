"""Integration App administration and public invoice-integration routes."""

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import JSONResponse
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
    ProductResolutionRequest,
)


router = APIRouter()
# Machine-to-machine endpoints use a revocable Integration App token rather
# than a user JWT. The factory still rechecks the bound user's current scope.
_require_invoice_integration = require_integration_scope("invoice:write")


def _validation_error(exc: validation_service.InvoiceValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": 422,
            "message": "invoice validation failed",
            "data": {"issues": exc.issues, "warnings": exc.warnings},
        },
    )


@router.post("/v1/customers/resolve", summary="Resolve one existing OKKI customer exactly")
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


@router.post("/v1/products/resolve", summary="Resolve one active catalog product exactly")
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


@router.post("/v1/invoices/validate", summary="Validate an invoice submission without writes")
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
