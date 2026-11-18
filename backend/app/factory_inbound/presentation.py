"""Serialize drafts without leaking order invoice identifiers written by sales."""

from sqlalchemy import select

from app.auth.models import ArkUser
from app.auth.service import get_live_user_authorization
from app.factory_inbound.matching_service import can_see_invoice
from app.factory_inbound.models import EditLog, Line
from app.invoice.models import Invoice


def has(user, permission):
    return "super_admin" in user.get("roles", ()) or permission in user.get("permissions", ())


def actor_id(user):
    return int(user["sub"])


def is_admin(user):
    return has(user, "factory_inbound:admin")


def can_edit(note, user):
    return is_admin(user) or (has(user, "factory_inbound:write") and note.created_by == actor_id(user))


def card(note, creator=None):
    return {
        "id": note.id, "inbound_no": note.inbound_no, "created_by": note.created_by,
        "creator": creator, "created_at": note.created_at, "updated_at": note.updated_at,
        "status": note.status, "recognition_status": note.recognition_status,
        "delivery_no": note.delivery_no, "recognized_delivery_no": note.recognized_delivery_no,
        "delivery_month": note.delivery_month, "delivery_day": note.delivery_day,
        "version": note.version,
    }


def order_signatures(order):
    return tuple(order[field] for field in ("kind", "ref", "date", "line_count", "quantity"))


def visible_invoices(db, user, ids):
    if not ids:
        return {}
    roles, permissions = get_live_user_authorization(db, actor_id(user))
    live = {**user, "roles": roles, "permissions": permissions}
    if not (has(live, "invoice:read") or has(live, "invoice:write")):
        return {}
    return {
        invoice.id: invoice.invoice_no for invoice in db.scalars(select(Invoice).where(
            Invoice.id.in_(ids), Invoice.status != "deleted", Invoice.transaction_mode == "legacy",
        )) if can_see_invoice(db, live, invoice)
    }


def _display_order(order, names):
    if not order or order["kind"] != "invoice" or order["id"] not in names:
        return order
    return {**order, "invoice_no": names[order["id"]]}


def line_data(line, names):
    match = line.match_data
    orders = [_display_order(order, names) for order in match["orders"]]
    signatures = [order_signatures(order) for order in orders]
    orders = [{**order, "restricted": order["kind"] == "invoice" and order["id"] not in names
               and signatures.count(order_signatures(order)) > 1} for order in orders]
    return {
        "id": line.id, "line_no": line.line_no, "raw": line.raw, "values": line.values,
        "batch_id": line.batch_id,
        "match_status": line.match_status, "match": {
            **match, "orders": orders, "order": _display_order(match.get("order"), names),
        }, "selected": line.selected, "writeback_enabled": line.writeback_enabled,
    }


def detail(db, note, user, duplicate):
    lines = list(db.scalars(select(Line).where(Line.note_id == note.id).order_by(Line.line_no)))
    names = visible_invoices(db, user, {
        order["id"] for line in lines for order in line.match_data["orders"] if order["kind"] == "invoice"
    })
    creator = db.scalar(select(ArkUser.real_name).where(ArkUser.id == note.created_by))
    duplicate_data = None
    if duplicate is not None:
        duplicate_creator = db.scalar(select(ArkUser.real_name).where(ArkUser.id == duplicate.created_by))
        duplicate_data = {
            "inbound_no": duplicate.inbound_no, "status": duplicate.status, "creator": duplicate_creator,
            "id": duplicate.id if can_edit(duplicate, user) else None,
        }
    logs = db.scalars(select(EditLog).where(EditLog.note_id == note.id).order_by(EditLog.id.desc()).limit(100))
    return {
        **card(note, creator), "recognition_error": note.recognition_error,
        "has_original": bool(note.original_path), "editable": can_edit(note, user) and note.status == "draft",
        "duplicate": duplicate_data, "lines": [line_data(line, names) for line in lines],
        "logs": [{"line_id": log.line_id, "action": log.action, "created_at": log.created_at,
                  "created_by": log.created_by, "before": log.before_data, "after": log.after_data} for log in logs],
    }
