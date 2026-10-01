"""Register customer service entry points without treating web traffic as sales evidence."""

from urllib.parse import urlsplit, urlunsplit

from app.core.time import beijing_now
from app.customer import pcw_errors
from app.customer.access_service import CustomerAccessDenied, apply_record_access, require_customer_access
from app.customer.logical_customer_service import logical_root_predicate
from app.customer.models import CustomerAnnotation, CustomerAssignment
from app.customer.pcw_idempotency import run_with_receipt
from app.customer.work_item_service import READ, WRITE, live_user
from app.customer.workflow_service import _account_for_update, _active_user

KIND = "service_asset_v1"
TYPES = {"customer_website", "selection_page", "purchase_entry", "material_service", "other"}


def _access(db, user, customer_id, *, write=False):
    try:
        return require_customer_access(db, customer_id=customer_id, user=live_user(db, user),
            action_permissions=WRITE if write else READ, manage_permissions=("customer:admin",))
    except CustomerAccessDenied as exc:
        raise pcw_errors.customer_not_found() from exc


def _entry_url(raw):
    try:
        parts = urlsplit(str(raw).strip())
        if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
            raise ValueError("unsupported service URL")
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))
    except ValueError as exc:
        raise pcw_errors.bad_request("请输入有效的 HTTP(S) 服务入口", error_code="SERVICE_ENTRY_URL_INVALID") from exc


def serialize(row):
    data = row.content_json or {}
    return {"asset_id": row.id, "asset_version": 1, "asset_type": data.get("asset_type"),
        "entry_url": data.get("entry_url"), "purpose": data.get("purpose"),
        "owner_user_id": data.get("owner_user_id"), "known_issue": data.get("known_issue"),
        "status": row.status, "registered_at": row.created_at.isoformat() if row.created_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None}


def list_assets(db, user, customer_id):
    access = _access(db, user, customer_id)
    rows = apply_record_access(db.query(CustomerAnnotation), CustomerAnnotation, access,
        visibility_field="visibility", author_field="authored_by", logical_object_type="annotation").filter(
            CustomerAnnotation.annotation_type == "note", CustomerAnnotation.content_schema_version == "v1",
            CustomerAnnotation.status == "active").order_by(CustomerAnnotation.id.desc()).all()
    return {"items": [serialize(row) for row in rows if (row.content_json or {}).get("kind") == KIND]}


def register_asset(db, user, customer_id, payload, idempotency_key):
    access = _access(db, user, customer_id, write=True)
    _account_for_update(db, access.customer_id)
    access = _access(db, user, access.customer_id, write=True)
    actor = access.actor_user_id
    owner = int(payload.get("owner_user_id") or actor)
    _active_user(db, owner)
    assigned = db.query(CustomerAssignment.id).filter(CustomerAssignment.customer_id == access.customer_id,
        CustomerAssignment.user_id == owner, CustomerAssignment.assignment_role.in_(("primary", "collaborator")),
        CustomerAssignment.assignment_status == "active", CustomerAssignment.effective_to.is_(None)).first()
    if assigned is None:
        raise pcw_errors.bad_request("服务负责人必须在当前客户团队内", error_code="SERVICE_OWNER_NOT_ASSIGNED")
    if payload["asset_type"] not in TYPES:
        raise pcw_errors.bad_request("服务入口类型不支持", error_code="SERVICE_ASSET_TYPE_INVALID")
    url = _entry_url(payload["entry_url"])
    request = {**payload, "owner_user_id": owner, "entry_url": url}

    def execute():
        rows = db.query(CustomerAnnotation).filter(logical_root_predicate(CustomerAnnotation, "annotation", access.customer_id),
            CustomerAnnotation.annotation_type == "note", CustomerAnnotation.content_schema_version == "v1",
            CustomerAnnotation.status == "active").with_for_update().all()
        existing = next((row for row in rows if (row.content_json or {}).get("kind") == KIND
            and row.content_json.get("asset_type") == payload["asset_type"]
            and row.content_json.get("entry_url") == url), None)
        if existing is not None:
            if (existing.content_json or {}).get("purpose") != payload["purpose"]:
                raise pcw_errors.conflict("该入口已有不同服务用途，请先撤销旧登记", error_code="SERVICE_ASSET_DUPLICATE")
            return serialize(existing)
        row = CustomerAnnotation(customer_id=access.customer_id, annotation_type="note",
            content_schema_version="v1", content_json={"kind": KIND, "asset_type": payload["asset_type"],
                "entry_url": url, "purpose": payload["purpose"], "owner_user_id": owner,
                "known_issue": payload.get("known_issue") or None},
            visibility="customer_team", data_classification="internal_business", status="active",
            authored_by=actor, created_at=beijing_now(), updated_at=beijing_now())
        db.add(row)
        db.flush()
        return serialize(row)

    result, _ = run_with_receipt(db, actor_user_id=actor, operation_scope=f"service_asset_register:{access.customer_id}",
        idempotency_key=idempotency_key, request_payload=request, execute=execute)
    return result


def revoke_asset(db, user, customer_id, asset_id, payload, idempotency_key):
    access = _access(db, user, customer_id, write=True)
    _account_for_update(db, access.customer_id)
    access = _access(db, user, access.customer_id, write=True)
    row = db.query(CustomerAnnotation).filter(CustomerAnnotation.id == asset_id,
        logical_root_predicate(CustomerAnnotation, "annotation", access.customer_id)).with_for_update().one_or_none()
    if row is None or (row.content_json or {}).get("kind") != KIND:
        raise pcw_errors.customer_not_found()

    def execute():
        if payload["expected_asset_version"] != 1 or row.status != "active":
            raise pcw_errors.conflict("服务入口登记版本或状态已变化", error_code="SERVICE_ASSET_VERSION_CONFLICT")
        row.status = "revoked"
        row.revoked_by = access.actor_user_id
        row.revoked_at = beijing_now()
        row.updated_at = row.revoked_at
        row.content_json = {**row.content_json, "revocation_reason": payload["reason"]}
        db.flush()
        return serialize(row)

    result, _ = run_with_receipt(db, actor_user_id=access.actor_user_id,
        operation_scope=f"service_asset_revoke:{asset_id}", idempotency_key=idempotency_key,
        request_payload=payload, execute=execute)
    return result
