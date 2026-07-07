"""FastAPI router for order invoice management."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.invoice import export_service, product_service, service, xiaoman_service
from app.invoice.schemas import InvoiceCreate, InvoiceUpdate

router = APIRouter()


def _user_id(current_user) -> int | None:
    if isinstance(current_user, dict):
        return current_user.get("id")
    return getattr(current_user, "id", None)


@router.get("/customers/search", summary="Search invoice customers")
def search_customers(
    keyword: str | None = Query(None),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission("invoice:read", "invoice:write")),
):
    return {"items": product_service.search_customers(db, keyword=keyword, limit=limit)}


@router.get("/products/filter-options", summary="Cascading product filter options")
def get_product_filter_options(
    model: str | None = Query(None),
    color: str | None = Query(None),
    size: str | None = Query(None),
    unit: str | None = Query(None),
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission("invoice:read", "invoice:write")),
):
    return product_service.get_filter_options(db, model=model, color=color, size=size, unit=unit)


@router.get("/products/match", summary="Match one product by model/color/size/unit")
def match_product(
    model: str = Query(...),
    color: str = Query(...),
    size: str = Query(...),
    unit: str = Query(...),
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission("invoice:read", "invoice:write")),
):
    return product_service.match_product(db, model=model, color=color, size=size, unit=unit)


@router.get("/invoices", summary="Invoice list")
def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:read")),
):
    items, total = service.list_invoices(db, page=page, page_size=page_size, keyword=keyword, status=status)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.post("/invoices", summary="Create invoice", status_code=201)
def create_invoice(
    body: InvoiceCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("invoice:write")),
):
    invoice = service.create_invoice(db, body, user_id=_user_id(current_user))
    db.commit()
    db.refresh(invoice)
    invoice = service.get_invoice(db, invoice.id)
    return service.serialize_detail(invoice)


@router.get("/invoices/{invoice_id}", summary="Invoice detail")
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:read")),
):
    invoice = service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(404, "发票不存在")
    return service.serialize_detail(invoice)


@router.put("/invoices/{invoice_id}", summary="Update invoice")
def update_invoice(
    invoice_id: int,
    body: InvoiceUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("invoice:write")),
):
    invoice = service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(404, "发票不存在")
    invoice = service.update_invoice(db, invoice, body, user_id=_user_id(current_user))
    db.commit()
    invoice = service.get_invoice(db, invoice.id)
    return service.serialize_detail(invoice)


@router.post("/invoices/{invoice_id}/validate", summary="Validate invoice before sync")
def validate_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission("invoice:read", "invoice:write")),
):
    invoice = service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(404, "发票不存在")
    issues = service.mark_ready_if_valid(invoice)
    db.commit()
    return {"ok": not issues, "issues": issues}


@router.post("/invoices/{invoice_id}/sync", summary="Sync invoice to Xiaoman")
def sync_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:sync")),
):
    invoice = service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(404, "发票不存在")
    result = xiaoman_service.sync_invoice(invoice)
    db.commit()
    return result


@router.get("/invoices/{invoice_id}/export/excel", summary="Export invoice Excel")
def export_excel(
    invoice_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:read")),
):
    invoice = service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(404, "发票不存在")
    stream = export_service.build_invoice_workbook(invoice)
    filename = quote(f"{invoice.invoice_no}.xlsx")
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/invoices/{invoice_id}/export/print", summary="Printable invoice HTML")
def export_print_html(
    invoice_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:read")),
):
    invoice = service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(404, "发票不存在")
    return HTMLResponse(export_service.build_print_html(invoice))


@router.get("/invoices/{invoice_id}/export/pdf", summary="Export invoice PDF")
def export_pdf(
    invoice_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:read")),
):
    invoice = service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(404, "发票不存在")
    stream = export_service.build_invoice_pdf(invoice)
    filename = quote(f"{invoice.invoice_no}.pdf")
    return StreamingResponse(
        stream,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
