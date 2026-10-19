"""Public customer access requests and employee review.

An application never creates authorization from customer input. Approval must
bind the request to an already reviewed/enabled CustomerAccess; the existing
invitation service then creates the account and sends the password setup email.
"""
from sqlalchemy import func, or_, select

from app.core.time import beijing_now
from app.portal import admin_service, auth_service
from app.portal.domain import content_hash, normalize_email
from app.portal.errors import reject
from app.portal.models import Account, CustomerAccess, PortalAccessRequest


def submit(db, body, client_ip):
    site = auth_service.enabled_site(db)
    auth_service.lock_authority(db, force=True)
    auth_service.debit(db, "access-request-ip:" + client_ip, 20, 3600)
    email = normalize_email(body.email)
    auth_service.debit(db, "access-request-email:" + email, 5, 3600)
    existing = db.scalar(select(PortalAccessRequest).where(PortalAccessRequest.site_id == site.id,
        PortalAccessRequest.email_normalized == email, PortalAccessRequest.status == "pending"))
    if existing:
        return view(existing)
    row = PortalAccessRequest(site_id=site.id, full_name=body.full_name, phone=body.phone,
        email_normalized=email, email_display=body.email, status="pending")
    db.add(row)
    db.flush()
    from app.portal import dingtalk_notice
    dingtalk_notice.enqueue(db, "access_request_submitted", row.public_id, beijing_now())
    return view(row)


def view(row):
    return {"id": row.public_id, "full_name": row.full_name, "phone": row.phone,
        "email": row.email_display, "status": row.status, "created_at": row.created_at.isoformat(),
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "review_reason": row.review_reason}


def list_requests(db, actor_id, *, page=1, page_size=20, status="pending", keyword=None):
    actor = admin_service.begin(db, actor_id, "portal_access:read")
    site = admin_service.site_for_admin(db)
    query = select(PortalAccessRequest).where(PortalAccessRequest.site_id == site.id)
    if status:
        query = query.where(PortalAccessRequest.status == status)
    if keyword:
        query = query.where(or_(PortalAccessRequest.full_name.contains(keyword, autoescape=True),
                                PortalAccessRequest.email_normalized == normalize_email(keyword)))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(PortalAccessRequest.created_at.desc(), PortalAccessRequest.id.desc())
        .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [view(row) for row in rows], "total": total, "page": page, "page_size": page_size}


def review(db, actor_id, public_id, body):
    actor = admin_service.begin(db, actor_id, "portal_access:admin")
    site = admin_service.site_for_admin(db)
    row = db.scalar(select(PortalAccessRequest).where(PortalAccessRequest.public_id == str(public_id),
        PortalAccessRequest.site_id == site.id).with_for_update())
    if row is None:
        reject("RESOURCE_NOT_FOUND", "申请不存在。", 404)
    if row.status != "pending":
        reject("REQUEST_ALREADY_REVIEWED", "该申请已审核，不能重复处理。", 409)
    now = beijing_now()
    if body.decision == "reject":
        row.status, row.reviewed_by, row.reviewed_at, row.review_reason = "rejected", actor["id"], now, body.reason
        db.flush()
        return view(row)
    if body.access_id is None:
        reject("INVALID_INPUT", "批准申请时必须选择客户门户授权。", 422)
    access = admin_service.scoped_access(db, body.access_id, actor)
    if access.site_id != site.id or access.status != "enabled" or not access.can_order:
        reject("ACCESS_NOT_ENABLED", "请选择已启用且允许下单的客户门户授权。", 422)
    admin_service.validate_binding(db, access)
    account = db.scalar(select(Account).where(Account.email_normalized == row.email_normalized))
    if account is not None:
        reject("ACCOUNT_ALREADY_EXISTS", "该邮箱已有采购账号，请在客户账号页处理。", 409)
    from types import SimpleNamespace
    command_key = f"access-request:{row.public_id}"
    # invite reads only email/contact_name; no password is accepted or generated for this flow.
    invitation = admin_service.invite(db, actor["id"], access.public_id, command_key,
        SimpleNamespace(email=row.email_display, contact_name=row.full_name))
    # invite() only uses email/contact_name in its payload; it does not hash or persist
    # the placeholder password. The account remains invited until email activation.
    account = db.scalar(select(Account).where(Account.email_normalized == row.email_normalized))
    row.status, row.reviewed_by, row.reviewed_at, row.review_reason = "approved", actor["id"], now, body.reason
    row.account_id, row.access_id = account.id, access.id
    db.flush()
    return {**view(row), "invitation_id": invitation["invitation_id"], "event_id": invitation["event_id"],
            "account_id": account.public_id, "access_id": access.public_id}
