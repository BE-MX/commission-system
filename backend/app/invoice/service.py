"""Business logic for order invoices."""

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth.models import ArkUser
from app.invoice import price_service, product_service
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.schemas import InvoiceCreate, InvoiceUpdate

_HEADER_FIELDS = (
    "customer_id", "customer_name", "contact_name", "contact_phone", "contact_email",
    "delivery_address", "sales_user_name", "sales_phone", "sales_email",
    "invoice_date", "express_channel", "shipping_fee", "surcharge_name",
    "surcharge_amount", "payment_term", "internal_payment_method", "internal_discount",
    "internal_accessory", "internal_received", "internal_balance",
    "internal_shipping_type", "remark",
)


def list_invoices(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    status: str | None = None,
    order_type: str | None = None,
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
    if order_type:
        query = query.filter(Invoice.order_type == order_type)
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
    creator_names = _resolve_user_names(db, {inv.created_by for inv, _ in rows if inv.created_by})
    return [
        _invoice_list_row(invoice, item_count, creator_names.get(invoice.created_by))
        for invoice, item_count in rows
    ], total


def _resolve_user_names(db: Session, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    rows = db.query(ArkUser.id, ArkUser.real_name).filter(ArkUser.id.in_(user_ids)).all()
    return {uid: name for uid, name in rows}


def delete_invoice(db: Session, invoice: Invoice) -> None:
    """Synced invoices are OKKI-side documents; deleting locally would orphan them."""
    if invoice.sync_status == "synced":
        raise ValueError("已同步小满的发票不允许删除，请先在小满侧处理")
    db.delete(invoice)


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
        order_type=body.order_type,
        currency=body.currency or "USD",
        sales_user_id=user_id,
        created_by=user_id,
        updated_by=user_id,
    )
    for field in _HEADER_FIELDS:
        setattr(invoice, field, getattr(body, field))
    db.add(invoice)
    _replace_items(db, invoice, body, user_id=user_id)
    _refresh_invoice_totals(invoice)
    db.flush()
    return invoice


def update_invoice(db: Session, invoice: Invoice, body: InvoiceUpdate, user_id: int | None = None) -> Invoice:
    for field in _HEADER_FIELDS:
        setattr(invoice, field, getattr(body, field))
    invoice.currency = body.currency or "USD"
    invoice.updated_by = user_id
    if invoice.sync_status == "synced":
        invoice.sync_status = "not_synced"
        invoice.status = "draft"
        invoice.xiaoman_order_id = None
        invoice.xiaoman_order_no = None
        invoice.synced_at = None
    _replace_items(db, invoice, body, user_id=user_id)
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
        if item.item_type == "custom":
            if not item.product_display:
                issues.append({"field": prefix, "message": "生产单产品需填写 Product 描述"})
        else:
            if not item.product_id or not item.product_name:
                issues.append({"field": prefix, "message": "产品未匹配到唯一产品"})
            if not item.sku_id:
                issues.append({"field": f"{prefix}.sku_id", "message": "缺少 sku_id，无法同步小满订单"})
        if not item.net_weight_grams:
            issues.append({"field": f"{prefix}.net_weight_grams", "message": "Net Weight Grams 必填"})
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
        "contact_name": invoice.contact_name,
        "contact_phone": invoice.contact_phone,
        "contact_email": invoice.contact_email,
        "delivery_address": invoice.delivery_address,
        "sales_user_name": invoice.sales_user_name,
        "sales_phone": invoice.sales_phone,
        "sales_email": invoice.sales_email,
        "express_channel": invoice.express_channel,
        "shipping_fee": invoice.shipping_fee,
        "surcharge_name": invoice.surcharge_name,
        "surcharge_amount": invoice.surcharge_amount,
        "payment_term": invoice.payment_term,
        "product_amount": invoice.product_amount,
        "internal_payment_method": invoice.internal_payment_method,
        "internal_discount": invoice.internal_discount,
        "internal_accessory": invoice.internal_accessory,
        "internal_received": invoice.internal_received,
        "internal_balance": invoice.internal_balance,
        "internal_shipping_type": invoice.internal_shipping_type,
        "remark": invoice.remark,
        "xiaoman_order_id": invoice.xiaoman_order_id,
        "xiaoman_order_no": invoice.xiaoman_order_no,
        "sync_error": invoice.sync_error,
        "synced_at": invoice.synced_at,
        "updated_at": invoice.updated_at,
        "items": [_serialize_item(item) for item in invoice.items],
    }


def _custom_line_complete(payload) -> bool:
    return all(str(v or "").strip() for v in (
        payload.product_display, payload.color, payload.length, payload.net_weight_grams,
    ))


def _next_invoice_no(db: Session) -> str:
    today = date.today().strftime("%Y%m%d")
    prefix = f"INV{today}"
    latest = db.execute(
        select(Invoice.invoice_no)
        .where(Invoice.invoice_no.like(f"{prefix}-%"))
        # length first so INV...-1000 sorts after INV...-999
        .order_by(func.length(Invoice.invoice_no).desc(), Invoice.invoice_no.desc())
        .limit(1)
    ).scalar()
    next_seq = 1
    if latest:
        try:
            next_seq = int(str(latest).rsplit("-", 1)[-1]) + 1
        except ValueError:
            next_seq = 1
    return f"{prefix}-{next_seq:03d}"


def _replace_items(db: Session, invoice: Invoice, body, user_id: int | None = None) -> None:
    # re-saving an invoice must not inflate use_count of already-referenced products
    prior_custom_ids = {item.custom_product_id for item in invoice.items if item.custom_product_id}
    has_custom = any(
        p.item_type == "custom" and _custom_line_complete(p) for p in body.items
    )
    okki_rows = product_service.load_okki_rows(db) if has_custom else None
    invoice.items.clear()
    for idx, payload in enumerate(body.items, start=1):
        item = InvoiceItem(
            sort_order=idx,
            item_type=payload.item_type,
            product_id=payload.product_id,
            sku_id=payload.sku_id,
            product_name=payload.product_name,
            product_display=payload.product_display,
            net_weight_grams=payload.net_weight_grams,
            curl=payload.curl,
            model=payload.model,
            color=payload.color,
            length=payload.length,
            quantity=payload.quantity,
            price_per_piece=payload.price_per_piece,
        )
        if payload.item_type == "custom" and _custom_line_complete(payload):
            resolved = product_service.ensure_custom_product(
                db,
                product_display=payload.product_display,
                model=payload.model,
                color=payload.color,
                size=payload.length,
                unit=payload.net_weight_grams,
                user_id=user_id,
                okki_rows=okki_rows,
                skip_bump_ids=prior_custom_ids,
            )
            item.custom_product_id = resolved["custom_product_id"]
            item.product_id = resolved["product_id"]
            item.sku_id = resolved["sku_id"]
            item.product_name = resolved["product_name"] or item.product_name
            # Only flip to a stock line when the OKKI product also has a sku:
            # a stock line without sku_id fails sync validation forever, while
            # a custom line falls back to the generic product at push time.
            if resolved["source"] == "okki" and resolved["sku_id"]:
                item.item_type = "stock"

        # Pricing snapshot is authoritative on the server: the client shows the
        # same numbers, but totals must not trust client-side arithmetic.
        pricing = price_service.resolve_price(
            db,
            customer_id=body.customer_id,
            product_display=item.product_display,
            length=item.length,
            unit=item.net_weight_grams,
            color=item.color,
        )
        item.standard_price = pricing["standard_price"]
        item.customer_price = pricing["customer_price"]
        if item.price_per_piece is None:
            item.price_per_piece = pricing["customer_price"]
        if pricing["customer_price"] is None:
            item.price_source = "missing_std"
        elif item.price_per_piece == pricing["customer_price"]:
            item.price_source = "customer_rule"
        else:
            item.price_source = "manual"
        item.total_price = _money((item.price_per_piece or Decimal("0")) * Decimal(item.quantity))
        invoice.items.append(item)


def _refresh_invoice_totals(invoice: Invoice) -> None:
    invoice.product_amount = _money(sum((item.total_price or Decimal("0")) for item in invoice.items))
    invoice.total_amount = _money(
        invoice.product_amount
        + Decimal(invoice.shipping_fee or 0)
        + Decimal(invoice.surcharge_amount or 0)
    )
    if invoice.sync_status != "synced":
        invoice.status = "ready" if invoice.items and not validate_invoice(invoice) else "draft"


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _invoice_list_row(invoice: Invoice, item_count: int, creator_name: str | None = None) -> dict:
    return {
        "id": invoice.id,
        "invoice_no": invoice.invoice_no,
        "order_type": invoice.order_type,
        "created_by_name": creator_name,
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
        "item_type": item.item_type,
        "product_id": item.product_id,
        "sku_id": item.sku_id,
        "custom_product_id": item.custom_product_id,
        "product_name": item.product_name,
        "product_display": item.product_display,
        "net_weight_grams": item.net_weight_grams,
        "curl": item.curl,
        "model": item.model,
        "color": item.color,
        "length": item.length,
        "quantity": item.quantity,
        "standard_price": item.standard_price,
        "customer_price": item.customer_price,
        "price_per_piece": item.price_per_piece,
        "price_source": item.price_source,
        "total_price": item.total_price,
    }

