"""Read-only native order selection with the existing invoice visibility policy."""
from fastapi import HTTPException
from sqlalchemy import func, select
from app.finance.models import Currency
from app.inventory.models import Warehouse
from app.invoice.models import Invoice, InvoiceItem
from app.invoice import service


def list_orders(db, user, *, page=1, page_size=30, keyword=None, commerce_status=None, order_type=None, local_customer_id=None):
    can_read_all = "super_admin" in user.get("roles", []) or "invoice:read_all" in user.get("permissions", [])
    try:
        viewer = None if can_read_all else int(user["sub"])
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(403, "无法确认用户身份") from exc
    query = service._visible_invoice_query(db, viewer_user_id=viewer).filter(Invoice.transaction_mode == "local")
    from app.invoice.native_visibility import local_invoice_scope
    query = query.filter(local_invoice_scope(db, user))
    if keyword:
        term = f"%{keyword.strip()}%"
        query = query.filter(Invoice.invoice_no.ilike(term) | Invoice.customer_name.ilike(term))
    for value, column in ((commerce_status, Invoice.commerce_status), (order_type, Invoice.order_type),
                           (local_customer_id, Invoice.local_customer_id)):
        if value is not None:
            query = query.filter(column == value)
    total = query.count()
    rows = query.order_by(Invoice.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    counts = dict(db.execute(select(InvoiceItem.invoice_id, func.count()).where(
        InvoiceItem.invoice_id.in_([row.id for row in rows])).group_by(InvoiceItem.invoice_id)).all())
    names = service._resolve_user_names(db, {row.created_by for row in rows if row.created_by})
    items = []
    for row in rows:
        item = service._invoice_list_row(row, counts.get(row.id, 0), names.get(row.created_by))
        for key in ("total_amount", "local_deposit_amount", "local_deposit_charge"):
            item[key] = str(getattr(row, key) or "0.00")
        item.update(sales_user_id=row.sales_user_id, sales_user_name=row.sales_user_name)
        from app.invoice.transition_editor import describe as describe_transition
        item.update(describe_transition(db, row, user))
        items.append(item)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def reference_data(db):
    return {"currencies": [{"code": row.code, "name": row.name, "rate_to_cny": str(row.rate_to_cny)}
            for row in db.scalars(select(Currency).where(Currency.active == 1).order_by(Currency.code))],
        "warehouses": [{"id": row.id, "code": row.code, "name": row.name}
            for row in db.scalars(select(Warehouse).where(Warehouse.active.is_(True)).order_by(Warehouse.id))]}
