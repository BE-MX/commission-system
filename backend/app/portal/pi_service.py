"""Authorized PI downloads with rendering outside locks and a final current-state check."""
from copy import deepcopy
from uuid import uuid4
from sqlalchemy import select

from app.invoice.models import Invoice, InvoiceItem
from app.portal import auth_service as auth, invoice_evidence
from app.portal.domain import content_hash
from app.portal.errors import reject
from app.portal.models import AuditEvent, Conversion, OrderRequest, PiAmendment, Publication


def capture(db, token, request_id):
    principal, _ = auth.authenticate(db, token)
    principal.require("pi")
    order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == str(request_id),
        OrderRequest.access_id == principal.access.id).execution_options(populate_existing=True))
    if order is None:
        reject("RESOURCE_NOT_FOUND", "This order request is not available.", 404)
    conversion = db.scalar(select(Conversion).where(Conversion.request_id == order.id)
        .execution_options(populate_existing=True))
    if order.status != "invoice_created" or conversion is None or conversion.status != "created" or order.invoice_id != conversion.invoice_id:
        reject("PI_REVISION_PENDING", "Your PI is not available. Please contact your account manager.", 409)
    invoice = db.scalar(select(Invoice).where(Invoice.id == conversion.invoice_id).with_for_update()
        .execution_options(populate_existing=True))
    if invoice is None or invoice.source_type != "portal" or invoice.source_order_id != order.public_id or invoice.status in {"cancel_pending", "cancelled"}:
        reject("PI_REVISION_PENDING", "Your PI needs review.", 409)
    items = db.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id).with_for_update()
        .execution_options(populate_existing=True)).all()
    publication = db.scalar(select(Publication).where(Publication.request_id == order.id,
        Publication.invoice_id == invoice.id, Publication.invoice_document_version == invoice.portal_document_version,
        Publication.status == "published").with_for_update().execution_options(populate_existing=True))
    amendment = db.scalar(select(PiAmendment).where(PiAmendment.request_id == order.id)
        .with_for_update().execution_options(populate_existing=True))
    if publication is None or amendment is None or amendment.status != "current" or amendment.accepted_revision_id != publication.revision_id:
        reject("PI_REVISION_PENDING", "Your updated PI is awaiting confirmation.", 409)
    if publication.render_template_version != "portal-pi-v1":
        reject("PDF_UNAVAILABLE", "This PI template is not available. Please contact your account manager.", 503)
    snapshot = deepcopy(publication.customer_snapshot_json)
    snapshot_hash = snapshot.pop("snapshot_hash", None)
    if (not snapshot_hash or content_hash(snapshot) != snapshot_hash
            or snapshot.get("invoice_document_hash") != invoice_evidence.fingerprint(invoice, items)):
        reject("PI_REVISION_PENDING", "The PI content changed and needs review.", 409)
    ticket = {"publication_id":publication.public_id, "invoice_document_version":invoice.portal_document_version,
              "snapshot_hash":snapshot_hash, "request_id":order.public_id}
    return principal, ticket, snapshot


def download(db, token, request_id):
    from app.portal.pi_pdf import render
    try:
        _, ticket, snapshot = capture(db, token, request_id)
        db.commit()
        pdf = render(snapshot)  # No database locks while paginating or embedding fonts.
        principal, latest, _ = capture(db, token, request_id)
        if latest != ticket:
            reject("PI_REVISION_PENDING", "Your PI changed. Refresh before downloading.", 409)
        db.add(AuditEvent(actor_type="customer", actor_id=principal.account.id, access_id=principal.access.id,
            object_type="order_request", object_public_id=str(request_id), action="order.pi_downloaded",
            reason="", trace_id=str(uuid4()), safe_diff_json={"publication_id":ticket["publication_id"]}))
        db.commit()
        return pdf, "PI-"+ticket["request_id"]+".pdf"
    except Exception:
        db.rollback()
        raise
