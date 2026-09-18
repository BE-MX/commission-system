"""Receipt scope is the invoice salesperson, unless receipt read-all is granted."""
from fastapi import HTTPException

from app.invoice.delegation_service import can_access_invoice
from app.invoice.models import Invoice


def user_id(user):
    return int(user.get("id") or user["sub"])


def all_access(user):
    return "super_admin" in user.get("roles", []) or "receipt:read_all" in user.get("permissions", [])


def scope(query, db, user):
    if all_access(user):
        return query
    return query.filter(Invoice.sales_user_id == user_id(user))


def ensure_invoice(db, invoice, user, *, invoice_context=False):
    if invoice is None:
        raise HTTPException(404, "订单或回款单不存在")
    if invoice_context:
        # Unsynchronized invoice evidence still follows the invoice editor's
        # delegation policy, never the scope of an already-created receipt.
        allowed = ("super_admin" in user.get("roles", [])
                   or "invoice:read_all" in user.get("permissions", [])
                   or can_access_invoice(db, user_id(user), invoice))
    else:
        allowed = all_access(user) or invoice.sales_user_id == user_id(user)
    if not allowed:
        raise HTTPException(404, "订单或回款单不存在")
