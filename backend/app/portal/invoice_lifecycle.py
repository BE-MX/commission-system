"""Transactional ORM protection for published portal invoices.

Header/line mutations invalidate publications in the same flush. Bulk SQL is not
covered; those writers must not modify portal documents without this protocol.
"""
from uuid import uuid4

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from app.invoice.models import Invoice, InvoiceItem
from app.portal.event_models import AuditEvent
from app.portal.order_models import Conversion, PiAmendment, Publication

HEADER_FIELDS = {
    "invoice_no", "order_type", "customer_id", "customer_name", "contact_name", "contact_phone",
    "contact_email", "delivery_address", "sales_user_id", "sales_user_name", "sales_phone", "sales_email",
    "invoice_date", "currency", "express_channel", "shipping_fee", "surcharge_name", "surcharge_amount",
    "payment_term", "product_amount", "total_amount", "internal_discount", "internal_accessory",
    "packaging_quantity", "remark",
}
LINE_FIELDS = {
    "sort_order", "product_kind", "item_type", "product_id", "sku_id", "custom_product_id", "product_name",
    "product_display", "net_weight_grams", "curl", "model", "color", "length", "quantity",
    "price_per_piece", "discount_amount", "total_price",
}
SOURCE_FIELDS = {"source_type", "source_order_id", "source_order_no", "source_order_name", "source_image_sha256"}


def changed(row):
    return {key for key in inspect(row).attrs.keys() if inspect(row).attrs[key].history.has_changes()}


def before_flush(db, context, instances):
    affected = set()
    for row in set(db.dirty) | set(db.new) | set(db.deleted):
        if isinstance(row, Invoice):
            state = inspect(row)
            if not state.persistent:
                continue  # Initial approval publishes the new document in version 1.
            fields = changed(row)
            prior = state.attrs.source_type.history.deleted
            portal = row.source_type == "portal" or "portal" in prior
            if fields & SOURCE_FIELDS:
                original_source = db.scalar(select(Invoice.source_type).where(Invoice.id == row.id).with_for_update())
                portal = portal or original_source == "portal"
            if not portal:
                continue
            if row in db.deleted:
                raise ValueError("Portal invoice lineage must be retained")
            if fields & SOURCE_FIELDS:
                raise ValueError("Portal invoice source identity is immutable")
            if "portal_document_version" in fields:
                raise ValueError("Portal document version is managed by the lifecycle protocol")
            if "status" in fields and row.status != "cancelled":
                # Lock the lineage regardless of current state: no snapshot-only
                # or nonmatching-row check can race the terminal transition.
                lineage_state = db.scalar(select(Conversion.status).where(Conversion.invoice_id == row.id).with_for_update())
                pending_tombstone = any(isinstance(value, Conversion) and value.invoice_id == row.id
                    and value.status == "tombstoned" for value in db.dirty)
                if lineage_state == "tombstoned" or pending_tombstone:
                    raise ValueError("A voided portal invoice cannot be reactivated")
            cancellation = "status" in fields and row.status in {"cancel_pending", "cancelled"}
            if fields & HEADER_FIELDS or cancellation or "items" in fields:
                affected.add(row)
        elif isinstance(row, InvoiceItem):
            state = inspect(row)
            reparented = (any(parent is not None for parent in state.attrs.invoice.history.added)
                          or any(identity is not None for identity in state.attrs.invoice_id.history.added))
            if state.persistent and reparented:
                parents = list(state.attrs.invoice.history.deleted) + list(state.attrs.invoice.history.added)
                identities = set(state.attrs.invoice_id.history.deleted) | set(state.attrs.invoice_id.history.added)
                identities.add(db.scalar(select(InvoiceItem.invoice_id).where(InvoiceItem.id == row.id).with_for_update()))
                parents.extend(db.get(Invoice, identity) for identity in identities if identity is not None)
                if any(parent is not None and parent.source_type == "portal" for parent in parents):
                    raise ValueError("Portal invoice lines cannot be reassigned to another invoice")
            if not (row in db.new or row in db.deleted or changed(row) & LINE_FIELDS):
                continue
            parent = row.invoice if row.invoice is not None else db.get(Invoice, row.invoice_id)
            if parent is not None and inspect(parent).persistent and parent.source_type == "portal":
                affected.add(parent)
    for invoice in sorted(affected, key=lambda row: row.id):
        conversion = db.scalar(select(Conversion).where(Conversion.invoice_id == invoice.id,
            Conversion.status.in_(("created", "tombstoned"))))
        if conversion is None:
            continue  # create_invoice can autoflush before its initial lines/totals are complete.
        # Lock/current-read scalar only: refreshing the entity would erase pending edits.
        stored = db.execute(select(Invoice.portal_document_version).where(Invoice.id == invoice.id).with_for_update()).scalar_one()
        if stored != invoice.portal_document_version:
            raise ValueError("Portal invoice changed concurrently; reload before editing")
        invoice.portal_document_version = stored + 1
        publications = db.scalars(select(Publication).where(Publication.invoice_id == invoice.id,
            Publication.status == "published").with_for_update().execution_options(populate_existing=True)).all()
        for publication in publications:
            publication.status = "withdrawn"
        amendment = db.scalar(select(PiAmendment).where(PiAmendment.invoice_id == invoice.id)
            .with_for_update().execution_options(populate_existing=True))
        if amendment is not None:
            amendment.status = "withdrawn"
            amendment.active_revision_id = None
            amendment.accepted_revision_id = None
            amendment.row_version += 1
        db.add(AuditEvent(actor_type="system", actor_id=None, access_id=None,
            object_type="invoice", object_public_id=conversion.public_id,
            action="invoice.portal_withdrawn", before_version=stored, after_version=stored+1,
            reason="Customer-visible invoice content changed", trace_id=str(uuid4()),
            safe_diff_json={"invoice_id":invoice.id, "publication_count":len(publications)}))


def install_guard():
    if not event.contains(Session, "before_flush", before_flush):
        event.listen(Session, "before_flush", before_flush)
