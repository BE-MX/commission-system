"""Business logic for order invoices."""

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.invoice.models import Invoice, InvoiceItem
from app.invoice.schemas import InvoiceCreate, InvoiceUpdate


def list_invoices(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    status: str | None = None,
) -> tuple[list[dict], int]:
    query = db.query(Invoice)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (Invoice.invoice_no.like(like)) |
            (Invoice.customer_name.like(like)) |
            (Invoice.customer_id.like(like))
        )
    if status:
        query = query.filter(Invoice.status == status)
    total = query.count()
    rows = (
        query
        .outerjoin(InvoiceItem)
        .group_by(Invoice.id)
        .with_entities(
            Invoice,
            func.count(InvoiceItem.id).label("item_count"),
        )
        .order_by(Invoice.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [_invoice_list_row(invoice, item_count) for invoice, item_count in rows], total


def get_invoice(db: Session, invoice_id: int) -> Invoice | None:
    return (
        db.query(Invoice)
        .options(selectinload(Invoice.items))
        .filter(Invoice.id == invoice_id)
        .first()
    )


def create_invoice(db: Session, body: InvoiceCreate, user_id: int | None = None) -> Invoice:
    invoice = Invoice(
        invoice_no=_next_invoice_no(db),
        customer_id=body.customer_id,
        customer_name=body.customer_name,
        invoice_date=body.invoice_date,
        currency=body.currency or "USD",
        remark=body.remark,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(invoice)
    _replace_items(invoice, body.items)
    _refresh_invoice_totals(invoice)
    db.flush()
    return invoice


def update_invoice(db: Session, invoice: Invoice, body: InvoiceUpdate, user_id: int | None = None) -> Invoice:
    invoice.customer_id = body.customer_id
    invoice.customer_name = body.customer_name
    invoice.invoice_date = body.invoice_date
    invoice.currency = body.currency or "USD"
    invoice.remark = body.remark
    invoice.updated_by = user_id
    if invoice.sync_status == "synced":
        invoice.sync_status = "not_synced"
        invoice.status = "draft"
        invoice.xiaoman_order_id = None
        invoice.xiaoman_order_no = None
        invoice.synced_at = None
    _replace_items(invoice, body.items)
    _refresh_invoice_totals(invoice)
    db.flush()
    return invoice


def validate_invoice(invoice: Invoice) -> list[dict]:
    issues: list[dict] = []
    if not invoice.customer_id:
        issues.append({"field": "customer_id", "message": "请选择客户"})
    if not invoice.items:
        issues.append({"field": "items", "message": "至少需要一条产品明细"})
    for idx, item in enumerate(invoice.items, start=1):
        prefix = f"items[{idx}]"
        if not item.product_id or not item.product_name:
            issues.append({"field": prefix, "message": "产品未匹配到唯一产品"})
        if not item.sku_id:
            issues.append({"field": f"{prefix}.sku_id", "message": "缺少 sku_id，无法同步小满订单"})
        if not item.net_weight_grams:
            issues.append({"field": f"{prefix}.net_weight_grams", "message": "Net Weight Grams 必填"})
        if not item.model:
            issues.append({"field": f"{prefix}.model", "message": "Model 必填"})
        if not item.color:
            issues.append({"field": f"{prefix}.color", "message": "Color 必填"})
        if not item.length:
            issues.append({"field": f"{prefix}.length", "message": "Length 必填"})
        if not item.quantity or item.quantity <= 0:
            issues.append({"field": f"{prefix}.quantity", "message": "Quantity 必须大于 0"})
        if item.price_per_piece is None or item.price_per_piece <= 0:
            issues.append({"field": f"{prefix}.price_per_piece", "message": "Price/Piece 必须大于 0"})
    return issues


def mark_ready_if_valid(invoice: Invoice) -> list[dict]:
    issues = validate_invoice(invoice)
    invoice.status = "ready" if not issues and invoice.sync_status != "synced" else invoice.status
    return issues


def serialize_detail(invoice: Invoice) -> dict:
    return {
        **_invoice_list_row(invoice, len(invoice.items)),
        "remark": invoice.remark,
        "xiaoman_order_id": invoice.xiaoman_order_id,
        "xiaoman_order_no": invoice.xiaoman_order_no,
        "sync_error": invoice.sync_error,
        "synced_at": invoice.synced_at,
        "updated_at": invoice.updated_at,
        "items": [_serialize_item(item) for item in invoice.items],
    }


def _next_invoice_no(db: Session) -> str:
    today = date.today().strftime("%Y%m%d")
    prefix = f"INV{today}"
    latest = db.execute(
        select(Invoice.invoice_no)
        .where(Invoice.invoice_no.like(f"{prefix}-%"))
        .order_by(Invoice.invoice_no.desc())
        .limit(1)
    ).scalar()
    next_seq = 1
    if latest:
        try:
            next_seq = int(str(latest).rsplit("-", 1)[-1]) + 1
        except ValueError:
            next_seq = 1
    return f"{prefix}-{next_seq:03d}"


def _replace_items(invoice: Invoice, payload_items) -> None:
    invoice.items.clear()
    for idx, payload in enumerate(payload_items, start=1):
        price = payload.price_per_piece
        quantity = payload.quantity
        total = _money((price or Decimal("0")) * Decimal(quantity))
        invoice.items.append(InvoiceItem(
            sort_order=idx,
            product_id=payload.product_id,
            sku_id=payload.sku_id,
            product_name=payload.product_name,
            product_display=payload.product_display,
            net_weight_grams=payload.net_weight_grams,
            curl=payload.curl,
            model=payload.model,
            color=payload.color,
            length=payload.length,
            quantity=quantity,
            price_per_piece=price,
            total_price=total,
            price_source=payload.price_source or "manual",
        ))


def _refresh_invoice_totals(invoice: Invoice) -> None:
    invoice.total_amount = _money(sum((item.total_price or Decimal("0")) for item in invoice.items))
    if invoice.sync_status != "synced":
        invoice.status = "ready" if invoice.items and not validate_invoice(invoice) else "draft"


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _invoice_list_row(invoice: Invoice, item_count: int) -> dict:
    return {
        "id": invoice.id,
        "invoice_no": invoice.invoice_no,
        "customer_id": invoice.customer_id,
        "customer_name": invoice.customer_name,
        "invoice_date": invoice.invoice_date,
        "currency": invoice.currency,
        "status": invoice.status,
        "sync_status": invoice.sync_status,
        "total_amount": invoice.total_amount,
        "item_count": int(item_count or 0),
        "created_at": invoice.created_at,
    }


def _serialize_item(item: InvoiceItem) -> dict:
    return {
        "id": item.id,
        "sort_order": item.sort_order,
        "product_id": item.product_id,
        "sku_id": item.sku_id,
        "product_name": item.product_name,
        "product_display": item.product_display,
        "net_weight_grams": item.net_weight_grams,
        "curl": item.curl,
        "model": item.model,
        "color": item.color,
        "length": item.length,
        "quantity": item.quantity,
        "price_per_piece": item.price_per_piece,
        "price_source": item.price_source,
        "total_price": item.total_price,
    }

