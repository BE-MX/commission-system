"""Whitelisted site policy. Deployment origins and secret keys are never UI writable."""
from uuid import uuid4

from sqlalchemy import select

from app.core.config import get_settings
from app.core.time import beijing_now
from app.portal import admin_service as admin
from app.portal.domain import require_version
from app.portal.errors import reject
from app.portal.models import (AuditEvent, AuthChallenge, CustomerAccess, Membership,
                               PortalSession, PreauthSession, Quote, Site)
from app.portal.schemas import SitePolicy
from app.portal.contact_service import validate_contacts, employee_options


def find_site(db):
    return db.scalar(select(Site).where(Site.code == get_settings().PORTAL_SITE_CODE)
                     .execution_options(populate_existing=True))


def view(site):
    if site is None:
        return {"configured": False, "row_version": 0, "site_code": get_settings().PORTAL_SITE_CODE,
                "origin": get_settings().PORTAL_ORIGIN, "currency": "USD", "language": "en",
                "policy": SitePolicy().model_dump(mode="json")}
    return {"configured": True, "id": site.public_id, "row_version": site.row_version,
        "policy_version": site.policy_version, "site_code": site.code, "name": site.name,
        "status": site.status, "origin": site.allowed_origin, "currency": site.currency,
        "language": site.language, "policy": SitePolicy.model_validate(site.policy_json).model_dump(mode="json")}


def read_settings(db, actor_id):
    admin.begin(db, actor_id, "portal_site:admin")
    return {**view(find_site(db)), "contact_employee_options": employee_options(db)}


def update_settings(db, actor_id, expected, body):
    actor = admin.begin(db, actor_id, "portal_site:admin")
    site = find_site(db)
    require_version(site.row_version if site is not None else 0, expected)
    validate_contacts(db, body.policy.sales_contacts)
    policy = body.policy.model_dump(mode="json")
    if site is None:
        site = Site(code=get_settings().PORTAL_SITE_CODE, name=body.name,
            status=body.status, allowed_origin=get_settings().PORTAL_ORIGIN,
            currency="USD", language="en", policy_json=policy)
        db.add(site)
        db.flush()
        before = 0
    else:
        if site.allowed_origin != get_settings().PORTAL_ORIGIN:
            reject("SITE_ORIGIN_MISMATCH", "站点域名与受信部署配置不同，请先由部署管理员核对。", 409)
        before = site.row_version
        changed_policy = SitePolicy.model_validate(site.policy_json).model_dump(mode="json", exclude={"sales_contacts"}) != body.policy.model_dump(mode="json", exclude={"sales_contacts"})
        closing = site.status != body.status
        site.name = body.name
        site.status = body.status
        site.policy_json = policy
        site.row_version += 1
        if changed_policy:
            site.policy_version += 1
        if closing:
            for session in db.scalars(select(PortalSession).where(PortalSession.revoked_at.is_(None),
                    PortalSession.membership_id.in_(select(Membership.id).where(Membership.site_id == site.id)))).all():
                session.revoked_at = beijing_now()
            for preauth in db.scalars(select(PreauthSession).where(PreauthSession.site_id == site.id,
                    PreauthSession.consumed_at.is_(None))).all():
                preauth.consumed_at = beijing_now()
            for challenge in db.scalars(select(AuthChallenge).where(AuthChallenge.site_id == site.id,
                    AuthChallenge.consumed_at.is_(None), AuthChallenge.revoked_at.is_(None))).all():
                challenge.revoked_at = beijing_now()
        if closing or changed_policy:
            for quote in db.scalars(select(Quote).where(Quote.status == "valid", Quote.access_id.in_(
                    select(CustomerAccess.id).where(CustomerAccess.site_id == site.id)))).all():
                quote.status = "expired"
    db.add(AuditEvent(actor_type="employee", actor_id=actor["id"], object_type="site",
        object_public_id=site.public_id, action="site_updated", before_version=before,
        after_version=site.row_version, reason=body.reason, trace_id=str(uuid4()),
        safe_diff_json={"status": site.status, "policy_version": site.policy_version}))
    db.flush()
    return {**view(site), "contact_employee_options": employee_options(db)}
