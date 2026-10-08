"""Customer/company and employee/order scopes applied before paging or projection."""
from copy import deepcopy

from sqlalchemy import and_, exists, func, or_, select

from app.core.time import beijing_now
from app.core.config import get_settings
from app.portal import admin_service as admin, auth_service as auth, revision_evidence, order_commands
from app.portal.errors import reject
from app.portal.models import AuditEvent, CustomerAccess, HistoryGrant, OrderRequest, RequestLine, Revision


def employee_query(db, actor):
    site = admin.site_for_admin(db)
    query = select(OrderRequest).join(CustomerAccess, CustomerAccess.id == OrderRequest.access_id)
    query = query.where(CustomerAccess.site_id == site.id)
    if "super_admin" in actor["roles"] or "portal_order:read_all" in actor["permissions"]:
        return query
    own = and_(OrderRequest.servicing_user_id == actor["id"], admin.employee_scope(actor))
    history = exists().where(HistoryGrant.access_id == OrderRequest.access_id,
        HistoryGrant.grantee_user_id == actor["id"], HistoryGrant.revoked_at.is_(None),
        HistoryGrant.expires_at > beijing_now(), or_(
            and_(HistoryGrant.scope == "order", HistoryGrant.order_request_id == OrderRequest.id),
            and_(HistoryGrant.scope == "request_history", OrderRequest.created_at < HistoryGrant.created_at)))
    return query.where(or_(own, history))


def load_revision(db, order):
    revision_id = order.active_revision_id
    if order.status == "invoice_created":
        from app.portal.models import Publication
        published_revision = db.scalar(select(Publication.revision_id).where(Publication.request_id == order.id)
            .order_by(Publication.invoice_document_version.desc()).limit(1))
        if published_revision is not None:
            revision_id = published_revision
    revision = db.scalar(select(Revision).where(Revision.id == revision_id,
                                               Revision.request_id == order.id))
    if revision is None:
        reject("ORDER_UNAVAILABLE", "This order request needs review.", 409)
    lines = db.scalars(select(RequestLine).where(RequestLine.revision_id == revision.id)
                      .order_by(RequestLine.id)).all()
    revision_evidence.verify(revision, lines)
    return revision, lines


def summary(db, order, *, show_price):
    result = {"request_id": order.public_id, "request_no": order.public_no, "status": order.status,
              "row_version": order.row_version, "submitted_at": order.submitted_at.isoformat(),
              "customer_po": order.customer_po}
    if show_price:
        revision, _ = load_revision(db, order)
        result.update(currency=revision.currency, product_amount=format(revision.product_amount, ".2f"),
                      total_amount=revision_evidence.fixed(revision.total_amount), fees_status=revision.fees_status)
    return result


def detail_view(db, order, *, show_price):
    revision, lines = load_revision(db, order)
    result = summary(db, order, show_price=False)
    display_keys = ("item_id", "model_name", "color_name", "customer_sku", "length", "weight", "unit")
    items = []
    for line in lines:
        item = {"line_key": line.line_key, "quantity": line.qty,
                "display_snapshot": {key: deepcopy(line.customer_display_json.get(key)) for key in display_keys}}
        if show_price:
            item.update(unit_price=revision_evidence.fixed(line.unit_price, 4),
                        discount_amount=revision_evidence.fixed(line.discount_amount),
                        line_amount=revision_evidence.fixed(line.line_amount))
        items.append(item)
    result.update(items=items, delivery=deepcopy(revision.delivery_json), remark=revision.remark,
                  revision_id=revision.public_id, revision_kind=revision.kind, available_actions=[])
    if show_price:
        result.update(currency=revision.currency, product_amount=revision_evidence.fixed(revision.product_amount),
            total_amount=revision_evidence.fixed(revision.total_amount),
            payment_terms_snapshot=deepcopy(revision.payment_terms_snapshot),
            fees={"status": revision.fees_status, "shipping_amount": revision_evidence.fixed(revision.shipping_amount),
                  "packaging_amount": revision_evidence.fixed(revision.packaging_amount),
                  "surcharge_amount": revision_evidence.fixed(revision.surcharge_amount),
                  "surcharge_name": revision.surcharge_name})
        if revision.kind == "proposal":
            from app.portal.revision_comparison import previous_comparison
            result["proposal"] = {"revision_id": revision.public_id, "content_hash": revision.content_hash,
                "expires_at": revision.expires_at.isoformat(), "expired": revision.expires_at <= beijing_now(),
                "accepted": order.accepted_revision_id == revision.id,
                "changes": previous_comparison(db, revision, lines)}
        if order.status == "invoice_created":
            from app.portal.pi_amendment_queries import view
            result["pi_amendment"] = view(db, order)
    events = db.scalars(select(AuditEvent).where(AuditEvent.access_id == order.access_id,
        AuditEvent.object_type == "order_request", AuditEvent.object_public_id == order.public_id,
        AuditEvent.action.in_(("order.submitted", "order.cancelled", "order.proposed", "order.accepted",
                              "order.proposal_rejected", "order.invoice_created", "order.pi_proposed",
                              "order.pi_accepted", "order.pi_rejected", "order.pi_published", "order.pi_voided", "order.rejected")))
        .order_by(AuditEvent.id.desc()).limit(100)).all()
    result["customer_safe_timeline"] = [{"event": row.action, "at": row.created_at.isoformat()}
                                        for row in reversed(events)]
    return result


def page_view(db, query, *, page, page_size, status, show_price):
    if status is not None:
        query = query.where(OrderRequest.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(OrderRequest.submitted_at.desc(), OrderRequest.id.desc())
        .offset((page-1)*page_size).limit(page_size)).all()
    return {"items": [summary(db, row, show_price=show_price) for row in rows],
            "total": total, "page": page, "page_size": page_size}


def customer_list(db, token, *, page=1, page_size=20, status=None):
    principal, _ = auth.authenticate(db, token)
    principal.require("order_status")
    query = select(OrderRequest).where(OrderRequest.access_id == principal.access.id)
    return page_view(db, query, page=page, page_size=page_size, status=status,
                     show_price=principal.access.can_view_price)


def customer_detail(db, token, public_id):
    principal, _ = auth.authenticate(db, token)
    principal.require("order_status")
    order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == str(public_id),
                                                OrderRequest.access_id == principal.access.id))
    if order is None:
        reject("RESOURCE_NOT_FOUND", "This order request is not available.", 404)
    result = detail_view(db, order, show_price=principal.access.can_view_price)
    pi = result.get("pi_amendment")
    if pi and pi["status"] == "current":
        result["available_actions"].append("download_pi")
    if (pi and pi["status"] == "pending_customer" and pi["proposal"]
            and get_settings().PORTAL_WRITES_ENABLED and principal.access.can_order and principal.access.can_view_price):
        result["available_actions"].append("reject_pi")
        if not pi["proposal"]["expired"]:
            result["available_actions"].append("accept_pi")
    if (get_settings().PORTAL_WRITES_ENABLED and principal.access.can_order and principal.access.can_view_price
            and order.status in {"submitted", "awaiting_customer", "ready_for_review"}
            and not order_commands.has_invoice_lineage(db, order)):
        result["available_actions"] = ["cancel"]
        proposal = result.get("proposal")
        if order.status == "awaiting_customer" and proposal:
            result["available_actions"].append("reject_proposal")
            if not proposal["expired"]:
                result["available_actions"].append("accept_proposal")
    return result


def employee_list(db, actor_id, *, page=1, page_size=20, status=None):
    actor = admin.begin(db, actor_id, "portal_order:read")
    return page_view(db, employee_query(db, actor), page=page, page_size=page_size, status=status, show_price=True)


def employee_detail(db, actor_id, public_id):
    actor = admin.begin(db, actor_id, "portal_order:read")
    order = db.scalar(employee_query(db, actor).where(OrderRequest.public_id == str(public_id)))
    if order is None:
        reject("RESOURCE_NOT_FOUND", "订单不存在或不在当前授权范围内。", 404)
    return detail_view(db, order, show_price=True)
