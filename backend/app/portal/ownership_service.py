"""Explicit customer handoff; immutable order and invoice ownership stays intact."""
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.core.time import beijing_now
from app.customer.models import CustomerAssignment, CustomerExternalIdentity
from app.portal import admin_service as admin
from app.portal.access_policy import binding_fingerprint, current, validate_assignment, validate_binding
from app.portal.domain import require_version
from app.portal.errors import PortalError, reject
from app.portal.models import HistoryGrant, Invitation, OrderRequest, Quote


PENDING_STATUSES = {"submitted", "awaiting_customer", "ready_for_review"}


def transfer_customer(db, actor_id, public_id, expected, body):
    actor = admin.begin(db, actor_id)
    access = admin.scoped_access(db, public_id, actor)
    require_version(access.row_version, expected)
    from app.portal.binding_review_service import require_review
    reviewed = require_review(db, access, body.review_fingerprint)
    if body.assignment_id not in {choice["id"] for choice in reviewed["assignments"]}:
        reject("ASSIGNMENT_CHANGED", "所选对象不在当前有效复核选项内。")
    if int(body.assignment_id) > 9223372036854775807:
        reject("INVALID_INPUT", "无效复核对象编号。", 422)
    if (body.history_policy == "explicit_grant") != (body.history_days is not None):
        reject("INVALID_INPUT", "明确保留历史读取时须指定有效天数，撤销历史读取时不能填写天数。", 422)
    requested = {str(value) for value in body.pending_request_ids}
    if len(requested) != len(body.pending_request_ids):
        reject("INVALID_INPUT", "待交接请求列表存在重复项。", 422)
    assignment = current(db, CustomerAssignment, int(body.assignment_id))
    identity = current(db, CustomerExternalIdentity, access.external_identity_id)
    if assignment is None or identity is None:
        reject("ASSIGNMENT_CHANGED", "请先在方舟确认有效的客户归属。")
    candidate = SimpleNamespace(customer_id=access.customer_id, assignment_id=assignment.id,
        sales_user_id=assignment.user_id, external_identity_id=identity.id,
        okki_namespace=access.okki_namespace, okki_company_id=access.okki_company_id,
        binding_fingerprint=binding_fingerprint(access.customer_id, identity, assignment))
    validate_assignment(db, candidate)
    needs_identity_review = False
    try:
        validate_binding(db, candidate)
    except PortalError as error:
        if error.code != "IDENTITY_REVIEW_REQUIRED":
            raise
        # Assignment and external identity may both change upstream. Allow this
        # one-axis review, but never reopen until the identity is reviewed too.
        needs_identity_review = True
    orders = db.scalars(select(OrderRequest).where(OrderRequest.access_id == access.id)
                         .order_by(OrderRequest.id).with_for_update()).all()
    selected = [row for row in orders if row.public_id in requested]
    if len(selected) != len(requested) or any(row.status not in PENDING_STATUSES or row.invoice_id is not None for row in selected):
        reject("INVALID_TRANSFER_REQUESTS", "仅可交接当前客户尚未建票的待处理请求。")
    before = access.row_version
    previous_owner = access.sales_user_id
    access.assignment_id = assignment.id
    access.sales_user_id = assignment.user_id
    access.binding_fingerprint = candidate.binding_fingerprint
    access.auth_version += 1
    access.row_version += 1
    access.status = "review_required" if needs_identity_review else "suspended"
    admin.revoke_sessions(db, access_id=access.id)
    for quote in db.scalars(select(Quote).where(Quote.access_id == access.id, Quote.status == "valid")).all():
        quote.status = "expired"
    for invitation in db.scalars(select(Invitation).where(Invitation.access_id == access.id,
            Invitation.consumed_at.is_(None), Invitation.revoked_at.is_(None))).all():
        invitation.revoked_at = beijing_now()
        invitation.row_version += 1
    for grant in db.scalars(select(HistoryGrant).where(HistoryGrant.access_id == access.id,
            HistoryGrant.revoked_at.is_(None))).all():
        grant.revoked_at = beijing_now()
    for row in selected:
        row.servicing_user_id = assignment.user_id
        row.accepted_revision_id = None
        row.status = "submitted"  # A new proposal and customer acceptance are mandatory.
        row.row_version += 1
    grants = 0
    if body.history_policy == "explicit_grant":
        # Grant only the records present at handoff, to the NEW representative.
        # No access-wide grant accidentally includes future requests or companies.
        for row in orders:
            if row.public_id in requested:
                continue
            db.add(HistoryGrant(access_id=access.id, grantee_user_id=assignment.user_id,
                scope="order", order_request_id=row.id, reason=body.reason,
                expires_at=beijing_now() + timedelta(days=body.history_days), created_by=actor["id"]))
            grants += 1
    remaining = [row.public_id for row in orders if row.status in PENDING_STATUSES and row.public_id not in requested]
    admin.audit(db, actor, access, access, "customer_transferred", before=before, reason=body.reason,
        changes={"previous_sales_user_id": str(previous_owner), "sales_user_id": str(assignment.user_id),
            "reassigned_request_ids": sorted(requested), "history_policy": body.history_policy,
            "history_grants": grants, "status": access.status})
    db.flush()
    return {**admin.access_view(access), "reassigned_request_ids": sorted(requested),
        "unassigned_pending_request_ids": remaining, "history_grants": grants,
        "requires_identity_review": needs_identity_review, "requires_enable": True}
