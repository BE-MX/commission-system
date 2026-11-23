"""Live reconciliation views and hash-scoped, audited specialist decisions."""
from fastapi import HTTPException
from sqlalchemy import select

from app.auth.models import ArkUser
from app.core.time import to_beijing_naive
from app.cross_border.import_service import write_transaction
from app.cross_border.match_service import build_rows
from app.cross_border.models import Declaration, ImportBatch, Review


def annotate(rows):
    suspected = {r["order_no"] for r in rows if r["suspected_changed"] and not (r["voided"] or r["excluded"])}
    for row in rows:
        row["needs_suspected_confirmation"] = row["order_no"] in suspected
    return rows


def _matches(row, filters, batch_hashes):
    invoices = row["invoices"]
    ticket = row["ticket"] or {}
    if batch_hashes is not None and not ({row["content_hash"], row["receipt_hash"]} & batch_hashes):
        return False
    if filters.shop and not any(i["shop"] == filters.shop for i in invoices):
        return False
    if filters.salesperson and not any(filters.salesperson.casefold() in str(i.get("salesperson") or "").casefold()
                                       or str(i.get("sales_user_id")) == filters.salesperson for i in invoices):
        return False
    logistics = ticket.get("logistics_status") or "none"
    if filters.logistics and filters.logistics != logistics:
        return False
    if filters.issue and not any(i["code"] == filters.issue for i in row["issues"]):
        return False
    if filters.bound_date_from or filters.bound_date_to:
        bound_at = to_beijing_naive(ticket.get("bound_at"))
        if not bound_at or (filters.bound_date_from and bound_at.date() < filters.bound_date_from
                            or filters.bound_date_to and bound_at.date() > filters.bound_date_to):
            return False
    terms = [row["order_no"], ticket.get("waybill_no"), *(i["number"] for i in invoices)]
    return not filters.q or any(filters.q.strip().casefold() in str(term or "").casefold() for term in terms)


def list_declarations(db, filters):
    if filters.bound_date_from and filters.bound_date_to and filters.bound_date_from > filters.bound_date_to:
        raise HTTPException(422, "物流单开始日期不能晚于结束日期")
    members = None
    if filters.import_id:
        batch = db.get(ImportBatch, filters.import_id)
        members = set(batch.content_hashes) if batch else set()
    rows = [r for r in annotate(build_rows(db)) if _matches(r, filters, members)]
    summary = dict(blocked=0, ready=0, reminders=0, exported=0)
    visible, ready, suspected = [], [], []
    for row in rows:
        active = not (row["excluded"] or row["voided"] or row["exported"])
        views = {"all"}
        if active and row["blocking"]:
            views.add("blocked")
        if active and row["can_export"]:
            views.add("ready")
            ready.append(row["content_hash"])
        if active and any(not issue["blocking"] for issue in row["issues"]):
            views.add("reminders")
        if row["exported"]:
            views.add("exported")
        if active and row["issues"]:
            views.add("exceptions")
        if row["needs_suspected_confirmation"] and row["row_type"] == "declaration":
            suspected.append(row["content_hash"])
        for view in summary:
            summary[view] += int(view in views)
        if filters.view in views:
            visible.append(row)
    start = (filters.page - 1) * filters.page_size
    return dict(items=visible[start:start + filters.page_size], total=len(visible), summary=summary,
                ready_content_hashes=ready, suspected_content_hashes=suspected,
                page=filters.page, page_size=filters.page_size)


def group_for(db, identity):
    declaration = db.scalar(select(Declaration).where(Declaration.content_hash == identity))
    if declaration is None:
        raise HTTPException(404, "找不到这条申报")
    rows = annotate(build_rows(db, order_nos=[declaration.order_no]))
    row = next(r for r in rows if r["row_type"] == "declaration" and r["content_hash"] == identity)
    return declaration, row, rows


def detail(db, identity):
    _, row, _ = group_for(db, identity)
    audit = row["reviews"]
    names = dict(db.execute(select(ArkUser.id, ArkUser.real_name).where(
        ArkUser.id.in_({item["created_by"] for item in audit}))).all()) if audit else {}
    return {**row, "audit": [dict(item, actor_name=names.get(item["created_by"])) for item in audit]}


def review(db, identity, body, actor):
    with write_transaction(db, freeze_sources=True):
        declaration, row, group = group_for(db, identity)
        if row["voided"] or row["excluded"]:
            raise HTTPException(409, "此申报已排除或作废，请刷新")
        codes = {i["code"] for i in row["issues"]}
        if body.action == "void":
            if not row["suspected_changed"]:
                raise HTTPException(409, "仅疑似被修改的旧条目可作废")
            declaration.status = "voided"
        if body.action == "confirm_shipped" and "not_picked_up" not in codes:
            raise HTTPException(409, "此条目当前没有待确认的揽收异常")
        if body.action == "assign_ticket":
            if not codes & {"ambiguous_match", "unknown_product_amount"}:
                raise HTTPException(409, "此申报当前无需指定配对")
            targets = {t["shipment_tracking_id"] for t in row["candidate_tickets"]}
            if body.target not in targets:
                raise HTTPException(409, "目标运单已变化，请重新选择")
            for other in group:
                if other["content_hash"] == identity or other["voided"]:
                    continue
                assigned = [a for a in other.get("reviews", []) if a["action"] == "assign_ticket"]
                if assigned and assigned[-1]["target"] == body.target:
                    raise HTTPException(409, "此票已被其他申报指定")
        target = row["ticket"]["shipment_tracking_id"] if body.action == "confirm_shipped" else body.target
        db.add(Review(content_hash=identity, action=body.action, reason=body.reason, target=target, created_by=actor))
    return {"content_hash": identity, "action": body.action}
