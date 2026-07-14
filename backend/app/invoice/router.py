"""FastAPI router for order invoice management."""

import logging
from datetime import datetime
from decimal import Decimal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok
from app.invoice import (
    export_service,
    import_service,
    okki_client,
    price_service,
    product_service,
    receipt_repair_service,
    service,
    xiaoman_service,
)
from app.invoice.schemas import InvoiceCreate, InvoiceImportPreviewRequest, InvoiceUpdate

logger = logging.getLogger(__name__)

router = APIRouter()

_READ_OR_WRITE = require_any_permission("invoice:read", "invoice:write")
# 价格与产品配置页读端点（063 拆分）：页面码 + 旧读写码兼容（发票编辑器也调这批端点）
_PRICE_PAGE_READ = require_any_permission("invoice_price:read", "invoice:read", "invoice:write")


def _user_id(current_user) -> int | None:
    # JWT payload 的用户 ID 在 "sub"（字符串）——原先只取 "id" 导致
    # created_by/operator_id 长期写 NULL（2026-07-13 修复）
    if isinstance(current_user, dict):
        raw = current_user.get("id") or current_user.get("sub")
    else:
        raw = getattr(current_user, "id", None)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _can_read_all(current_user) -> bool:
    """invoice:read_all / super_admin → 全量数据范围，其余只看自己创建的发票"""
    if not isinstance(current_user, dict):
        return False
    return (
        "invoice:read_all" in current_user.get("permissions", [])
        or "super_admin" in current_user.get("roles", [])
    )


def _ensure_invoice_visible(invoice, current_user) -> None:
    """数据范围守卫：不可见的发票按不存在处理（防拿 ID 探测，tracking 同口径）。

    created_by 为 NULL 的历史发票只有 read_all/super_admin 可见。
    """
    if _can_read_all(current_user):
        return
    if invoice.created_by != _user_id(current_user) or invoice.created_by is None:
        raise HTTPException(404, "发票不存在")


# ── customers / products ─────────────────────────────────────

def _resolve_private_owner(db: Session, current_user) -> tuple[int | None, bool]:
    """私海筛选的 owner：当前登录用户绑定的 OKKI 账号。

    返回 (okki_user_id, okki_bound)：未绑定时无从判定私海，调用方返回空列表 +
    okki_bound=False，前端据此提示去「系统管理 → 外部账号绑定」。
    """
    okki_user_id = xiaoman_service.resolve_okki_user_id(db, _user_id(current_user))
    return okki_user_id, okki_user_id is not None


@router.get("/customers/search", summary="Search invoice customers")
def search_customers(
    keyword: str | None = Query(None),
    private_only: bool = Query(False, description="仅显示私海客户（owner 含当前用户绑定的 OKKI 账号）"),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user=Depends(_PRICE_PAGE_READ),
):
    owner_okki_id = None
    payload: dict = {}
    if private_only:
        owner_okki_id, bound = _resolve_private_owner(db, current_user)
        if not bound:
            return ok({"items": [], "okki_bound": False})
        # okki_bound 只随私海请求返回：非私海请求不知道绑定状态，回 True 会把
        # 前端「未绑定」提示错误冲掉（对抗性审查 2026-07-14）
        payload["okki_bound"] = True
    payload["items"] = product_service.search_customers(
        db, keyword=keyword, limit=limit, owner_okki_id=owner_okki_id,
    )
    return ok(payload)


@router.get("/customers/contacts", summary="Search customers by contact name")
def search_customer_contacts(
    keyword: str | None = Query(None),
    company_id: str | None = Query(None, max_length=64),
    private_only: bool = Query(False),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    # 联系人含邮箱/电话 PII，口径对齐 contact-defaults：录入场景专用
    current_user=Depends(require_permission("invoice:write")),
):
    owner_okki_id = None
    payload: dict = {}
    if private_only:
        owner_okki_id, bound = _resolve_private_owner(db, current_user)
        if not bound:
            return ok({"items": [], "okki_bound": False})
        payload["okki_bound"] = True  # 同 search：非私海请求不返回该字段
    payload["items"] = product_service.search_customer_contacts(
        db, keyword=keyword, company_id=company_id,
        owner_okki_id=owner_okki_id, limit=limit,
    )
    return ok(payload)


@router.get("/customers/contact-defaults", summary="Latest contact snapshot for a customer")
def get_customer_contact_defaults(
    customer_id: str = Query(..., min_length=1, max_length=64),
    db: Session = Depends(get_db),
    # 录入页自动填充用；组织级共享（客户数据，非发票财务数据），刻意不做数据范围过滤
    _user=Depends(require_permission("invoice:write")),
):
    return ok(service.get_customer_contact_defaults(db, customer_id))


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


@router.post("/import/preview", summary="Preview pasted invoice lines")
def preview_invoice_import(
    body: InvoiceImportPreviewRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:write")),
):
    try:
        result = import_service.preview_import(
            db,
            customer_id=body.customer_id,
            order_type=body.order_type,
            currency=body.currency,
            raw_rows=[row.model_dump() for row in body.rows],
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ok(result)


@router.get("/custom-products", summary="List sunk custom products")
def list_custom_products(
    keyword: str | None = Query(None),
    db: Session = Depends(get_db),
    _user=Depends(_PRICE_PAGE_READ),
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
    _user=Depends(_PRICE_PAGE_READ),
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
    _user=Depends(_PRICE_PAGE_READ),
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
    _user=Depends(_PRICE_PAGE_READ),
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


# ── OKKI push settings ───────────────────────────────────────

class XiaomanSettingsPayload(BaseModel):
    generic_product_no: str | None = Field(None, max_length=64)
    generic_sku_id: int | None = None
    default_order_status: str | None = Field(None, max_length=64)
    default_currency: str = Field("USD", max_length=8)
    # None = 保持现有 token 不变；空字符串 = 清除；其他 = 覆盖
    access_token: str | None = None
    token_expires_at: datetime | None = None


@router.get("/xiaoman/settings", summary="Get OKKI push settings")
def get_xiaoman_settings(
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:admin")),
):
    return ok(xiaoman_service.serialize_settings(xiaoman_service.get_settings_row(db)))


@router.put("/xiaoman/settings", summary="Update OKKI push settings")
def update_xiaoman_settings(
    body: XiaomanSettingsPayload,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("invoice:admin")),
):
    try:
        row = xiaoman_service.update_settings(
            db,
            generic_product_no=body.generic_product_no,
            generic_sku_id=body.generic_sku_id,
            default_order_status=body.default_order_status,
            default_currency=body.default_currency,
            access_token=body.access_token,
            token_expires_at=body.token_expires_at,
            user_id=_user_id(current_user),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return ok(xiaoman_service.serialize_settings(row), message="已保存")


@router.get("/xiaoman/settings/resolve-product", summary="Resolve generic product by product_no")
def resolve_xiaoman_product(
    product_no: str = Query(..., min_length=1, max_length=64),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:admin")),
):
    resolved = xiaoman_service.resolve_generic_product(db, product_no.strip())
    return ok({"found": resolved is not None, "product": resolved})


@router.post("/xiaoman/settings/fetch-token", summary="Fetch OKKI access token via client_credentials")
def fetch_xiaoman_token(
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:admin")),
):
    try:
        okki_client.ensure_access_token(db, force=True)
    except okki_client.OkkiApiError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    row = xiaoman_service.get_settings_row(db)
    return ok(xiaoman_service.serialize_settings(row), message="Token 已获取")


@router.get("/xiaoman/enums", summary="OKKI order enums (status/currency/price contract)")
def get_xiaoman_enums(
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:admin")),
):
    try:
        enums = okki_client.get_order_enums(db)
    except okki_client.OkkiApiError as exc:
        raise HTTPException(400, str(exc))
    db.commit()  # 惰性 token 获取可能更新了 settings 行
    return ok(enums)


# ── invoices ─────────────────────────────────────────────────

@router.get("/invoices", summary="Invoice list")
def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None),
    status: str | None = Query(None),
    order_type: str | None = Query(None, pattern="^(stock|production)$"),
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("invoice:read")),
):
    if _can_read_all(current_user):
        created_by = None  # 全量范围，不过滤
    else:
        created_by = _user_id(current_user)
        if created_by is None:
            # fail-closed：身份解析不出时宁可拒绝，不能落到"不过滤=全量"
            raise HTTPException(403, "无法确认用户身份，禁止访问发票列表")
    items, total = service.list_invoices(
        db, page=page, page_size=page_size, keyword=keyword, status=status, order_type=order_type,
        created_by=created_by,
    )
    return ok({"total": total, "page": page, "page_size": page_size, "items": items})


# 固定路径必须注册在 /invoices/{invoice_id} 之前（cerebrum 2026-05-20：路径参数吞噬）

@router.get("/invoices/suggest-no", summary="Suggested invoice number for a new invoice")
def suggest_invoice_no(
    order_type: str = Query("stock", pattern="^(stock|production)$"),
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("invoice:write")),
):
    return ok({"invoice_no": service.suggest_invoice_no(db, _user_id(current_user), order_type)})


@router.get("/invoices/check-no", summary="Check invoice number availability")
def check_invoice_no(
    invoice_no: str = Query(..., min_length=1, max_length=64),
    exclude_id: int | None = Query(None, description="编辑既有发票时排除自身"),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("invoice:write")),
):
    return ok({"available": not service.invoice_no_exists(db, invoice_no.strip(), exclude_id=exclude_id)})


def _write_invoice_or_400(db: Session, write):
    """执行发票写入（service 调用 + commit），业务校验失败与唯一约束竞态统一转 400。

    IntegrityError 必须覆盖整个写入：service 末尾的 flush 就会把 INSERT/UPDATE
    发往 DB，竞态冲突（预查通过后另一会话先落库）在 flush 处就抛，只包 commit 接不住。
    """
    try:
        result = write()
        db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except IntegrityError as exc:
        db.rollback()  # flush/commit 失败必须 rollback，否则 session 污染（cerebrum 2026-05-26）
        logger.warning("invoice 写入唯一约束冲突: %s", exc)
        print(f"[invoice] integrity error on write: {exc}", flush=True)
        raise HTTPException(400, "发票号已被占用（并发冲突），请修改后重试")


@router.post("/invoices", summary="Create invoice", status_code=201)
def create_invoice(
    body: InvoiceCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("invoice:write")),
):
    invoice = _write_invoice_or_400(
        db, lambda: service.create_invoice(db, body, user_id=_user_id(current_user)),
    )
    db.refresh(invoice)
    invoice = service.get_invoice(db, invoice.id)
    return ok(service.serialize_detail(invoice))


@router.get("/invoices/{invoice_id}", summary="Invoice detail")
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("invoice:read")),
):
    invoice = service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(404, "发票不存在")
    _ensure_invoice_visible(invoice, current_user)
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
    _ensure_invoice_visible(invoice, current_user)
    invoice = _write_invoice_or_400(
        db, lambda: service.update_invoice(db, invoice, body, user_id=_user_id(current_user)),
    )
    invoice = service.get_invoice(db, invoice.id)
    return ok(service.serialize_detail(invoice))


@router.delete("/invoices/{invoice_id}", summary="Delete invoice")
def delete_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("invoice:write")),
):
    invoice = service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(404, "发票不存在")
    _ensure_invoice_visible(invoice, current_user)
    try:
        service.delete_invoice(db, invoice)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return ok(message="已删除")


@router.post("/invoices/{invoice_id}/validate", summary="Validate invoice before sync")
def validate_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    # mutates invoice.status -> read-only users must not reach it
    current_user=Depends(require_any_permission("invoice:write", "invoice:sync")),
):
    invoice = service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(404, "发票不存在")
    _ensure_invoice_visible(invoice, current_user)
    issues = service.mark_ready_if_valid(invoice)
    db.commit()
    return ok({"ok": not issues, "issues": issues})


@router.post("/invoices/{invoice_id}/sync", summary="Sync invoice to Xiaoman")
def sync_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("invoice:sync")),
):
    invoice = service.get_invoice(db, invoice_id, for_update=True)
    if not invoice:
        raise HTTPException(404, "发票不存在")
    _ensure_invoice_visible(invoice, current_user)
    result = xiaoman_service.sync_invoice(db, invoice, operator_id=_user_id(current_user))
    db.commit()
    return ok(result)


@router.get("/invoices/{invoice_id}/sync-logs", summary="OKKI push audit logs")
def get_sync_logs(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("invoice:read")),
):
    invoice = service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(404, "发票不存在")
    _ensure_invoice_visible(invoice, current_user)
    return ok({"items": xiaoman_service.list_sync_logs(db, invoice_id)})


@router.get("/invoices/{invoice_id}/export/excel", summary="Export invoice Excel")
def export_excel(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("invoice:read")),
):
    invoice = service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(404, "发票不存在")
    _ensure_invoice_visible(invoice, current_user)
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
    current_user=Depends(require_permission("invoice:read")),
):
    invoice = service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(404, "发票不存在")
    _ensure_invoice_visible(invoice, current_user)
    return HTMLResponse(export_service.build_print_html(invoice))


@router.get("/invoices/{invoice_id}/export/pdf", summary="Export invoice PDF")
def export_pdf(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("invoice:read")),
):
    invoice = service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(404, "发票不存在")
    _ensure_invoice_visible(invoice, current_user)
    stream = export_service.build_invoice_pdf(invoice)
    filename = quote(f"{invoice.invoice_no}.pdf")
    return StreamingResponse(
        stream,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


# ── receipt collection_date repair ───────────────────────────

class RepairChangeItem(BaseModel):
    cash_collection_id: str = Field(..., max_length=64)
    new_date: str = Field(..., description="YYYY-MM-DD")


class RepairApplyPayload(BaseModel):
    source_file: str | None = Field(None, max_length=256)
    items: list[RepairChangeItem]


class RepairUnmatchedPayload(BaseModel):
    unmatched: list[dict]


@router.post("/receipt-repair/preview", summary="Dry-run match uploaded workbook to okki_receipts")
def receipt_repair_preview(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    # invoice_repair:read=回款日期修复页面码（063 拆分）；预览是只读试算，apply 仍锁 invoice:admin
    _user=Depends(require_any_permission("invoice_repair:read", "invoice:admin")),
):
    content = file.file.read()
    try:
        rows = receipt_repair_service.parse_workbook(content)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"工作表解析失败: {exc}")
    if not rows:
        raise HTTPException(400, "未从工作表读到有效数据行")
    plan = receipt_repair_service.build_plan(db, rows, source_file=file.filename or "")
    return ok(plan)


@router.post("/receipt-repair/apply", summary="Apply confirmed collection_date fixes")
def receipt_repair_apply(
    body: RepairApplyPayload,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("invoice:admin")),
):
    if not body.items:
        raise HTTPException(400, "没有需要修复的记录")
    result = receipt_repair_service.apply_changes(
        db,
        [it.model_dump() for it in body.items],
        operator_id=_user_id(current_user),
        source_file=body.source_file or "",
    )
    return ok(result, message=f"已修复 {result['applied']} 条")


@router.post("/receipt-repair/export-unmatched", summary="Export unmatched rows as a workbook")
def receipt_repair_export_unmatched(
    body: RepairUnmatchedPayload,
    # 只读导出（axios blob 带 JWT），与 preview 同档；apply 仍锁 invoice:admin
    _user=Depends(require_any_permission("invoice_repair:read", "invoice:admin")),
):
    stream = receipt_repair_service.build_unmatched_workbook(body.unmatched)
    filename = quote("回款日期修复-无法匹配.xlsx")
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
