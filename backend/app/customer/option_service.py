"""Bounded customer identity options for authorized business command forms."""
from sqlalchemy import or_
from app.customer.access_service import apply_customer_scope
from app.customer.models import CustomerAccount


def options(db, user, *, permissions, manage_permissions=(), keyword=None, page=1, page_size=30):
    query = apply_customer_scope(db.query(CustomerAccount), user=user, read_permissions=permissions,
        include_public_pool=False, manage_permissions=manage_permissions)
    query = query.filter(CustomerAccount.record_status == "active", CustomerAccount.identity_status != "disputed")
    if keyword:
        term = f"%{keyword.strip()}%"
        query = query.filter(or_(CustomerAccount.display_name.ilike(term), CustomerAccount.customer_code.ilike(term)))
    total = query.count()
    rows = query.order_by(CustomerAccount.display_name, CustomerAccount.id).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [{"id": row.id, "display_name": row.display_name, "customer_code": row.customer_code}
                      for row in rows], "total": total, "page": page, "page_size": page_size}
