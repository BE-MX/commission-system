"""Canonical fingerprint of customer-visible live PI content, independent of ORM hooks."""
from datetime import date, datetime
from decimal import Decimal

from app.portal.domain import content_hash
from app.portal.invoice_lifecycle import HEADER_FIELDS, LINE_FIELDS, SOURCE_FIELDS


def value(item):
    if isinstance(item, Decimal):
        return format(item.normalize(), "f")
    if isinstance(item, (date, datetime)):
        return item.isoformat()
    return item


def fingerprint(invoice, items=None):
    rows = invoice.items if items is None else items
    return content_hash({"header":{key:value(getattr(invoice, key)) for key in sorted(HEADER_FIELDS | SOURCE_FIELDS)},
        "items":[{key:value(getattr(row, key)) for key in sorted(LINE_FIELDS | {"id"})}
                 for row in sorted(rows, key=lambda row:(row.sort_order, row.id))]})
