"""Customer confirmation and publication of an existing PI; never creates invoices."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from app.core.time import beijing_now
from app.invoice.delegation_service import can_act_for
from app.invoice.models import Invoice, InvoiceItem
from app.portal import admin_service as admin, auth_service as auth, invoice_evidence, pi_revision_source, pi_presentation
from app.portal import proposal_service, quote_service, revision_comparison, revision_evidence
from app.portal.access_policy import validate_binding
from app.portal.domain import content_hash, require_fresh, require_version
from app.portal.errors import reject
from app.portal.models import AuditEvent, CommandReceipt, Conversion, CustomerAccess, OrderRequest, OutboxEvent, PiAmendment, Publication, RequestLine, Revision


def locked_order(db, public_id, access_id=None):
    query = select(OrderRequest).where(OrderRequest.public_id == str(public_id))
    if access_id is not None:
        query = query.where(OrderRequest.access_id == access_id)
    order = db.scalar(query.with_for_update().execution_options(populate_existing=True))
    if order is None:
        reject("RESOURCE_NOT_FOUND", "This order request is not available.", 404)
    return order


def load_pi(db, order):
    conversion = db.scalar(select(Conversion).where(Conversion.request_id == order.id).execution_options(populate_existing=True))
    if order.status != "invoice_created" or conversion is None or conversion.status != "created" or conversion.invoice_id != order.invoice_id:
        reject("PI_REVISION_PENDING", "This PI needs review.", 409)
    invoice = db.scalar(select(Invoice).where(Invoice.id == conversion.invoice_id).with_for_update().execution_options(populate_existing=True))
    items = db.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id == conversion.invoice_id).with_for_update().execution_options(populate_existing=True)).all()
    amendment = db.scalar(select(PiAmendment).where(PiAmendment.request_id == order.id, PiAmendment.invoice_id == conversion.invoice_id)
        .with_for_update().execution_options(populate_existing=True))
    if invoice is None or amendment is None or invoice.source_type != "portal" or invoice.source_order_id != order.public_id:
        reject("PI_REVISION_PENDING", "This PI needs review.", 409)
    return invoice, items, amendment


def employee_context(db, actor_id, public_id):
    admin.begin(db, actor_id, "portal_order:write")
    admin.employee_principal(db, actor_id, "invoice:write")
    site = admin.site_for_admin(db)
    order = locked_order(db, public_id)
    access = db.get(CustomerAccess, order.access_id, populate_existing=True)
    if access.site_id != site.id or not can_act_for(db, actor_id, access.sales_user_id):
        reject("RESOURCE_NOT_FOUND", "This request is outside your current scope.", 404)
    validate_binding(db, access)
    invoice, items, amendment = load_pi(db, order)
    if not can_act_for(db, actor_id, invoice.sales_user_id):
        reject("RESOURCE_NOT_FOUND", "PI ownership requires an explicit delegation.", 404)
    if site.status != "enabled" or access.status != "enabled" or not (access.can_order and access.can_view_price):
        reject("ACTION_FORBIDDEN", "The customer is not enabled for ordering.", 403)
    return SimpleNamespace(access=access, site=site), order, invoice, items, amendment


def replay(db, order, amendment, action, key, body):
    row = db.scalar(select(CommandReceipt).where(CommandReceipt.action == action,
        CommandReceipt.object_public_id == order.public_id, CommandReceipt.command_key == key))
    if row is None:
        return None
    if row.payload_hash != content_hash(body.model_dump(mode="json")):
        reject("IDEMPOTENCY_CONFLICT", "This action was recorded with different content.", 409)
    return {"replayed":True,"original_receipt":deepcopy(row.result_reference_json),
        "current_state":order.status,"amendment_state":amendment.status,"row_version":order.row_version}


def record(db, principal, order, amendment, revision, action, key, body, actor_type, actor_id):
    before = order.row_version
    order.row_version += 1
    amendment.row_version += 1
    result = {"request_id":order.public_id,"revision_id":revision.public_id,
        "content_hash":revision.content_hash,"invoice_document_version":revision.bound_invoice_document_version,
        "expires_at":revision.expires_at.isoformat(),"row_version":order.row_version}
    now = beijing_now()
    db.add(CommandReceipt(action=action,object_public_id=order.public_id,command_key=key,
        payload_hash=content_hash(body.model_dump(mode="json")),result_reference_json=result,
        first_actor_type=actor_type,first_actor_id=actor_id,completed_at=now))
    db.add(AuditEvent(actor_type=actor_type,actor_id=actor_id,access_id=principal.access.id,
        object_type="order_request",object_public_id=order.public_id,action="order."+action,
        before_version=before,after_version=order.row_version,reason=getattr(body,"reason",""),
        trace_id=str(uuid4()),safe_diff_json={"revision_id":revision.public_id}))
    db.add(OutboxEvent(event_key=action+":"+revision.public_id,event_type=action,
        aggregate_public_id=order.public_id,payload_json={"request_id":order.public_id,"revision_id":revision.public_id},next_attempt_at=now))
    db.flush()
    return {"replayed":False,"original_receipt":result,"current_state":order.status,
        "amendment_state":amendment.status,"row_version":order.row_version}


def create(db, actor_id, public_id, expected, body):
    principal, order, invoice, items, amendment = employee_context(db, actor_id, public_id)
    key = "pi-propose:"+str(expected)
    saved = replay(db,order,amendment,"pi_proposed",key,body)
    if saved:
        return saved
    quote_service.require_writes()
    require_version(order.row_version, expected)
    require_version(invoice.portal_document_version, body.invoice_document_version)
    if amendment.status in {"pending_customer","accepted"}:
        prior = db.get(Revision, amendment.active_revision_id)
        if prior is None or prior.expires_at > beijing_now():
            reject("VERSION_CONFLICT", "The current PI proposal is still active.", 409)
    elif amendment.status != "withdrawn":
        reject("VERSION_CONFLICT", "Edit the PI before proposing an update.", 409)
    revision, records = pi_revision_source.build(db,principal.access,principal.site,order,invoice,items,
        actor_id=actor_id,valid_for_hours=body.valid_for_hours)
    db.add(revision)
    db.flush()
    for row in records:
        row.revision_id = revision.id
        db.add(row)
    amendment.active_revision_id = revision.id
    amendment.accepted_revision_id = None
    amendment.status = "pending_customer"
    return record(db,principal,order,amendment,revision,"pi_proposed",key,body,"employee",actor_id)


def revision_for(db, order, revision_id):
    revision = db.scalar(select(Revision).where(Revision.request_id == order.id, Revision.public_id == str(revision_id))
        .execution_options(populate_existing=True))
    if revision is None or revision.kind != "pi_amendment":
        reject("RESOURCE_NOT_FOUND", "This PI proposal is not available.", 404)
    records = db.scalars(select(RequestLine).where(RequestLine.revision_id == revision.id).order_by(RequestLine.id)).all()
    revision_evidence.verify(revision,records)
    return revision,records


def revalidate(db, principal, order, invoice, items, revision, records):
    revision_evidence.verify(revision,records)
    require_fresh(revision.expires_at,beijing_now())
    require_version(invoice.portal_document_version,revision.bound_invoice_document_version)
    expected = proposal_service.company_versions(principal.access,principal.site)
    expected.update(invoice_document_hash=invoice_evidence.fingerprint(invoice,items),invoice_sales_user_id=invoice.sales_user_id)
    if (expected != revision.authority_versions_json
            or revision.invoice_presentation_json != pi_presentation.capture(invoice)):
        reject("PROPOSAL_CHANGED", "PI content or authorization changed. Request a new proposal.", 409)
    # Validate current eligibility and inventory without replacing accepted PI prices.
    pi_revision_source.build(db,principal.access,principal.site,order,invoice,items,
        actor_id=revision.created_by,valid_for_hours=None)
    require_fresh(revision.expires_at,beijing_now())


def decide(db, token, csrf, public_id, revision_id, expected, body, *, accept):
    principal,_ = auth.authenticate(db,token,csrf=csrf,write=True)
    principal.require("accept" if accept else "reject")
    order = locked_order(db,public_id,principal.access.id)
    invoice,items,amendment = load_pi(db,order)
    revision,records = revision_for(db,order,revision_id)
    action = "pi_accepted" if accept else "pi_rejected"
    key = revision.public_id + (":"+body.proposal_hash if accept else "")
    saved = replay(db,order,amendment,action,key,body)
    if saved:
        return saved
    quote_service.require_writes()
    require_version(order.row_version,expected)
    if amendment.status != "pending_customer" or amendment.active_revision_id != revision.id:
        reject("PROPOSAL_SUPERSEDED", "Review the current PI proposal.", 409)
    if accept:
        if body.proposal_hash != revision.content_hash:
            reject("PROPOSAL_CHANGED", "PI proposal content changed.", 409)
        revalidate(db,principal,order,invoice,items,revision,records)
        revision.customer_accepted_by = principal.account.id
        revision.customer_accepted_at = beijing_now()
        amendment.accepted_revision_id = revision.id
        amendment.status = "accepted"
    else:
        amendment.accepted_revision_id = None
        amendment.status = "withdrawn"
    return record(db,principal,order,amendment,revision,action,key,body,"customer",principal.account.id)


def publish(db, actor_id, public_id, expected, body):
    principal,order,invoice,items,amendment = employee_context(db,actor_id,public_id)
    revision,records = revision_for(db,order,body.accepted_revision_id)
    key = str(body.invoice_document_version)+":"+revision.public_id+":"+revision.content_hash
    saved = replay(db,order,amendment,"pi_published",key,body)
    if saved:
        return saved
    quote_service.require_writes()
    require_version(order.row_version,expected)
    require_version(invoice.portal_document_version,body.invoice_document_version)
    if (amendment.status != "accepted" or amendment.accepted_revision_id != revision.id
            or amendment.active_revision_id != revision.id or revision.customer_accepted_by is None):
        reject("CUSTOMER_ACCEPTANCE_REQUIRED", "Customer confirmation of the current PI is required.", 409)
    revalidate(db,principal,order,invoice,items,revision,records)
    by_sku = {(row.product_kind,str(row.product_id),str(row.sku_id)):row for row in items}
    snapshot = {"request_id":order.public_id,"request_no":order.public_no,"customer_po":order.customer_po,
        "currency":revision.currency,"product_amount":revision_evidence.fixed(revision.product_amount),
        "total_amount":revision_evidence.fixed(revision.total_amount),"fees":{"status":"confirmed",
            **{key:revision_evidence.fixed(getattr(revision,key)) for key in ("shipping_amount","packaging_amount","surcharge_amount")},
            "surcharge_name":revision.surcharge_name},"delivery":deepcopy(revision.delivery_json),
        "payment_terms_snapshot":deepcopy(revision.payment_terms_snapshot),"remark":revision.remark,
        "items":[{"line_key":row.line_key,**revision_comparison.line_view(row)} for row in records],
        "commercial_header":deepcopy(revision.invoice_presentation_json),
        **{key:revision.invoice_presentation_json[key] for key in ("invoice_no","customer_name","invoice_date")},
        "line_bindings":[{"line_key":row.line_key,"product_id":row.product_id,"sku_id":row.sku_id,
            "invoice_item_id_at_publication":by_sku[(row.product_kind,row.product_id,row.sku_id)].id} for row in records],
        "invoice_document_hash":invoice_evidence.fingerprint(invoice,items)}
    snapshot["snapshot_hash"] = content_hash(snapshot)
    existing = db.scalar(select(Publication).where(Publication.invoice_id == invoice.id,
        Publication.invoice_document_version == invoice.portal_document_version))
    if existing is not None:
        reject("VERSION_CONFLICT", "This PI version already has a publication record.", 409)
    db.add(Publication(request_id=order.id,invoice_id=invoice.id,invoice_document_version=invoice.portal_document_version,
        revision_id=revision.id,content_hash=revision.content_hash,customer_snapshot_json=snapshot,
        render_template_version="portal-pi-v1",status="published",published_by=actor_id,published_at=beijing_now()))
    amendment.status = "current"
    return record(db,principal,order,amendment,revision,"pi_published",key,body,"employee",actor_id)
