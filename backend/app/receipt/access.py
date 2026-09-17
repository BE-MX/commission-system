"""Receipt visibility follows invoice ownership and existing delegated access."""
from fastapi import HTTPException
from sqlalchemy import and_, or_

from app.auth.models import ArkUser
from app.invoice.delegation_service import can_access_invoice
from app.invoice.models import Invoice, InvoiceDelegateGrant


def user_id(user):
    return int(user.get("id") or user["sub"])


def all_access(user):
    return "super_admin" in user.get("roles", []) or "receipt:read_all" in user.get("permissions", [])


def scope(query, db, user):
    if all_access(user):
        return query
    uid = user_id(user)
    granted = db.query(InvoiceDelegateGrant.sales_user_id).join(
        ArkUser, ArkUser.id == InvoiceDelegateGrant.sales_user_id).filter(
        InvoiceDelegateGrant.delegate_user_id == uid, ArkUser.deleted_at.is_(None), ArkUser.is_active.is_(True))
    return query.filter(or_(Invoice.sales_user_id == uid, and_(
        Invoice.created_by == uid,
        Invoice.sales_user_id.in_(granted),
    )))


def ensure_invoice(db, invoice, user, *, invoice_context=False):
    can_all = all_access(user)
    if invoice_context:
        can_all = "super_admin" in user.get("roles", []) or "invoice:read_all" in user.get("permissions", [])
    if invoice is None or (not can_all and not can_access_invoice(db, user_id(user), invoice)):
        raise HTTPException(404, "订单或回款单不存在")
