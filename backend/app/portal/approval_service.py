"""Atomic employee approval: one request, one permanent PI lineage.

All source reads are local. Caller commits or rolls back the entire transaction.
"""
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from app.core.time import beijing_now
from app.customer.models import CustomerAccount
from app.portal import admin_service as admin, invoice_adapter, order_queries, proposal_decisions, proposal_service, quote_service
from app.portal.domain import content_hash, request_transition, require_version
from app.portal.errors import reject
from app.portal.models import AuditEvent, CommandReceipt, Conversion, OutboxEvent, PiAmendment, Publication, Revision


def approve(db, actor_id, public_id, expected, body):
    actor, site, access, order = proposal_service.managed_request(db, actor_id, public_id)
    admin.employee_principal(db, actor_id, "invoice:write")
    revision = db.scalar(select(Revision).where(Revision.public_id == str(body.accepted_revision_id),
        Revision.request_id == order.id).execution_options(populate_existing=True))
    if revision is None:
        reject("RESOURCE_NOT_FOUND", "该确认版本不存在。", 404)
    key = revision.public_id + ":" + revision.content_hash
    payload_hash = content_hash(body.model_dump(mode="json"))
    saved = db.scalar(select(CommandReceipt).where(CommandReceipt.action == "approve",
        CommandReceipt.object_public_id == order.public_id, CommandReceipt.command_key == key))
    if saved is not None:
        if saved.payload_hash != payload_hash:
            reject("IDEMPOTENCY_CONFLICT", "审核命令与原成功记录不一致。", 409)
        return {"replayed": True, "original_receipt": deepcopy(saved.result_reference_json),
                "current_state": order.status, "row_version": order.row_version}
    lineage = db.scalar(select(Conversion).where(Conversion.request_id == order.id))
    if lineage is not None or order.invoice_id is not None:
        reject("INVOICE_ALREADY_CREATED", "该请求已经建票，不能重复创建。", 409)
    quote_service.require_writes()
    if not quote_service.get_settings().PORTAL_INVOICE_ENABLED:
        reject("SERVICE_UNAVAILABLE", "门户建票尚未启用。", 503)
    require_version(order.row_version, expected)
    if site.status != "enabled" or access.status != "enabled" or not (access.can_order and access.can_view_price):
        reject("ACTION_FORBIDDEN", "客户当前未启用交易权限。", 403)
    if order.active_revision_id != revision.id or order.accepted_revision_id != revision.id:
        reject("CUSTOMER_ACCEPTANCE_REQUIRED", "请先取得客户对当前提案的确认。", 409)
    new_state = request_transition(order.status, "approve")
    revision, records = order_queries.load_revision(db, order)
    proposal_decisions.revalidate(db, SimpleNamespace(access=access, site=site), revision, records)
    customer = db.get(CustomerAccount, access.customer_id, populate_existing=True)
    if customer is None or customer.record_status != "active":
        reject("CUSTOMER_BINDING_CHANGED", "客户档案需要复核。", 409)
    conversion = Conversion(request_id=order.id, approved_revision_id=revision.id,
        operation_key=content_hash({"request_id": order.public_id}), payload_hash=payload_hash,
        status="pending", created_by=actor_id)
    db.add(conversion)
    db.flush()
    try:
        invoice = invoice_adapter.create(db, order, access, revision, records,
            actor_id=actor_id, customer_name=customer.canonical_company_name or customer.display_name)
    except ValueError:
        reject("INVOICE_VALIDATION_FAILED", "方舟建票校验未通过，请业务员复核后重试。", 409)
    # Domain creation may span the proposal or inventory freshness boundary.
    proposal_decisions.revalidate(db, SimpleNamespace(access=access, site=site), revision, records)
    now = beijing_now().replace(microsecond=0)
    conversion.invoice_id = invoice.id
    conversion.invoice_document_version = invoice.portal_document_version
    conversion.status = "created"
    db.flush()  # Composite FK targets must exist before publication/amendment.
    before = order.row_version
    order.invoice_id = invoice.id
    order.status = new_state
    order.row_version += 1
    view = order_queries.detail_view(db, order, show_price=True)
    snapshot = {key: view[key] for key in ("request_id", "request_no", "customer_po", "currency", "product_amount",
        "total_amount", "fees", "payment_terms_snapshot", "delivery", "remark", "items")}
    snapshot.update(invoice_no=invoice.invoice_no, customer_name=invoice.customer_name,
        invoice_date=invoice.invoice_date.isoformat(), line_bindings=[{
            "line_key": record.line_key, "invoice_item_id_at_publication": item.id,
            "product_id": record.product_id, "sku_id": record.sku_id}
            for record, item in zip(records, sorted(invoice.items, key=lambda row: row.sort_order))])
    from app.portal.invoice_evidence import fingerprint
    from app.portal.pi_presentation import capture
    snapshot["commercial_header"] = capture(invoice)
    snapshot["invoice_document_hash"] = fingerprint(invoice)
    snapshot["snapshot_hash"] = content_hash(snapshot)
    db.add(Publication(request_id=order.id, invoice_id=invoice.id,
        invoice_document_version=invoice.portal_document_version, revision_id=revision.id,
        content_hash=revision.content_hash, customer_snapshot_json=snapshot, render_template_version="portal-pi-v1",
        status="published", published_by=actor_id, published_at=now))
    db.add(PiAmendment(request_id=order.id, invoice_id=invoice.id, status="current",
        active_revision_id=revision.id, accepted_revision_id=revision.id))
    result = {"request_id": order.public_id, "invoice_id": invoice.id, "invoice_no": invoice.invoice_no,
        "revision_id": revision.public_id, "invoice_document_version": invoice.portal_document_version,
        "row_version": order.row_version}
    db.add(CommandReceipt(action="approve", object_public_id=order.public_id, command_key=key,
        payload_hash=payload_hash, result_reference_json=result, first_actor_type="employee",
        first_actor_id=actor_id, completed_at=now))
    db.add(AuditEvent(actor_type="employee", actor_id=actor_id, access_id=access.id,
        object_type="order_request", object_public_id=order.public_id, action="order.invoice_created",
        before_version=before, after_version=order.row_version, reason="", trace_id=str(uuid4()),
        safe_diff_json={"revision_id": revision.public_id, "invoice_id": invoice.id}))
    db.add(OutboxEvent(event_key="order.invoice_created:"+order.public_id, event_type="order_invoice_created",
        aggregate_public_id=order.public_id, payload_json={"request_id": order.public_id,
        "invoice_id": invoice.id}, next_attempt_at=now))
    db.flush()
    return {"replayed": False, "original_receipt": result, "current_state": order.status, "row_version": order.row_version}


def invoice_number_conflict(error):
    """Only the known invoice number uniqueness conflict is retryable."""
    import re
    args = getattr(error.orig, "args", ())
    if args and args[0] == 1062:
        match = re.search(r"for key ['`]([^'`]+)['`]", str(args[1]))
        return bool(match and match.group(1).split(".")[-1] in {"uq_ark_invoices_invoice_no", "invoice_no"})
    return str(error.orig) == "UNIQUE constraint failed: ark_invoices.invoice_no"


def record_failure(db, actor_id, public_id, code):
    # Caller has rolled back the business transaction. Store only safe references.
    db.add(AuditEvent(actor_type="system", actor_id=None, access_id=None,
        object_type="order_request", object_public_id=str(public_id), action="order.approval_failed",
        reason=code, trace_id=str(uuid4()), safe_diff_json={"employee_id":actor_id}))
    db.commit()

def execute(db, actor_id, public_id, expected, body):
    """HTTP transaction owner; retries restart authorization and all domain reads."""
    from sqlalchemy.exc import IntegrityError
    from app.portal.errors import PortalError
    for attempt in range(3):
        try:
            result = approve(db, actor_id, public_id, expected, body)
            db.commit()
            return result
        except IntegrityError as error:
            db.rollback()
            if not invoice_number_conflict(error):
                raise
            if attempt == 2:
                record_failure(db, actor_id, public_id, "INVOICE_NUMBER_CONFLICT")
                reject("INVOICE_NUMBER_CONFLICT", "发票编号并发冲突，请重试审核。", 409)
        except PortalError as error:
            db.rollback()
            record_failure(db, actor_id, public_id, error.code)
            raise
        except Exception:
            db.rollback()
            raise


