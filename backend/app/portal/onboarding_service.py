"""Scoped Ark choices for creating portal access, without caller-supplied identities."""
from sqlalchemy import func, or_, select

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.customer.logical_customer_service import logical_subject_matches_customer
from app.customer.models import CustomerAccount, CustomerAssignment, CustomerExternalIdentity
from app.portal import admin_service as admin
from app.portal.errors import reject
from app.portal.models import CatalogItem, CustomerAccess


def customer_query(actor):
    query = select(CustomerAccount, CustomerAssignment, ArkUser.real_name).join(
        CustomerAssignment, CustomerAssignment.customer_id == CustomerAccount.id).join(
        ArkUser, ArkUser.id == CustomerAssignment.user_id).where(
        CustomerAccount.record_status == "active", CustomerAssignment.assignment_role == "primary",
        CustomerAssignment.assignment_status == "active", CustomerAssignment.effective_to.is_(None),
        CustomerAssignment.effective_from <= beijing_now(), ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None))
    if "super_admin" not in actor["roles"]:
        query = query.where(CustomerAssignment.user_id == actor["id"])
    return query


def identities(db, customer_ids):
    namespace = admin.get_settings().PORTAL_OKKI_NAMESPACE
    if not namespace:
        reject("SERVICE_UNAVAILABLE", "请先配置库存与客户身份来源。", 503)
    rows = db.execute(select(CustomerAccount.id, CustomerExternalIdentity).select_from(CustomerAccount).join(
        CustomerExternalIdentity, logical_subject_matches_customer(CustomerExternalIdentity, "external_identity", CustomerAccount)).where(
        CustomerAccount.id.in_(customer_ids), CustomerExternalIdentity.contact_id.is_(None),
        CustomerExternalIdentity.source_system == "okki", CustomerExternalIdentity.identifier_type == "company_id",
        CustomerExternalIdentity.source_account_key == namespace, CustomerExternalIdentity.status == "active",
        CustomerExternalIdentity.verification_status == "verified", CustomerExternalIdentity.identity_strength == "strong",
        CustomerExternalIdentity.cardinality == "one_to_one").execution_options(populate_existing=True)).all()
    result = {identifier: [] for identifier in customer_ids}
    for owner_id, identity in rows:
        result[owner_id].append(identity)
    return result


def project_candidates(db, actor, site, rows):
    ids = [customer.id for customer, _, _ in rows]
    if not ids:
        return []
    candidates = identities(db, ids)
    accesses = {row.customer_id: row for row in db.scalars(select(CustomerAccess).where(
        CustomerAccess.site_id == site.id, CustomerAccess.customer_id.in_(ids))).all()}
    result = []
    for customer, assignment, sales_name in rows:
        matches = candidates[customer.id]
        identity = matches[0] if len(matches) == 1 else None
        reasons = []
        if customer.identity_status == "disputed":
            reasons.append("CUSTOMER_DISPUTED")
        if not matches:
            reasons.append("VERIFIED_IDENTITY_MISSING")
        elif len(matches) > 1:
            reasons.append("MULTIPLE_VERIFIED_IDENTITIES")
        elif not identity.normalized_value or len(identity.normalized_value) > 64:
            reasons.append("IDENTITY_VALUE_INVALID")
        existing = accesses.get(customer.id)
        if existing:
            reasons.append("ACCESS_ALREADY_EXISTS")
        readable = existing and ("super_admin" in actor["roles"] or (
            existing.sales_user_id == actor["id"] and existing.assignment_id == assignment.id
            and existing.status != "review_required"))
        result.append({"canonical_customer_id": str(customer.id), "company_display_name": customer.display_name,
            "customer_code": customer.customer_code, "assignment_id": str(assignment.id),
            "sales_user_id": str(assignment.user_id), "sales_display_name": sales_name,
            "okki_identity_id": str(identity.id) if identity else None,
            "okki_company_id": identity.normalized_value if identity else None,
            "binding_fingerprint": admin.binding_fingerprint(customer.id, identity, assignment) if identity else None,
            "ready": not reasons, "blocked_reasons": reasons,
            "existing_access": {"id": existing.public_id if readable else None,
                                "status": existing.status if readable else "review_required"} if existing else None})
    return result


def list_candidates(db, actor_id, *, keyword=None, page=1, page_size=20):
    actor = admin.begin(db, actor_id)
    site = admin.site_for_admin(db)
    query = customer_query(actor)
    if keyword:
        query = query.where(or_(CustomerAccount.display_name.contains(keyword, autoescape=True),
                               CustomerAccount.customer_code == keyword))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(CustomerAccount.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": project_candidates(db, actor, site, rows), "total": total, "page": page, "page_size": page_size}


def status(db, actor_id, customer_id):
    actor = admin.begin(db, actor_id)
    site = admin.site_for_admin(db)
    row = db.execute(customer_query(actor).where(CustomerAccount.id == customer_id)).first()
    if row is None:
        reject("RESOURCE_NOT_FOUND", "客户不存在或不在当前开通范围内。", 404)
    return project_candidates(db, actor, site, [row])[0]


def validate_creation(db, actor, site, body):
    # Called after the shared authority barrier is locked by create_customer.
    if any(int(value) > 9223372036854775807 for value in (body.canonical_customer_id, body.assignment_id, body.okki_identity_id)):
        reject("INVALID_INPUT", "无效客户身份编号。", 422)
    row = db.execute(customer_query(actor).where(CustomerAccount.id == int(body.canonical_customer_id))
                     .execution_options(populate_existing=True)).first()
    if row is None:
        reject("RESOURCE_NOT_FOUND", "客户不存在或不在当前开通范围内。", 404)
    candidate = project_candidates(db, actor, site, [row])[0]
    if candidate["existing_access"] is not None:
        reject("ACCESS_ALREADY_EXISTS", "该客户已有门户授权，请编辑现有记录。")
    if (not candidate["ready"] or candidate["assignment_id"] != body.assignment_id
            or candidate["okki_identity_id"] != body.okki_identity_id
            or candidate["binding_fingerprint"] != body.binding_fingerprint):
        reject("IDENTITY_REVIEW_REQUIRED", "客户归属或唯一外部身份已变化，请重新选择。")
    existing = db.scalar(select(CustomerAccess.id).where(CustomerAccess.site_id == site.id,
        CustomerAccess.okki_namespace == admin.get_settings().PORTAL_OKKI_NAMESPACE,
        CustomerAccess.okki_company_id == candidate["okki_company_id"]))
    if existing is not None:
        reject("IDENTITY_REVIEW_REQUIRED", "外部身份已存在门户绑定，请由管理员复核。")


def catalog_options(db, actor_id, *, keyword=None, page=1, page_size=20):
    admin.begin(db, actor_id)
    site = admin.site_for_admin(db)
    query = select(CatalogItem).where(CatalogItem.site_id == site.id, CatalogItem.status == "published")
    if keyword:
        query = query.where(or_(CatalogItem.display_name.contains(keyword, autoescape=True),
                               CatalogItem.color_name.contains(keyword, autoescape=True)))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(CatalogItem.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": row.public_id, "model_name": row.display_name, "color_name": row.color_name,
        "length": (row.standard_json or {}).get("length"), "weight": (row.standard_json or {}).get("weight"),
        "sale_unit": row.sale_unit, "product_kind": row.product_kind} for row in rows],
        "total": total, "page": page, "page_size": page_size}
