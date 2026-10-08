"""Independent read scopes for the invoice's related document panels."""
from fastapi import HTTPException
from sqlalchemy import exists, or_
from sqlalchemy.orm import aliased

from app.auth.models import ArkUserExternalBinding
from app.invoice import service
from app.invoice.models import Invoice
from app.receipt import access
from app.receipt.models import Receipt

PERMISSIONS = {
    "order": ("invoice:read", "invoice:write", "invoice:sync"),
    "receipt": ("receipt:read", "receipt:write", "receipt:admin"),
    "outbound": ("shipping_inspection:read", "shipping_inspection:write", "shipping_inspection:admin"),
    "shipment": ("shipment:read", "shipment:write"),
}


def allowed(user, domain):
    return "super_admin" in user.get("roles", []) or any(p in user.get("permissions", []) for p in PERMISSIONS[domain])


def invoice_query(db, user):
    all_rows = "super_admin" in user.get("roles", []) or "invoice:read_all" in user.get("permissions", [])
    return service._visible_invoice_query(db, viewer_user_id=None if all_rows else access.user_id(user))


def get_order(db, identity, user):
    if not allowed(user, "order") or not invoice_query(db, user).filter(Invoice.id == identity).first():
        raise HTTPException(404, "发票不存在")
    return service.get_invoice(db, identity)


def receipt_query(db, user):
    query = access.scope(db.query(Receipt).join(Invoice, Invoice.id == Receipt.invoice_id), db, user)
    if not access.all_access(user):
        peer, owner = aliased(Receipt), aliased(Invoice)
        inaccessible_batch = exists().where(peer.batch_id == Receipt.batch_id,
            peer.invoice_id == owner.id, or_(owner.sales_user_id != access.user_id(user), owner.sales_user_id.is_(None)))
        query = query.filter(~inaccessible_batch)
    return query


def require_receipts(db, invoice, user):
    if not allowed(user, "receipt"):
        raise HTTPException(403, "无回款查看权限")
    access.ensure_invoice(db, invoice, user)
    # A mixed-owner batch has the same private proof scope as the existing API.
    full = db.query(Receipt.id).filter(Receipt.invoice_id == invoice.id).count()
    visible = receipt_query(db, user).filter(Receipt.invoice_id == invoice.id).count()
    if full != visible:
        raise HTTPException(403, "关联回款批次不在当前可见范围内")


def outbound_scope(db, user):
    if not allowed(user, "outbound"):
        raise HTTPException(403, "无出库单查看权限")
    from app.shipping_inspection.router import _outbound_scope
    return _outbound_scope(db, user)


def local_outbound_query(query, scope):
    if scope is None:
        return query
    return query.filter(exists().where(
        ArkUserExternalBinding.ark_user_id == Invoice.sales_user_id,
        ArkUserExternalBinding.provider == "okki",
        ArkUserExternalBinding.binding_status == "active",
        ArkUserExternalBinding.deleted_at.is_(None),
        ArkUserExternalBinding.external_account_id == scope))
