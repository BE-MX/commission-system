"""Canonical evidence for persisted revisions and their actual immutable lines."""
from app.portal.domain import content_hash
from app.portal.errors import reject


def fixed(value, places=2):
    return None if value is None else format(value, f".{places}f")


def digest(revision, lines):
    header = {key: getattr(revision, key) for key in (
        "public_id", "request_id", "revision_no", "kind", "currency", "fees_status",
        "surcharge_name", "delivery_json", "payment_terms_snapshot", "authority_versions_json",
        "remark", "mapping_version", "pricing_fingerprint", "bound_invoice_document_version", "created_by")}
    header["expires_at"] = revision.expires_at.isoformat()
    if revision.invoice_presentation_json is not None:
        header["invoice_presentation_json"] = revision.invoice_presentation_json
    for key in ("product_amount", "shipping_amount", "packaging_amount", "surcharge_amount", "total_amount"):
        header[key] = fixed(getattr(revision, key))
    details = []
    for line in sorted(lines, key=lambda value: value.line_key):
        row = {key: getattr(line, key) for key in ("line_key", "catalog_item_id", "product_kind",
            "product_id", "sku_id", "standard_json", "customer_display_json", "mapping_version", "qty",
            "price_source", "price_fingerprint")}
        row.update(unit_price=fixed(line.unit_price, 4), discount_amount=fixed(line.discount_amount),
                   line_amount=fixed(line.line_amount), unit_weight_grams=fixed(line.unit_weight_grams, 6))
        details.append(row)
    return content_hash({"revision": header, "lines": details})


def verify(revision, lines):
    if not lines or digest(revision, lines) != revision.content_hash:
        reject("ORDER_UNAVAILABLE", "This order request needs review.", 409)
