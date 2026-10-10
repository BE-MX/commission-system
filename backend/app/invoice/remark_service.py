"""Local remark edits without rebuilding or resending the commercial document."""
from fastapi import HTTPException

from app.invoice import edit_authority
from app.invoice.linked_sync_service import edit_version, ensure_idle
from app.invoice.lifecycle_guard import ensure_mutable


def update(db, identity, body, user):
    invoice, current = edit_authority.prepare_local(db, identity, user, "invoice:write")
    ensure_idle(invoice)
    ensure_mutable(db, invoice)
    if edit_version(invoice) != body.expected_version:
        raise HTTPException(409, "订单已被修改，请刷新后重新编辑备注")
    if (invoice.remark or "") != body.remark:
        invoice.remark = body.remark
        invoice.updated_by = int(current.get("id") or current["sub"])
        db.flush()  # Keep the existing portal publication invalidation protocol.
    return {"id": invoice.id, "remark": invoice.remark, "edit_version": edit_version(invoice)}
