"""Versioned durable bindings; full snapshots still fence every in-flight phase."""
from copy import deepcopy

from app.invoice.models import Invoice
from app.shipping_inspection.outbound_sync_plan import digest

CURRENT_VERSION = 2


def version(plan):
    value = plan.get('binding_version', 1)
    if type(value) is not int or value not in (1, CURRENT_VERSION):
        raise ValueError('Unsupported original outbound binding version')
    return value


def fingerprint(business, binding_version=1):
    if type(binding_version) is not int or binding_version not in (1, CURRENT_VERSION):
        raise ValueError('Unsupported original outbound binding version')
    if binding_version == 1:
        return digest(business)
    # The demonstrated non-business touch is Invoice.updated_at. Keep created_at,
    # item IDs/timestamps, quantities, money, status and every dependent record.
    snapshot = list(deepcopy(business))
    invoice = list(snapshot[1])
    invoice[[column.name for column in Invoice.__table__.columns].index('updated_at')] = None
    snapshot[1] = tuple(invoice)
    return digest(tuple(snapshot))
