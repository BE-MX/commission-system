"""Business logic for order invoices."""

import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from app.auth.models import ArkUser
from app.invoice import accessory_price_service, price_service, product_service
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.schemas import InvoiceCreate, InvoiceUpdate

_HEADER_FIELDS = (
    "customer_id", "customer_name", "contact_name", "contact_phone", "contact_email",
    "delivery_address", "sales_user_name", "sales_phone", "sales_email",
    "invoice_date", "express_channel", "shipping_fee", "surcharge_name",
    "surcharge_amount", "payment_term", "internal_payment_method", "internal_discount",
    "packaging_quantity", "internal_accessory", "internal_received", "internal_balance",
    "internal_shipping_type", "okki_new_deal", "okki_free_shipping", "okki_first_return",
    "remark",
)


def list_invoices(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    status: str | None = None,
    order_type: str | None = None,
    created_by: int | None = None,
) -> tuple[list[dict], int]:
    query = db.query(Invoice)
    if created_by is not None:
        # 数据范围口径（invoice:read_all 缺失时只看自己创建的），
        # created_by 为 NULL 的历史发票只对全量范围可见
        query = query.filter(Invoice.created_by == created_by)
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


def get_customer_contact_defaults(db: Session, customer_id: str) -> dict:
    """该客户最近一张带联系信息发票的联系人快照 + OKKI 历史订单标记，录入页自动填充用。

    组织级共享（刻意不受发票数据范围限制）：联系人/地址是客户数据（OKKI CRM
    同源），只出联系字段、不暴露任何金额——否则助理录一次业务员还得重录。
    has_xiaoman_orders 供前端预判「是否新成交」开关默认值。
    """
    defaults: dict = {
        "has_xiaoman_orders": customer_has_xiaoman_orders(db, customer_id),
        # 首返旁展示「上次订单成交日期」参考（仅展示，不落库不推 OKKI）；
        # 新成交（无历史单）时为 None → 前端留空
        "last_order_date": customer_last_order_date(db, customer_id),
    }
    row = (
        db.query(
            Invoice.contact_name, Invoice.contact_phone,
            Invoice.contact_email, Invoice.delivery_address,
        )
        .filter(
            Invoice.customer_id == customer_id,
            (func.coalesce(Invoice.contact_name, "") != "")
            | (func.coalesce(Invoice.contact_phone, "") != "")
            | (func.coalesce(Invoice.contact_email, "") != "")
            | (func.coalesce(Invoice.delivery_address, "") != ""),
        )
        # created_at 而非 updated_at：推单/校验等状态写入都会 bump updated_at，
        # 会让被系统触碰的老单顶掉真正最新的联系信息
        .order_by(Invoice.created_at.desc(), Invoice.id.desc())
        .first()
    )
    if row is not None:
        defaults.update({
            "contact_name": row.contact_name,
            "contact_phone": row.contact_phone,
            "contact_email": row.contact_email,
            "delivery_address": row.delivery_address,
        })
    return defaults


def customer_has_xiaoman_orders(db: Session, customer_id: str, *, exclude_order_id: str | None = None) -> bool:
    """该客户在 OKKI 是否已有历史订单（「是否新成交」的兜底判据）。

    exclude_order_id：排除本发票已推出的订单——否则首推成功、投影同步回来后
    重推同一单，会被自己的订单判成"老客"翻转新成交。
    """
    if not str(customer_id or "").strip():
        return False
    schema = product_service._schema()
    sql = f"SELECT 1 FROM `{schema}`.okki_orders WHERE company_id = :cid"
    params: dict = {"cid": str(customer_id)}
    if exclude_order_id:
        sql += " AND order_id != :own"
        params["own"] = str(exclude_order_id)
    row = db.execute(text(sql + " LIMIT 1"), params).first()
    return row is not None


def customer_last_order_date(db: Session, customer_id: str, *, exclude_order_id: str | None = None):
    """该客户在 OKKI 最新一张订单的成交日期（account_date）。

    「首返」旁的参考信息：新成交（无历史单）返回 None。account_date 在业务镜像里
    存为字符串（TEXT），原样返回由上层 JSON 序列化；exclude_order_id 备用（当前
    contact-defaults 按客户维度取数、不排除本单）。
    """
    if not str(customer_id or "").strip():
        return None
    schema = product_service._schema()
    sql = (
        f"SELECT account_date FROM `{schema}`.okki_orders "
        "WHERE company_id = :cid AND account_date IS NOT NULL AND account_date != ''"
    )
    params: dict = {"cid": str(customer_id)}
    if exclude_order_id:
        sql += " AND order_id != :own"
        params["own"] = str(exclude_order_id)
    sql += " ORDER BY account_date DESC LIMIT 1"
    row = db.execute(text(sql), params).first()
    return row[0] if row else None


def resolve_okki_flags(db: Session, invoice: Invoice) -> dict:
    """三个 OKKI 必填业务标记；空值兜底：新成交=客户在 OKKI 无历史订单，
    包邮=运费为 0，首返=否。"""
    new_deal = invoice.okki_new_deal
    if new_deal is None:
        has_history = customer_has_xiaoman_orders(
            db, invoice.customer_id, exclude_order_id=invoice.xiaoman_order_id,
        )
        new_deal = 0 if has_history else 1
    free_shipping = invoice.okki_free_shipping
    if free_shipping is None:
        free_shipping = 1 if Decimal(invoice.shipping_fee or 0) == 0 else 0
    first_return = invoice.okki_first_return
    if first_return is None:
        first_return = 0
    return {
        "okki_new_deal": int(new_deal),
        "okki_free_shipping": int(free_shipping),
        "okki_first_return": int(first_return),
    }


def delete_invoice(db: Session, invoice: Invoice) -> None:
    """Judge by xiaoman_order_id, not sync_status: editing flips a synced invoice
    back to not_synced while the real OKKI order still exists, and deleting would
    orphan it AND cascade-drop its push audit logs."""
    if invoice.xiaoman_order_id or invoice.sync_status == "synced":
        raise ValueError("该发票已在小满建单，不允许本地删除，请先在小满侧处理")
    db.delete(invoice)


def get_invoice(db: Session, invoice_id: int, *, for_update: bool = False) -> Invoice | None:
    """for_update: 推单端点用行锁串行化——两个会话同时首推同一发票会各建一张真实
    OKKI 订单（无沙箱）；持锁期间并发编辑的 header UPDATE 也会阻塞到推单落库。"""
    query = (
        db.query(Invoice)
        .options(selectinload(Invoice.items))
        .filter(Invoice.id == invoice_id)
    )
    if for_update:
        query = query.with_for_update()
    return query.first()


def create_invoice(db: Session, body: InvoiceCreate, user_id: int | None = None) -> Invoice:
    invoice_no = (body.invoice_no or "").strip()
    if invoice_no:
        if invoice_no_exists(db, invoice_no):
            raise ValueError(f"发票号 {invoice_no} 已存在，请更换")
    else:
        invoice_no = suggest_invoice_no(db, user_id, body.order_type)
    invoice = Invoice(
        invoice_no=invoice_no,
        order_type=body.order_type,
        currency=body.currency or "USD",
        sales_user_id=user_id,
        created_by=user_id,
        updated_by=user_id,
    )
    for field in _HEADER_FIELDS:
        setattr(invoice, field, getattr(body, field))
    # 业务员信息兜底：前端未带出时按当前登录用户补齐（编辑单不动，尊重人工修改）
    if user_id and not (invoice.sales_user_name and invoice.sales_phone and invoice.sales_email):
        creator = db.get(ArkUser, user_id)
        if creator:
            invoice.sales_user_name = invoice.sales_user_name or creator.username
            invoice.sales_phone = invoice.sales_phone or creator.phone
            invoice.sales_email = invoice.sales_email or creator.email
    # OKKI 业务标记空值兜底（null=自动判定）
    for field, value in resolve_okki_flags(db, invoice).items():
        setattr(invoice, field, value)
    db.add(invoice)
    _replace_items(db, invoice, body, user_id=user_id)
    _refresh_invoice_totals(invoice)
    _validate_internal_settlement(invoice)
    db.flush()
    return invoice


def update_invoice(db: Session, invoice: Invoice, body: InvoiceUpdate, user_id: int | None = None) -> Invoice:
    # 发票号开放编辑：空值=不改；改动需全库唯一（排除自身）
    new_no = (body.invoice_no or "").strip()
    if new_no and new_no != invoice.invoice_no:
        if invoice_no_exists(db, new_no, exclude_id=invoice.id):
            raise ValueError(f"发票号 {new_no} 已存在，请更换")
        invoice.invoice_no = new_no
    for field in _HEADER_FIELDS:
        setattr(invoice, field, getattr(body, field))
    invoice.currency = body.currency or "USD"
    invoice.updated_by = user_id
    if invoice.sync_status == "synced":
        # 保留 xiaoman_order_id/order_no：下次推单带 order_id 走 OKKI 编辑语义，
        # 清掉会导致重推产生重复订单（幂等编辑，07-07 设计文档 3.3）
        invoice.sync_status = "not_synced"
        invoice.status = "draft"
        invoice.synced_at = None
    # OKKI 业务标记空值兜底（null=自动判定）
    for field, value in resolve_okki_flags(db, invoice).items():
        setattr(invoice, field, value)
    _replace_items(db, invoice, body, user_id=user_id)
    _refresh_invoice_totals(invoice)
    _validate_internal_settlement(invoice)
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
        if item.product_kind == "accessory":
            if item.item_type != "stock":
                issues.append({"field": f"{prefix}.item_type", "message": "配件只能选择 OKKI 库存产品"})
            if not item.product_id:
                issues.append({"field": f"{prefix}.product_id", "message": "配件缺少 OKKI product_id"})
            if not item.sku_id:
                issues.append({"field": f"{prefix}.sku_id", "message": "配件缺少 OKKI sku_id"})
            if not str(item.product_name or "").strip():
                issues.append({"field": f"{prefix}.product_name", "message": "配件 Name 必填"})
            if not str(item.product_display or "").strip():
                issues.append({"field": f"{prefix}.product_display", "message": "配件显示名称必填"})
            if not str(item.model or "").strip():
                issues.append({"field": f"{prefix}.model", "message": "配件 Model 必填"})
            if not str(item.color or "").strip():
                issues.append({"field": f"{prefix}.color", "message": "配件 Color 必填"})
        else:
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
        gross = Decimal(item.price_per_piece or 0) * Decimal(item.quantity or 0)
        if gross + Decimal(item.discount_amount or 0) < 0:
            issues.append({"field": f"{prefix}.discount_amount", "message": "产品行折扣不能超过该行金额"})
    return issues


def mark_ready_if_valid(invoice: Invoice) -> list[dict]:
    issues = validate_invoice(invoice)
    invoice.status = "ready" if not issues and invoice.sync_status != "synced" else invoice.status
    return issues


def serialize_detail(invoice: Invoice) -> dict:
    summary = summarize_items(invoice)
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
        **summary,
        "internal_payment_method": invoice.internal_payment_method,
        "internal_discount": invoice.internal_discount,
        "packaging_quantity": invoice.packaging_quantity,
        "internal_accessory": invoice.internal_accessory,
        "internal_received": invoice.internal_received,
        "internal_balance": invoice.internal_balance,
        "internal_shipping_type": invoice.internal_shipping_type,
        "okki_new_deal": invoice.okki_new_deal,
        "okki_free_shipping": invoice.okki_free_shipping,
        "okki_first_return": invoice.okki_first_return,
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


def invoice_no_exists(db: Session, invoice_no: str, exclude_id: int | None = None) -> bool:
    query = db.query(Invoice.id).filter(Invoice.invoice_no == invoice_no)
    if exclude_id is not None:
        query = query.filter(Invoice.id != exclude_id)
    return query.first() is not None


def suggest_invoice_no(db: Session, user_id: int | None, order_type: str) -> str:
    """默认发票号（2026-07-14 亮哥定版）：
    库存单 `{用户名}-KC-{MM}{NN}`，NN=该用户本月第几张库存单；
    生产单 `SC-{MM}{NN}`，NN=全公司本月第几张生产单（号不含用户名，全局计数）。

    序号按「当月同前缀号面最大序号 +1」推算，不按 order_type 行数计数——
    旧 INV 格式存量单不进新序列，号面与序号永远自洽。号内无年份，跨年同月
    同序会撞全库唯一约束——默认号只是建议值，生成后逐一顺延到不冲突为止。
    NN 用两位零填充，超 99 自然进三位。
    """
    now = datetime.now()
    month = f"{now.month:02d}"
    if order_type == "production":
        prefix = f"SC-{month}"
    else:
        user = db.get(ArkUser, user_id) if user_id else None
        username = (user.username or "").strip() if user else ""
        if not username:
            return _next_invoice_no(db)  # 定位不到用户名（理论不可达）退回旧 INV 规则
        prefix = f"{username}-KC-{month}"
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    # created_at 存的是 utcnow（models 默认值）：「本月」按本地自然月起点换算到 UTC 存储系比较
    month_start = datetime(now.year, now.month, 1) - (datetime.now() - datetime.utcnow())
    existing = db.execute(
        select(Invoice.invoice_no)
        .where(Invoice.invoice_no.like(f"{escaped}%", escape="\\"))
        .where(Invoice.created_at >= month_start)
    ).scalars().all()
    seq = 0
    for no in existing:
        suffix = str(no)[len(prefix):]
        if suffix.isdigit():
            seq = max(seq, int(suffix))
    seq += 1
    while invoice_no_exists(db, f"{prefix}{seq:02d}"):
        seq += 1
    return f"{prefix}{seq:02d}"


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
    if body.order_type != "production" and any(item.item_type == "custom" for item in body.items):
        raise ValueError("库存单不能包含定制产品，请改为生产单或选择已有产品")
    stock_pairs = {
        (int(item.product_id), int(item.sku_id))
        for item in body.items
        if (
            item.product_kind == "hair"
            and item.item_type == "stock"
            and item.product_id is not None
            and item.sku_id is not None
        )
    }
    invalid_pairs = stock_pairs - product_service.valid_okki_product_skus(db, stock_pairs)
    if invalid_pairs:
        raise ValueError("产品与 SKU 不匹配或已停用，请重新选择产品")

    # re-saving an invoice must not inflate use_count of already-referenced products
    prior_custom_ids = {item.custom_product_id for item in invoice.items if item.custom_product_id}
    has_custom = any(
        p.item_type == "custom" and _custom_line_complete(p) for p in body.items
    )
    okki_rows = product_service.load_okki_rows(db, limit=None) if has_custom else None
    # 已推 OKKI 的行（有 unique_id）：回传 id 的行传承 unique_id（编辑语义按行更新）；
    # 未回传的即被删除，进待删快照，下次推单发 remove:1（否则 OKKI 侧留幽灵明细）
    prior_synced = {item.id: item for item in invoice.items if item.xiaoman_unique_id}
    echoed_ids = {p.id for p in body.items if p.id}
    _append_removed_lines(invoice, [
        {
            "unique_id": item.xiaoman_unique_id,
            "product_kind": item.product_kind,
            "item_type": item.item_type,
            "product_id": item.product_id,
            "sku_id": item.sku_id,
            "custom_product_id": item.custom_product_id,
        }
        for item_id, item in prior_synced.items() if item_id not in echoed_ids
    ])
    invoice.items.clear()
    carried_ids: set[int] = set()
    for idx, payload in enumerate(body.items, start=1):
        # 同一 id 只允许第一行传承——复制行带旧 id 时若两行共享 unique_id，
        # OKKI 编辑推单会把两行更新到同一条明细上（金额错且无声）
        carried = prior_synced.get(payload.id) if payload.id and payload.id not in carried_ids else None
        if carried:
            carried_ids.add(payload.id)
        item = InvoiceItem(
            xiaoman_unique_id=carried.xiaoman_unique_id if carried else None,
            sort_order=idx,
            product_kind=payload.product_kind,
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
            discount_amount=payload.discount_amount,
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
        if item.product_kind == "accessory" and item.product_id and item.sku_id:
            pricing = accessory_price_service.resolve_configured_price(
                db,
                customer_id=body.customer_id,
                product_id=int(item.product_id),
                sku_id=int(item.sku_id),
                currency=body.currency or "USD",
            )
        elif item.product_kind == "accessory":
            pricing = {
                "standard_price": None,
                "customer_price": None,
                "currency": body.currency or "USD",
            }
        else:
            pricing = price_service.resolve_price(
                db,
                customer_id=body.customer_id,
                product_display=item.product_display,
                length=item.length,
                unit=item.net_weight_grams,
                color=item.color,
            )
        same_currency = (
            pricing["standard_price"] is None
            or str(pricing["currency"] or "").upper() == str(body.currency or "USD").upper()
        )
        item.standard_price = pricing["standard_price"] if same_currency else None
        item.customer_price = pricing["customer_price"] if same_currency else None
        if item.product_kind == "accessory" and item.standard_price is not None:
            item.product_name = pricing["accessory_name"]
            item.product_display = pricing["accessory_name"]
            item.model = pricing["accessory_model"]
            item.color = pricing["accessory_color"]
        if item.product_kind == "hair" and item.price_per_piece is None:
            item.price_per_piece = item.customer_price
        if item.customer_price is None:
            item.price_source = "missing_std"
        elif item.price_per_piece == item.customer_price:
            item.price_source = "customer_rule"
        else:
            item.price_source = "manual"
        gross_amount = _money((item.price_per_piece or Decimal("0")) * Decimal(item.quantity))
        item.discount_amount = _money(Decimal(item.discount_amount or 0))
        if gross_amount + item.discount_amount < 0:
            raise ValueError(f"items[{idx}].discount_amount: 产品行折扣不能超过该行金额")
        item.total_price = _money(gross_amount + item.discount_amount)
        invoice.items.append(item)


def _append_removed_lines(invoice: Invoice, removed: list[dict]) -> None:
    """Accumulate pushed-then-deleted line snapshots; dedup by unique_id.

    Cleared by xiaoman_service on a successful push. Kept raw (no generic-product
    resolution) — push time owns OKKI identity semantics.
    """
    if not removed:
        return
    try:
        existing = json.loads(invoice.xiaoman_removed_lines or "[]")
    except ValueError:
        existing = []
    seen = {entry.get("unique_id") for entry in existing}
    existing.extend(entry for entry in removed if entry.get("unique_id") not in seen)
    invoice.xiaoman_removed_lines = json.dumps(existing, ensure_ascii=False) if existing else None


def summarize_items(invoice: Invoice) -> dict[str, Decimal]:
    summary = {
        "hair_amount": Decimal("0"),
        "hair_discount": Decimal("0"),
        "accessory_amount": Decimal("0"),
        "accessory_discount": Decimal("0"),
    }
    for item in invoice.items:
        prefix = "accessory" if item.product_kind == "accessory" else "hair"
        gross = _money(Decimal(item.price_per_piece or 0) * Decimal(item.quantity or 0))
        discount = _money(Decimal(item.discount_amount or 0))
        summary[f"{prefix}_amount"] += gross
        summary[f"{prefix}_discount"] += discount
    return {key: _money(value) for key, value in summary.items()}


def _refresh_invoice_totals(invoice: Invoice) -> None:
    summary = summarize_items(invoice)
    invoice.internal_discount = summary["hair_discount"]
    invoice.product_amount = _money(sum(summary.values(), Decimal("0")))
    invoice.total_amount = _money(
        invoice.product_amount
        + Decimal(invoice.internal_accessory or 0)
        + Decimal(invoice.shipping_fee or 0)
        + Decimal(invoice.surcharge_amount or 0)
    )
    if invoice.total_amount < 0:
        raise ValueError("折扣金额不能超过订单中可抵扣的金额")
    if invoice.internal_received is None:
        invoice.internal_balance = None
    else:
        balance = _money(invoice.total_amount - Decimal(invoice.internal_received))
        if balance < 0:
            raise ValueError("预付款不能超过发票总金额")
        invoice.internal_balance = balance
    if invoice.sync_status != "synced":
        invoice.status = "ready" if invoice.items and not validate_invoice(invoice) else "draft"


def _validate_internal_settlement(invoice: Invoice) -> None:
    prepayment = invoice.internal_received
    balance = invoice.internal_balance
    if prepayment is None and balance is None:
        return
    if prepayment is None or balance is None:
        raise ValueError("尾款必须由预付款和发票总金额自动计算")
    if _money(Decimal(prepayment) + Decimal(balance)) != _money(Decimal(invoice.total_amount or 0)):
        raise ValueError("预付款与尾款之和必须等于总金额")


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
        "product_kind": item.product_kind,
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
        "discount_amount": item.discount_amount,
        "price_source": item.price_source,
        "total_price": item.total_price,
    }
