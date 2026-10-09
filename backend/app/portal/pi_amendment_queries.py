"""Customer-safe PI confirmation view; caller has authorized the order and price scope."""
from copy import deepcopy
from sqlalchemy import select
from app.core.time import beijing_now
from app.invoice.models import Invoice, InvoiceItem
from app.portal import invoice_evidence, revision_comparison, revision_evidence
from app.portal.models import PiAmendment, Publication, RequestLine, Revision


def view(db, order):
    amendment = db.scalar(select(PiAmendment).where(PiAmendment.request_id == order.id))
    if amendment is None:
        return None
    result = {"status":amendment.status,"proposal":None}
    invoice = db.get(Invoice, amendment.invoice_id, populate_existing=True)
    items = db.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id == amendment.invoice_id)
        .execution_options(populate_existing=True)).all()
    if invoice is not None and invoice.status == "cancelled":
        return {"status":"voided","proposal":None}
    if invoice is None or invoice.status == "cancel_pending":
        return {"status":"withdrawn","proposal":None}
    digest = invoice_evidence.fingerprint(invoice,items)
    if amendment.status == "current":
        publication = db.scalar(select(Publication).where(Publication.request_id == order.id,
            Publication.invoice_document_version == invoice.portal_document_version,Publication.status == "published"))
        if publication is None or publication.customer_snapshot_json.get("invoice_document_hash") != digest:
            result["status"] = "withdrawn"
        return result
    if amendment.status not in {"pending_customer","accepted"}:
        return result
    revision = db.get(Revision,amendment.active_revision_id)
    if (revision is None or revision.request_id != order.id or revision.kind != "pi_amendment"
            or revision.bound_invoice_document_version != invoice.portal_document_version
            or revision.authority_versions_json.get("invoice_document_hash") != digest):
        return {"status":"withdrawn","proposal":None}
    records = db.scalars(select(RequestLine).where(RequestLine.revision_id == revision.id).order_by(RequestLine.id)).all()
    revision_evidence.verify(revision,records)
    result["proposal"] = {"revision_id":revision.public_id,"content_hash":revision.content_hash,
        "expires_at":revision.expires_at.isoformat(),"expired":revision.expires_at <= beijing_now(),
        "bound_invoice_document_version":revision.bound_invoice_document_version,
        "commercial_header":deepcopy(revision.invoice_presentation_json),
        **revision_comparison.scalar_view(revision),
        "items":[{"line_key":row.line_key,**revision_comparison.line_view(row)} for row in records],
        "changes":revision_comparison.previous_comparison(db,revision,records)}
    return result
