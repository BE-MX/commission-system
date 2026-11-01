"""Who may POST a receipt to OKKI, and the audited handover of that duty.

The sender is the original registrant unless a takeover was recorded. A sender
must be active, hold receipt:write (or super_admin) and still reach the order
through the same scope used when registering it: receipt scope (salesperson /
receipt:read_all) or the invoice editor scope that creates auto receipts
(delegated order creators, invoice:read_all). The registration fact
(Receipt.created_by) is never rewritten; a takeover is an append-only log row.
"""
import json

from fastapi import HTTPException
from sqlalchemy import select

from app.core.time import beijing_now
from app.receipt.models import ReceiptLog

TAKEOVER = "sender_takeover"
BLOCKED_MESSAGE = "原登记人已停用或无权，请由订单负责人点重试接手"


class SenderIneligible(ValueError):
    """The resolved sender cannot authorize a new POST right now."""


def current(db, receipt):
    """Latest takeover actor, else the original registrant."""
    actor = db.scalar(select(ReceiptLog.created_by).where(
        ReceiptLog.receipt_id == receipt.id, ReceiptLog.action == TAKEOVER).order_by(ReceiptLog.id.desc()).limit(1))
    return int(actor) if actor is not None else int(receipt.created_by)


def principal(db, invoice, actor_id):
    """Live grants of actor_id as a sender of this invoice's receipts."""
    from app.portal.access_policy import employee_principal
    from app.portal.errors import PortalError
    from app.receipt import access
    try:
        actor = employee_principal(db, int(actor_id), "receipt:write")
        try:
            access.ensure_invoice(db, invoice, actor)
        except HTTPException:
            access.ensure_invoice(db, invoice, actor, invoice_context=True)
    except (PortalError, HTTPException, TypeError, ValueError) as exc:
        raise SenderIneligible(BLOCKED_MESSAGE) from exc
    return actor


def take_over_if_needed(db, receipt, invoice, current_user):
    """Called by an authorized retry: hand the send to the retrier when needed.

    Returns the takeover log row, or None when the existing sender still
    qualifies (the retrier never silently replaces a valid sender).
    """
    original = current(db, receipt)
    try:
        principal(db, invoice, original)
        return None
    except SenderIneligible:
        pass
    new_actor = int(current_user["id"])
    if new_actor == original:
        raise SenderIneligible(BLOCKED_MESSAGE)
    principal(db, invoice, new_actor)  # The retrier must meet the same sender rule.
    detail = {"from_actor": original, "to_actor": new_actor, "at": beijing_now().isoformat(),
              "reason": "原发送人已停用、撤权或不再具有订单范围，由当前有权负责人重试接手"}
    row = ReceiptLog(receipt_id=receipt.id, action=TAKEOVER, created_by=new_actor,
                     message=json.dumps(detail, ensure_ascii=False, sort_keys=True))
    db.add(row)
    return row
