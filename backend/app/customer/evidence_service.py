"""Human-readable evidence choices with the same live record boundary as profiles."""

import logging
from urllib.parse import urlsplit

from sqlalchemy import or_

from app.core.time import beijing_now
from app.customer.access_service import apply_record_access, require_customer_access
from app.customer.models import CustomerEvent, CustomerFact, CustomerOpportunity, CustomerSourceRecord
from app.customer.logical_customer_service import logical_owner_expression
from app.customer.access_service import CustomerAccessDenied
from app.customer.query_service import iso_beijing


READ_PERMISSIONS = {"customer:read", "customer:read_all", "sales_automation:read",
                    "sales_automation:write", "sales_automation:admin",
                    "customer_opportunity:read", "customer_opportunity:write", "customer_radar:read"}
logger = logging.getLogger(__name__)


def access_for(db, user, customer_id):
    return require_customer_access(db, customer_id=customer_id, user=user,
        action_permissions=READ_PERMISSIONS, manage_permissions={"customer:admin"}, allow_public_pool=True)


def visible_facts(db, access):
    sources = apply_record_access(db.query(CustomerSourceRecord.id), CustomerSourceRecord,
                                   access, logical_object_type="source_record")
    return apply_record_access(db.query(CustomerFact), CustomerFact, access, logical_object_type="fact").filter(
        or_(CustomerFact.source_record_id.is_(None), CustomerFact.source_record_id.in_(sources)),
    )


def _safe_url(value):
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username else None
    except ValueError:
        message = "Invalid persisted evidence URL omitted from human response"
        logger.warning(message)
        print(message, flush=True)
        return None


def serialize_facts(db, rows):
    source_ids = {row.source_record_id for row in rows if row.source_record_id}
    sources = {row.id: row for row in db.query(CustomerSourceRecord).filter(
        CustomerSourceRecord.id.in_(source_ids)).all()} if source_ids else {}
    now = beijing_now()
    return [{
        "id": row.id, "kind": "fact", "title": row.fact_key,
        "value": (row.value_json or {}).get("value"), "fact_layer": row.fact_layer,
        "verification_status": row.verification_status,
        "occurred_at": iso_beijing(row.observed_at),
        "source": sources[row.source_record_id].source_system if row.source_record_id in sources else "manual",
        "source_url": _safe_url(sources[row.source_record_id].source_url) if row.source_record_id in sources else None,
        "selectable": row.verification_status not in ("rejected", "superseded", "disputed")
            and (row.effective_to is None or row.effective_to > now)
            and (row.effective_from is None or row.effective_from <= now)
            and (row.expires_at is None or row.expires_at > now),
    } for row in rows]


def list_evidence(db, user, customer_id, *, kind="fact", page=1, page_size=20, keyword=None,
                  opportunity_id=None, target_status=None):
    access = access_for(db, user, customer_id)
    opportunity = None
    if opportunity_id is not None:
        opportunity = db.query(CustomerOpportunity).filter(
            CustomerOpportunity.id == opportunity_id,
            logical_owner_expression(CustomerOpportunity, "opportunity") == access.customer_id,
        ).one_or_none()
        if opportunity is None:
            raise CustomerAccessDenied("CUSTOMER_NOT_FOUND_OR_FORBIDDEN")
    if kind == "event":
        from app.customer.workflow_service import _event_supports_stage

        query = apply_record_access(db.query(CustomerEvent), CustomerEvent, access)
        if keyword and keyword.strip():
            query = query.filter(or_(CustomerEvent.event_title.ilike(f"%{keyword.strip()}%"),
                                     CustomerEvent.event_summary.ilike(f"%{keyword.strip()}%")))
        total = query.count()
        rows = query.order_by(CustomerEvent.occurred_at.desc(), CustomerEvent.id.desc()).offset(
            (page - 1) * page_size).limit(page_size).all()
        items = []
        for row in rows:
            selectable = opportunity is None or target_status is None or _event_supports_stage(
                db, event=row, opportunity=opportunity, new_status=target_status,
            )
            items.append({"id": row.id, "kind": "event", "title": row.event_title,
                          "summary": row.event_summary, "event_type": row.event_type,
                          "source": row.event_source, "occurred_at": iso_beijing(row.occurred_at),
                          "selectable": selectable,
                          "unavailable_reason": None if selectable else "不属于本机会当前阶段的沟通依据"})
    else:
        query = visible_facts(db, access)
        if keyword and keyword.strip():
            query = query.filter(CustomerFact.fact_key.ilike(f"%{keyword.strip()}%"))
        total = query.count()
        rows = query.order_by(CustomerFact.observed_at.desc(), CustomerFact.id.desc()).offset(
            (page - 1) * page_size).limit(page_size).all()
        items = serialize_facts(db, rows)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def require_visible_selection(db, access, *, fact_ids=(), event_ids=()):
    from app.customer.workflow_service import CustomerWorkflowConflict

    if fact_ids:
        rows = visible_facts(db, access).filter(CustomerFact.id.in_(fact_ids)).all()
        allowed = {item["id"] for item in serialize_facts(db, rows) if item["selectable"]}
        if set(fact_ids) != allowed:
            raise CustomerWorkflowConflict("EVIDENCE_NOT_AVAILABLE_REFRESH_REQUIRED")
    if event_ids:
        allowed = {row.id for row in apply_record_access(db.query(CustomerEvent.id), CustomerEvent, access).filter(
            CustomerEvent.id.in_(event_ids)).all()}
        if set(event_ids) != allowed:
            raise CustomerWorkflowConflict("EVIDENCE_NOT_AVAILABLE_REFRESH_REQUIRED")
