"""Ark-managed customer access and invitations; caller owns the transaction.

Every entry locks the authority barrier before fresh employee permissions or
customer state. Functional permission never grants another salesperson's scope.
"""
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select, exists, and_

from app.core.config import get_settings
from app.core.time import beijing_now
from app.portal.access_policy import (binding_fingerprint, current, employee_principal,
    validate_binding)
from app.portal.auth_service import require_enabled
from app.portal.authority import lock_authority
from app.portal.domain import content_hash, normalize_email, require_version
from app.portal.errors import reject
from app.portal.models import (Account, AuditEvent, CatalogGrant, CatalogItem, CommandReceipt,
    CustomerAccess, Invitation, Membership, OutboxEvent, PortalSession, Site)
from app.portal.security import new_token, seal_secret, token_digest
from app.customer.models import CustomerAssignment, CustomerExternalIdentity


def begin(db, actor_id, permission="portal_access:admin"):
    require_enabled()
    lock_authority(db, force=True)
    return employee_principal(db, actor_id, permission)


def site_for_admin(db):
    settings = get_settings()
    site = db.scalar(select(Site).where(Site.code == settings.PORTAL_SITE_CODE)
                     .execution_options(populate_existing=True))
    if site is None or site.allowed_origin != settings.PORTAL_ORIGIN:
        reject("SERVICE_UNAVAILABLE", "请先完成门户站点配置。", 503)
    return site


def employee_scope(actor):
    """A stored sales ID is only a snapshot; current primary ownership must agree."""
    return and_(CustomerAccess.sales_user_id == actor["id"],
        CustomerAccess.status != "review_required",
        exists().where(CustomerAssignment.id == CustomerAccess.assignment_id,
            CustomerAssignment.customer_id == CustomerAccess.customer_id,
            CustomerAssignment.user_id == actor["id"],
            CustomerAssignment.assignment_role == "primary",
            CustomerAssignment.assignment_status == "active",
            CustomerAssignment.effective_from <= beijing_now(),
            CustomerAssignment.effective_to.is_(None)))


def scoped_access(db, public_id, actor):
    query = select(CustomerAccess).where(CustomerAccess.public_id == str(public_id),
                                        CustomerAccess.site_id == site_for_admin(db).id)
    if "super_admin" not in actor["roles"]:
        query = query.where(employee_scope(actor))
    row = db.scalar(query.execution_options(populate_existing=True))
    if row is None:
        reject("RESOURCE_NOT_FOUND", "记录不存在或不在当前授权范围内。", 404)
    return row


def audit(db, actor, access, obj, action, *, before=None, reason="", changes=None):
    db.add(AuditEvent(actor_type="employee", actor_id=actor["id"], access_id=access.id,
        object_type="invitation" if isinstance(obj, Invitation) else "account" if isinstance(obj, Account) else "customer_access",
        object_public_id=obj.public_id, action=action, before_version=before,
        after_version=obj.row_version, reason=reason, safe_diff_json=changes or {}, trace_id=str(uuid4())))


def access_view(row):
    return {"id": row.public_id, "status": row.status, "row_version": row.row_version,
        "canonical_customer_id": str(row.customer_id), "sales_user_id": str(row.sales_user_id),
        "capabilities": {"can_view_price": row.can_view_price, "can_order": row.can_order},
        "catalog_version": row.catalog_version, "mapping_version": row.mapping_version}


def catalog_selection(db, site_id, public_ids):
    identifiers = [str(value) for value in public_ids]
    if len(set(identifiers)) != len(identifiers):
        reject("INVALID_INPUT", "商品授权列表有重复项。", 422)
    rows = db.scalars(select(CatalogItem).where(CatalogItem.public_id.in_(identifiers),
        CatalogItem.site_id == site_id, CatalogItem.status == "published")).all()
    if len(rows) != len(identifiers):
        reject("INVALID_INPUT", "商品未发布或不属于当前站点。", 422)
    return rows


def apply_catalog(db, access, items):
    desired = {item.id for item in items}
    existing = {grant.catalog_item_id: grant for grant in db.scalars(
        select(CatalogGrant).where(CatalogGrant.access_id == access.id)).all()}
    changed = False
    for identifier, grant in existing.items():
        status = "enabled" if identifier in desired else "disabled"
        if grant.status != status:
            grant.status = status
            changed = True
    for identifier in desired - existing.keys():
        db.add(CatalogGrant(access_id=access.id, catalog_item_id=identifier))
        changed = True
    if changed:
        access.catalog_version += 1


def revoke_sessions(db, *, account_id=None, access_id=None):
    query = select(PortalSession).where(PortalSession.revoked_at.is_(None))
    if account_id is not None:
        query = query.where(PortalSession.account_id == account_id)
    elif access_id is not None:
        query = query.where(PortalSession.membership_id.in_(
            select(Membership.id).where(Membership.access_id == access_id)))
    else:
        raise ValueError("Revocation requires an explicit account or access")
    for row in db.scalars(query).all():
        row.revoked_at = beijing_now()


def create_customer(db, actor_id, body):
    from app.portal.onboarding_service import validate_creation
    actor = begin(db, actor_id)
    site = site_for_admin(db)
    validate_creation(db, actor, site, body)
    assignment = current(db, CustomerAssignment, int(body.assignment_id))
    identity = current(db, CustomerExternalIdentity, int(body.okki_identity_id))
    if assignment is None or identity is None or ("super_admin" not in actor["roles"] and assignment.user_id != actor["id"]):
        reject("RESOURCE_NOT_FOUND", "客户绑定不存在或不在当前授权范围内。", 404)
    row = CustomerAccess(site_id=site.id, customer_id=int(body.canonical_customer_id),
        assignment_id=assignment.id, sales_user_id=assignment.user_id,
        external_identity_id=identity.id, okki_namespace=identity.source_account_key,
        okki_company_id=identity.normalized_value,
        binding_fingerprint=binding_fingerprint(int(body.canonical_customer_id), identity, assignment),
        status="draft", can_view_price=body.capabilities.can_view_price, can_order=body.capabilities.can_order)
    validate_binding(db, row)
    if db.scalar(select(CustomerAccess.id).where(CustomerAccess.site_id == site.id,
            CustomerAccess.customer_id == row.customer_id)) is not None:
        reject("ACCESS_ALREADY_EXISTS", "该客户已有门户授权，请编辑现有记录。")
    items = catalog_selection(db, site.id, body.catalog_item_ids)
    db.add(row)
    db.flush()
    apply_catalog(db, row, items)
    audit(db, actor, row, row, "access_created")
    db.flush()
    return access_view(row)


def update_customer(db, actor_id, public_id, expected, body):
    actor = begin(db, actor_id)
    row = scoped_access(db, public_id, actor)
    require_version(row.row_version, expected)
    # Ordinary suspension must not erase the explicit review gate either.
    if row.status == "review_required":
        reject("IDENTITY_REVIEW_REQUIRED", "请先完成归属或外部身份复核。")
    if body.status == "enabled":
        validate_binding(db, row)
    # Omitted catalog selection preserves grants, including withdrawn products.
    # Access revocation must not depend on product publication state.
    items = None if body.catalog_item_ids is None else catalog_selection(db, row.site_id, body.catalog_item_ids)
    before = row.row_version
    row.status = body.status
    row.can_order = body.capabilities.can_order
    row.can_view_price = body.capabilities.can_view_price
    row.row_version += 1
    row.auth_version += 1
    if items is not None:
        apply_catalog(db, row, items)
    revoke_sessions(db, access_id=row.id)
    audit(db, actor, row, row, "access_updated", before=before, reason=body.reason,
        changes={"status": row.status, "can_order": row.can_order, "can_view_price": row.can_view_price})
    db.flush()
    return access_view(row)


def invite(db, actor_id, public_id, command_key, body):
    actor = begin(db, actor_id)
    access = scoped_access(db, public_id, actor)
    if access.status != "enabled":
        reject("ACCESS_NOT_ENABLED", "请先启用客户门户授权。")
    validate_binding(db, access)
    email = normalize_email(body.email)
    payload_hash = content_hash({"email": email, "contact_name": body.contact_name})
    receipt = db.scalar(select(CommandReceipt).where(CommandReceipt.action == "invitation",
        CommandReceipt.object_public_id == access.public_id, CommandReceipt.command_key == str(command_key)))
    if receipt:
        if receipt.payload_hash != payload_hash:
            reject("IDEMPOTENCY_CONFLICT", "同一操作标识不能用于不同邀请内容。")
        return {**receipt.result_reference_json, "replayed": True}
    account = db.scalar(select(Account).where(Account.email_normalized == email))
    if account is not None:
        bindings = db.scalars(select(CustomerAccess).join(Membership, Membership.access_id == CustomerAccess.id)
            .where(Membership.account_id == account.id)).all()
        if any(binding.customer_id != access.customer_id for binding in bindings):
            reject("ACCOUNT_BINDING_CONFLICT", "邮箱已绑定其他公司，不能通过邀请改绑。")
        if account.status == "disabled":
            reject("ACCOUNT_DISABLED", "请先审核并恢复已停用账号。")
    else:
        account = Account(email_normalized=email, email_display=email, contact_name=body.contact_name)
        db.add(account)
        db.flush()
    member = db.scalar(select(Membership).where(Membership.account_id == account.id, Membership.site_id == access.site_id))
    if member and (member.access_id != access.id or member.status == "disabled"):
        reject("ACCOUNT_BINDING_CONFLICT", "成员关系需单独复核，不允许通过邀请更改。")
    if member is None:
        member = Membership(account_id=account.id, site_id=access.site_id, access_id=access.id)
        db.add(member)
        db.flush()
    for old in db.scalars(select(Invitation).where(Invitation.membership_id == member.id,
            Invitation.consumed_at.is_(None), Invitation.revoked_at.is_(None))).all():
        old.revoked_at = beijing_now()
        old.row_version += 1
    token = new_token()
    row = Invitation(account_id=account.id, site_id=access.site_id, access_id=access.id,
        membership_id=member.id, token_hash=token_digest(token), account_version=account.auth_version,
        access_version=access.auth_version, membership_version=member.version, created_by=actor["id"],
        expires_at=beijing_now() + timedelta(hours=get_settings().PORTAL_INVITATION_HOURS))
    db.add(row)
    db.flush()
    settings = get_settings()
    event_key = "invitation:" + row.public_id
    event = OutboxEvent(event_key=event_key, event_type="invitation", aggregate_public_id=row.public_id,
        payload_json={"invitation_id": row.public_id}, next_attempt_at=beijing_now(),
        secret_envelope=seal_secret(settings.PORTAL_MAIL_KEYS[settings.PORTAL_MAIL_KEY_VERSION], token,
            event_key=event_key, purpose="activate", object_id=row.public_id),
        secret_key_version=settings.PORTAL_MAIL_KEY_VERSION, secret_expires_at=row.expires_at)
    db.add(event)
    db.flush()
    result = {"invitation_id": row.public_id, "event_id": event.public_id, "row_version": row.row_version}
    db.add(CommandReceipt(action="invitation", object_public_id=access.public_id, command_key=str(command_key),
        payload_hash=payload_hash, result_reference_json=result, first_actor_type="employee",
        first_actor_id=actor["id"], completed_at=beijing_now()))
    audit(db, actor, access, row, "invitation_created")
    db.flush()
    return {**result, "replayed": False}


def revoke_invitation(db, actor_id, public_id, expected, reason):
    actor = begin(db, actor_id)
    row = db.scalar(select(Invitation).where(Invitation.public_id == str(public_id)))
    if row is None:
        reject("RESOURCE_NOT_FOUND", "记录不存在或不在当前授权范围内。", 404)
    access = current(db, CustomerAccess, row.access_id)
    access = scoped_access(db, access.public_id, actor)
    require_version(row.row_version, expected)
    if row.consumed_at is not None:
        reject("INVITATION_CONSUMED", "账号已激活，请通过账号停用操作撤销访问。")
    before = row.row_version
    row.revoked_at = beijing_now()
    row.row_version += 1
    audit(db, actor, access, row, "invitation_revoked", before=before, reason=reason)
    db.flush()
    return {"id": row.public_id, "row_version": row.row_version, "revoked": True}


def update_account(db, actor_id, public_id, expected, body):
    actor = begin(db, actor_id)
    account = db.scalar(select(Account).where(Account.public_id == str(public_id)))
    if account is None:
        reject("RESOURCE_NOT_FOUND", "记录不存在或不在当前授权范围内。", 404)
    bindings = db.scalars(select(CustomerAccess).join(Membership, Membership.access_id == CustomerAccess.id)
        .where(Membership.account_id == account.id)).all()
    if not bindings:
        reject("RESOURCE_NOT_FOUND", "记录不存在或不在当前授权范围内。", 404)
    for access in bindings:
        scoped_access(db, access.public_id, actor)
    require_version(account.row_version, expected)
    if body.status == "active" and account.verified_at is None:
        reject("EMAIL_NOT_VERIFIED", "账号须先通过邀请验证邮箱，不能直接激活。")
    if body.status == "invited" and (account.status != "disabled" or account.verified_at is not None):
        reject("INVALID_ACCOUNT_TRANSITION", "仅已停用且未验证邮箱的账号可恢复为待邀请。")
    before = account.row_version
    account.status = body.status
    account.auth_version += 1
    account.row_version += 1
    revoke_sessions(db, account_id=account.id)
    audit(db, actor, bindings[0], account, "account_updated", before=before, reason=body.reason,
          changes={"status": account.status})
    db.flush()
    return {"id": account.public_id, "status": account.status, "row_version": account.row_version,
            "requires_invitation": account.status == "invited"}


def list_customers(db, actor_id, *, page=1, page_size=20, status=None, keyword=None):
    from sqlalchemy import func, or_
    from app.customer.models import CustomerAccount
    actor = begin(db, actor_id, "portal_access:read")
    site = site_for_admin(db)
    query = select(CustomerAccess, CustomerAccount.display_name).join(
        CustomerAccount, CustomerAccount.id == CustomerAccess.customer_id).where(CustomerAccess.site_id == site.id)
    if "super_admin" not in actor["roles"]:
        query = query.where(employee_scope(actor))
    if status:
        query = query.where(CustomerAccess.status == status)
    if keyword:
        # autoescape treats user-supplied %/_ as literal characters.
        query = query.where(or_(CustomerAccount.display_name.contains(keyword, autoescape=True),
                               CustomerAccess.okki_company_id == keyword))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(CustomerAccess.created_at.desc(), CustomerAccess.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{**access_view(row), "company_display_name": name} for row, name in rows],
            "total": total, "page": page, "page_size": page_size}


def customer_detail(db, actor_id, public_id, *, page=1, page_size=20):
    from sqlalchemy import func
    from app.customer.models import CustomerAccount
    actor = begin(db, actor_id, "portal_access:read")
    access = scoped_access(db, public_id, actor)
    company_name = db.scalar(select(CustomerAccount.display_name).where(CustomerAccount.id == access.customer_id))
    query = select(Account, Membership).join(Membership, Membership.account_id == Account.id).where(
        Membership.access_id == access.id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(Account.created_at.desc(), Account.id.desc())
        .offset((page - 1) * page_size).limit(page_size)).all()
    members = []
    for account, member in rows:
        invitation = db.scalar(select(Invitation).where(Invitation.membership_id == member.id)
            .order_by(Invitation.created_at.desc(), Invitation.id.desc()).limit(1))
        invitation_view = None
        if invitation is not None:
            state = "consumed" if invitation.consumed_at else "revoked" if invitation.revoked_at else (
                "expired" if invitation.expires_at <= beijing_now() else "pending")
            invitation_view = {"id": invitation.public_id, "status": state, "row_version": invitation.row_version}
        members.append({"id": account.public_id, "email": account.email_display,
            "contact_name": account.contact_name, "status": account.status,
            "row_version": account.row_version, "email_verified": account.verified_at is not None,
            "membership_status": member.status, "invitation": invitation_view})
    grants = db.scalars(select(CatalogItem.public_id).join(CatalogGrant,
        CatalogGrant.catalog_item_id == CatalogItem.id).where(CatalogGrant.access_id == access.id,
        CatalogGrant.status == "enabled")).all()
    return {**access_view(access), "company_display_name": company_name,
        "catalog_item_ids": list(grants), "accounts": {"items": members, "total": total,
        "page": page, "page_size": page_size}}


def rebind_identity(db, actor_id, public_id, expected, body):
    """Review one canonical company's external binding without rewriting old orders."""
    from types import SimpleNamespace
    from app.portal.models import Quote
    actor = begin(db, actor_id)
    access = scoped_access(db, public_id, actor)
    require_version(access.row_version, expected)
    from app.portal.binding_review_service import require_review
    reviewed = require_review(db, access, body.review_fingerprint)
    if body.identity_id not in {choice["id"] for choice in reviewed["identities"]}:
        reject("IDENTITY_REVIEW_REQUIRED", "所选对象不在当前有效复核选项内。")
    if int(body.identity_id) > 9223372036854775807:
        reject("INVALID_INPUT", "无效复核对象编号。", 422)
    identity = current(db, CustomerExternalIdentity, int(body.identity_id))
    assignment = current(db, CustomerAssignment, access.assignment_id)
    if identity is None or assignment is None:
        reject("IDENTITY_REVIEW_REQUIRED", "请先确认有效的公司身份和负责人。")
    candidate = SimpleNamespace(customer_id=access.customer_id, external_identity_id=identity.id,
        assignment_id=assignment.id, sales_user_id=access.sales_user_id,
        okki_namespace=identity.source_account_key, okki_company_id=identity.normalized_value,
        binding_fingerprint=binding_fingerprint(access.customer_id, identity, assignment))
    # Actual canonical ownership, namespace, verified strength and primary owner are rechecked.
    validate_binding(db, candidate)
    duplicate = db.scalar(select(CustomerAccess.id).where(CustomerAccess.site_id == access.site_id,
        CustomerAccess.id != access.id, CustomerAccess.okki_namespace == candidate.okki_namespace,
        CustomerAccess.okki_company_id == candidate.okki_company_id))
    if duplicate is not None:
        reject("IDENTITY_ALREADY_LINKED", "该外部公司身份已被其他门户授权使用。")
    before = access.row_version
    previous_identity = access.external_identity_id
    access.external_identity_id = identity.id
    access.okki_namespace = candidate.okki_namespace
    access.okki_company_id = candidate.okki_company_id
    access.binding_fingerprint = candidate.binding_fingerprint
    access.auth_version += 1
    access.row_version += 1
    # Review resolves identity only. Reopening remains an explicit capability/catalog decision.
    access.status = "suspended"
    revoke_sessions(db, access_id=access.id)
    expired = 0
    for quote in db.scalars(select(Quote).where(Quote.access_id == access.id, Quote.status == "valid")).all():
        quote.status = "expired"
        expired += 1
    for invitation in db.scalars(select(Invitation).where(Invitation.access_id == access.id,
            Invitation.consumed_at.is_(None), Invitation.revoked_at.is_(None))).all():
        invitation.revoked_at = beijing_now()
        invitation.row_version += 1
    audit(db, actor, access, access, "identity_rebound", before=before, reason=body.reason,
        changes={"previous_identity_id": str(previous_identity), "identity_id": str(identity.id),
                 "expired_quotes": expired, "status": "suspended"})
    db.flush()
    return {**access_view(access), "expired_quotes": expired, "requires_enable": True}
