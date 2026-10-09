"""Customer-safe immutable revision comparisons; no current catalog or price lookup."""
from copy import deepcopy
from sqlalchemy import select
from app.portal import revision_evidence
from app.portal.models import RequestLine, Revision

DISPLAY_KEYS = ("item_id", "model_name", "color_name", "customer_sku", "length", "weight", "unit")


def line_view(row):
    return {"display_snapshot":{key:deepcopy(row.customer_display_json.get(key)) for key in DISPLAY_KEYS},
        "quantity":row.qty, "unit_price":revision_evidence.fixed(row.unit_price,4),
        "discount_amount":revision_evidence.fixed(row.discount_amount), "line_amount":revision_evidence.fixed(row.line_amount)}


def compare_lines(before, after):
    changes = []
    for key in list(before) + [key for key in after if key not in before]:
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        fields = [field for field in ("display_snapshot","quantity","unit_price","discount_amount","line_amount")
                  if (old or {}).get(field) != (new or {}).get(field)]
        changes.append({"line_key":key, "change":"added" if old is None else "removed" if new is None else "changed",
            "before":old, "after":new, "changed_fields":fields})
    return changes


def scalar_view(revision):
    return {"currency":revision.currency, "product_amount":revision_evidence.fixed(revision.product_amount),
        "shipping_amount":revision_evidence.fixed(revision.shipping_amount),
        "packaging_amount":revision_evidence.fixed(revision.packaging_amount),
        "surcharge_amount":revision_evidence.fixed(revision.surcharge_amount), "surcharge_name":revision.surcharge_name,
        "total_amount":revision_evidence.fixed(revision.total_amount), "fees_status":revision.fees_status,
        "delivery":deepcopy(revision.delivery_json), "payment_terms":deepcopy(revision.payment_terms_snapshot),
        "remark":revision.remark}


def previous_comparison(db, revision, records):
    previous = db.scalar(select(Revision).where(Revision.request_id == revision.request_id,
        Revision.revision_no < revision.revision_no).order_by(Revision.revision_no.desc()).limit(1))
    if previous is None:
        return None
    old_records = db.scalars(select(RequestLine).where(RequestLine.revision_id == previous.id).order_by(RequestLine.id)).all()
    revision_evidence.verify(previous, old_records)
    before, after = scalar_view(previous), scalar_view(revision)
    if revision.kind == "pi_amendment":
        from app.portal.models import Publication
        from app.portal.pi_presentation import project
        old_header = previous.invoice_presentation_json
        if old_header is None:
            publication = db.scalar(select(Publication).where(Publication.revision_id == previous.id,
                Publication.request_id == revision.request_id).order_by(Publication.invoice_document_version.desc()).limit(1))
            snapshot = {} if publication is None else publication.customer_snapshot_json
            old_header = snapshot.get("commercial_header", snapshot)
        before["commercial_header"] = project(old_header)
        after["commercial_header"] = project(revision.invoice_presentation_json or {})
    return {"before_revision_id":previous.public_id, "before_revision_kind":previous.kind,
        "after_revision_id":revision.public_id, "after_revision_kind":revision.kind,
        "items":compare_lines({row.line_key:line_view(row) for row in old_records}, {row.line_key:line_view(row) for row in records}),
        "fields":[{"field":key,"before":before[key],"after":after[key]} for key in before if before[key] != after[key]]}
