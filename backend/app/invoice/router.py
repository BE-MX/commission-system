"""FastAPI router for order invoice management."""

from decimal import Decimal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok
from app.invoice import export_service, price_service, product_service, service, xiaoman_service
from app.invoice.schemas import InvoiceCreate, InvoiceUpdate

router = APIRouter()

_READ_OR_WRITE = require_any_permission("invoice:read", "invoice:write")


def _user_id(current_user) -> int | None:
    if isinstance(current_user, dict):
        return current_user.get("id")
    return getattr(current_user, "id", None)


# ── customers / products ─────────────────────────────────────

@router.get("/customers/search", summary="Search invoice customers")
def search_customers(
    keyword: str | None = Query(None),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    _user=Depends(_READ_OR_WRITE),
):
    return ok({"items": product_service.search_customers(db, keyword=keyword, limit=limit)})


@router.get("/products/filter-options", summary="Cascading product filter options")
def get_product_filter_options(
    model: str | None = Query(None),
    color: str | None = Query(None),
    size: str | None = Query(None),
    unit: str | None = Query(None),
    db: Session = Depends(get_db),
    _user=Depends(_READ_OR_WRITE),
):
    return ok(product_service.get_filter_options(db, model=model, color=color, size=size, unit=unit))


@router.get("/products/match", summary="Match one product by model/color/size/unit")
def match_product(
    model: str = Query(...),
    color: str = Query(...),
    size: str = Query(...),
    unit: str = Query(...),
    db: Session = Depends(get_db),
    _user=Depends(_READ_OR_WRITE),
):
    return ok(product_service.match_product(db, model=model, color=color, size=size, unit=unit))


@router.get("/products/entry-options", summary="Candidates for free-form production entry")
def get_entry_options(
    db: Session = Depends(get_db),
    _user=Depends(_READ_OR_WRITE),
):
    return ok(product_service.get_entry_options(db))


@router.get("/custom-products", summary="List sunk custom products")
def list_custom_products(
    keyword: str | None = Query(None),
    db: Session = Depends(get_db),
    _user=Depends(_READ_OR_WRITE),
):
    return ok({"items": product_service.list_custom_products(db, keyword=keyword)})


@router.post("/custom-products/reconcile", summary="Backfill okki IDs for custom products")
def reconcile_custom_products(
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:admin")),
):
    result = product_service.reconcile_custom_products(db)
    db.commit()
    return ok(result)


# ── pricing ──────────────────────────────────────────────────

@router.get("/price/resolve", summary="Resolve standard + customer price for a line")
def resolve_price(
    customer_id: str | None = Query(None),
    product_display: str = Query(...),
    length: str = Query(...),
    unit: str = Query(...),
    color: str = Query(...),
    db: Session = Depends(get_db),
    _user=Depends(_READ_OR_WRITE),
):
    return ok(price_service.resolve_price(
        db,
        customer_id=customer_id,
        product_display=product_display,
        length=length,
        unit=unit,
        color=color,
    ))


@router.get("/price/std", summary="List standard price matrix")
def list_std_prices(
    series_grade: str | None = Query(None),
    db: Session = Depends(get_db),
    _user=Depends(_READ_OR_WRITE),
):
    return ok({"items": price_service.list_std_prices(db, series_grade=series_grade)})


class StdPricePayload(BaseModel):
    id: int | None = None
    series_grade: str = Field(..., max_length=128)
    length: str = Field(..., max_length=32)
    weight_unit: str = Field(..., max_length=32)
    color_type: str = Field(..., pattern="^(solid|piano|ombre|balayage)$")
    price: Decimal = Field(..., ge=0)
    currency: str = Field(default="USD", max_length=8)


@router.post("/price/std", summary="Create/update one standard price cell")
def upsert_std_price(
    body: StdPricePayload,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("invoice:admin")),
):
    try:
        price_service.upsert_std_price(
            db,
            series_grade=body.series_grade,
            length=body.length,
            weight_unit=body.weight_unit,
            color_type=body.color_type,
            price=body.price,
            currency=body.currency,
            user_id=_user_id(current_user),
            price_id=body.id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return ok(message="已保存")


@router.delete("/price/std/{price_id}", summary="Delete one standard price cell")
def delete_std_price(
    price_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:admin")),
):
    if not price_service.delete_std_price(db, price_id):
        raise HTTPException(404, "价格记录不存在")
    db.commit()
    return ok(message="已删除")


@router.post("/price/import", summary="Import the business price workbook (价格表+颜色对照表)")
def import_price_workbook(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("invoice:admin")),
):
    content = file.file.read()
    result = price_service.import_price_workbook(db, content, user_id=_user_id(current_user))
    db.commit()
    return ok(result)


@router.get("/price/color-types", summary="List color type mapping")
def list_color_types(
    db: Session = Depends(get_db),
    _user=Depends(_READ_OR_WRITE),
):
    return ok({"items": price_service.list_color_types(db)})


class ColorTypePayload(BaseModel):
    color_code: str = Field(..., max_length=64)
    color_type: str = Field(..., pattern="^(solid|piano|ombre|balayage)$")


@router.post("/price/color-types", summary="Create/update a color type mapping")
def upsert_color_type(
    body: ColorTypePayload,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:admin")),
):
    price_service.upsert_color_type(db, color_code=body.color_code, color_type=body.color_type)
    db.commit()
    return ok(message="已保存")


@router.delete("/price/color-types/{entry_id}", summary="Delete a color type mapping")
def delete_color_type(
    entry_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:admin")),
):
    if not price_service.delete_color_type(db, entry_id):
        raise HTTPException(404, "映射不存在")
    db.commit()
    return ok(message="已删除")


@router.get("/price/customer-rules", summary="List customer price rules")
def list_customer_rules(
    keyword: str | None = Query(None),
    db: Session = Depends(get_db),
    _user=Depends(_READ_OR_WRITE),
):
    return ok({"items": price_service.list_customer_rules(db, keyword=keyword)})


@router.get("/price/customer-rules/by-customer/{customer_id}", summary="Rule for one customer")
def get_customer_rule(
    customer_id: str,
    db: Session = Depends(get_db),
    _user=Depends(_READ_OR_WRITE),
):
    return ok(price_service.get_customer_rule(db, customer_id))


class CustomerRulePayload(BaseModel):
    customer_id: str = Field(..., max_length=64)
    customer_name: str | None = Field(None, max_length=256)
    adjust_type: str = Field(..., pattern="^(fixed|percent)$")
    adjust_value: Decimal
    enabled: bool = True
    preferred_template: str | None = Field(None, max_length=8)
    remark: str | None = Field(None, max_length=512)


@router.post("/price/customer-rules", summary="Create/update a customer price rule")
def upsert_customer_rule(
    body: CustomerRulePayload,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("invoice:admin")),
):
    price_service.upsert_customer_rule(
        db,
        customer_id=body.customer_id,
        customer_name=body.customer_name,
        adjust_type=body.adjust_type,
        adjust_value=body.adjust_value,
        enabled=body.enabled,
        preferred_template=body.preferred_template,
        remark=body.remark,
        user_id=_user_id(current_user),
    )
    db.commit()
    return ok(message="已保存")


@router.delete("/price/customer-rules/{rule_id}", summary="Delete a customer price rule")
def delete_customer_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:admin")),
):
    if not price_service.delete_customer_rule(db, rule_id):
        raise HTTPException(404, "规则不存在")
    db.commit()
    return ok(message="已删除")


# ── invoices ─────────────────────────────────────────────────

@router.get("/invoices", summary="Invoice list")
def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None),
    status: str | None = Query(None),
    order_type: str | None = Query(None, pattern="^(stock|production)$"),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:read")),
):
    items, total = service.list_invoices(
        db, page=page, page_size=page_size, keyword=keyword, status=status, order_type=order_type
    )
    return ok({"total": total, "page": page, "page_size": page_size, "items": items})


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
    return ok(service.serialize_detail(invoice))


@router.get("/invoices/{invoice_id}", summary="Invoice detail")
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:read")),
):
    invoice = service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(404, "发票不存在")
    return ok(service.serialize_detail(invoice))


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
    return ok(service.serialize_detail(invoice))


@router.post("/invoices/{invoice_id}/validate", summary="Validate invoice before sync")
def validate_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    # mutates invoice.status -> read-only users must not reach it
    _user=Depends(require_any_permission("invoice:write", "invoice:sync")),
):
    invoice = service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(404, "发票不存在")
    issues = service.mark_ready_if_valid(invoice)
    db.commit()
    return ok({"ok": not issues, "issues": issues})


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
    return ok(result)


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
