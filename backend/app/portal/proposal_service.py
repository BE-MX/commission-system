"""Employee proposals use current standard prices and require fresh customer acceptance."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.time import beijing_now
from app.invoice.delegation_service import can_act_for
from app.portal import admin_service as admin, order_commands, quote_service, revision_evidence
from app.portal.access_policy import validate_binding
from app.portal.domain import content_hash, request_transition, require_version, total_amount
from app.portal.errors import reject
from app.portal.models import AuditEvent, CommandReceipt, CustomerAccess, OrderRequest, OutboxEvent, RequestLine, Revision
from app.portal.schemas import SitePolicy


def company_versions(access, site):
    return {"access": access.auth_version, "catalog": access.catalog_version,
            "mapping": access.mapping_version, "policy": site.policy_version,
            "binding": access.binding_fingerprint, "sales_user_id": access.sales_user_id}


def managed_request(db, actor_id, public_id):
    actor = admin.begin(db, actor_id, "portal_order:write")
    site = admin.site_for_admin(db)
    order = db.scalar(select(OrderRequest).join(CustomerAccess, CustomerAccess.id == OrderRequest.access_id)
        .where(OrderRequest.public_id == str(public_id), CustomerAccess.site_id == site.id)
        .with_for_update().execution_options(populate_existing=True))
    access = None if order is None else db.get(CustomerAccess, order.access_id, populate_existing=True)
    if order is None or order.servicing_user_id != access.sales_user_id or not can_act_for(db, actor_id, access.sales_user_id):
        reject("RESOURCE_NOT_FOUND", "订单不存在或不在当前处理权限范围内。", 404)
    validate_binding(db, access)
    return actor, site, access, order


def create(db, actor_id, public_id, expected, body):
    actor, site, access, order = managed_request(db, actor_id, public_id)
    command_key = "propose:" + str(expected)
    payload_hash = content_hash(body.model_dump(mode="json"))
    saved = db.scalar(select(CommandReceipt).where(CommandReceipt.action == "propose",
        CommandReceipt.object_public_id == order.public_id, CommandReceipt.command_key == command_key))
    if saved is not None:
        if saved.payload_hash != payload_hash:
            reject("IDEMPOTENCY_CONFLICT", "该版本已提交不同提案，请刷新后查看。", 409)
        return {"replayed": True, "original_receipt": deepcopy(saved.result_reference_json),
                "current_state": order.status, "row_version": order.row_version}
    state, term, lines = prepare(db, site, access, order, expected, body)
    previous_lines = db.scalars(select(RequestLine).where(RequestLine.revision_id == order.active_revision_id)).all()
    stable_keys = {row.catalog_item_id: row.line_key for row in previous_lines}
    # IDs are resolved only from the same currently authorized company catalog.
    from app.portal.catalog_service import authorized_items
    from types import SimpleNamespace
    items = {item.public_id: item for item in authorized_items(db, SimpleNamespace(access=access, site=site))}
    fees = body.fees
    product_amount, amount = total_amount([line["line_amount"] for line in lines],
        fees.shipping_amount, fees.packaging_amount, fees.surcharge_amount)
    now = beijing_now().replace(microsecond=0)
    number = db.scalar(select(func.max(Revision.revision_no)).where(Revision.request_id == order.id)) or 0
    revision = Revision(public_id=str(uuid4()), request_id=order.id, revision_no=number+1, kind="proposal",
        currency=site.currency, product_amount=product_amount, shipping_amount=Decimal(fees.shipping_amount),
        packaging_amount=Decimal(fees.packaging_amount), surcharge_amount=Decimal(fees.surcharge_amount),
        surcharge_name=fees.surcharge_name, total_amount=amount, fees_status="confirmed",
        delivery_json=body.delivery.model_dump(mode="json"), payment_terms_snapshot=term.model_dump(mode="json"),
        expires_at=now+timedelta(hours=body.valid_for_hours), authority_versions_json=company_versions(access, site),
        remark=body.remark, mapping_version=access.mapping_version,
        pricing_fingerprint=content_hash({line["item_id"]: line["price_fingerprint"] for line in lines}),
        bound_invoice_document_version=None, created_by=actor["id"])
    records = []
    for line in lines:
        item = items[line["item_id"]]
        standard, inventory = line["standard_snapshot"], line["inventory_snapshot"]
        records.append(RequestLine(line_key=stable_keys.get(item.id, line["line_key"]), catalog_item_id=item.id,
            product_kind=standard["product_kind"], product_id=standard["product_id"], sku_id=standard["sku_id"],
            standard_json=deepcopy(standard["standard_json"]), customer_display_json=deepcopy(line["display_snapshot"]),
            mapping_version=access.mapping_version, qty=line["quantity"], unit_price=Decimal(line["unit_price"]),
            discount_amount=Decimal(line["discount_amount"]), line_amount=Decimal(line["line_amount"]),
            unit_weight_grams=Decimal(inventory["conversion_factor"]) if inventory["unit"] == "g" else None,
            price_source="ark_customer_rule", price_fingerprint=line["price_fingerprint"]))
    revision.content_hash = revision_evidence.digest(revision, records)
    db.add(revision)
    db.flush()
    for line in records:
        line.revision_id = revision.id
        db.add(line)
    before = order.row_version
    order.active_revision_id = revision.id
    order.accepted_revision_id = None
    order.status = state
    order.row_version += 1
    result = {"request_id": order.public_id, "revision_id": revision.public_id,
              "content_hash": revision.content_hash, "expires_at": revision.expires_at.isoformat(),
              "row_version": order.row_version}
    db.add(CommandReceipt(action="propose", object_public_id=order.public_id, command_key=command_key,
        payload_hash=payload_hash, result_reference_json=result, first_actor_type="employee", first_actor_id=actor["id"], completed_at=now))
    db.add(AuditEvent(actor_type="employee", actor_id=actor["id"], access_id=access.id,
        object_type="order_request", object_public_id=order.public_id, action="order.proposed",
        before_version=before, after_version=order.row_version, reason=body.reason, trace_id=str(uuid4()),
        safe_diff_json={"revision_id": revision.public_id}))
    db.add(OutboxEvent(event_key="order.proposed:"+revision.public_id, event_type="order_proposed",
        aggregate_public_id=order.public_id, payload_json={"request_id": order.public_id, "revision_id": revision.public_id}, next_attempt_at=now))
    db.flush()
    return {"replayed": False, "original_receipt": result, "current_state": state, "row_version": order.row_version}


def require_proposable(db, site, access, order, expected):
    quote_service.require_writes()
    require_version(order.row_version, expected)
    if access.status != "enabled" or site.status != "enabled" or not (access.can_order and access.can_view_price):
        reject("ACTION_FORBIDDEN", "客户当前未启用下单及查价权限。", 403)
    if order_commands.has_invoice_lineage(db, order):
        reject("INVOICE_ALREADY_CREATED", "已建票请求须走PI修订流程。", 409)
    if order.status == "awaiting_customer":
        from app.portal.order_queries import load_revision
        active, _ = load_revision(db, order)
        if active.kind != "proposal" or active.expires_at > beijing_now():
            reject("VERSION_CONFLICT", "当前提案仍待客户确认，请等待确认或拒绝。", 409)
        state = "awaiting_customer"  # Replace expired evidence with a new revision.
    else:
        state = request_transition(order.status, "propose")
    return state


def prepare(db, site, access, order, expected, body):
    state = require_proposable(db, site, access, order, expected)
    if body.customer_po != order.customer_po:
        reject("INVALID_INPUT", "提案不能静默修改客户采购单号。", 422)
    try:
        policy = SitePolicy.model_validate(site.policy_json)
    except ValidationError:
        reject("POLICY_UNAVAILABLE", "站点交易政策需要复核。", 503)
    term = next((value for value in policy.payment_terms if value.code == body.payment_terms), None)
    if term is None or body.valid_for_hours not in policy.proposal_valid_hours:
        reject("INVALID_INPUT", "请选择站点允许的付款条件和有效期。", 422)
    lines = quote_service.build_lines(db, access, site, body.items)
    return state, term, lines
