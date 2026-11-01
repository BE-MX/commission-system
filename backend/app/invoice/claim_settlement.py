"""Close a target's original sending claims once its outcome is settled.

Presale freight orders and shipment outbounds record their POSTs as
sending claims (request keys ``legacy:freight:{target}:...`` and
``legacy:shipment:{outbound}:...``). An unknown outcome leaves the claim open
and blocks every legacy send of the whole order, so each settling path must
close it: a verified remote result closes it as succeeded; an attested
absence closes it as not_sent. Callers already hold portal -> policy ->
authority (lock_recovery_scope) before the invoice lock, and own the commit.
"""
from sqlalchemy import select

from app.commerce_transition import service as ownership
from app.commerce_transition.models import SendingClaim
from app.invoice import legacy_sending

FREIGHT = ('freight_order_create', 'legacy:freight:{}:')
SHIPMENT = ('shipment_outbound_create', 'legacy:shipment:{}:')


def open_claims(db, invoice_id, kind, target_id):
    operation, prefix = kind
    key = prefix.format(target_id)
    rows = db.scalars(select(SendingClaim).where(
        SendingClaim.invoice_id == invoice_id, SendingClaim.operation == operation,
        SendingClaim.state.in_(sorted(ownership.MANUALLY_RELEASABLE))).order_by(SendingClaim.id)
        .with_for_update().execution_options(populate_existing=True)).all()
    return [row for row in rows if row.request_key.startswith(key)]


def settle_verified(db, invoice_id, kind, target_id, remote_id, evidence):
    """A verified original remote document closes every unfinished POST of the target."""
    for claim in open_claims(db, invoice_id, kind, target_id):
        legacy_sending.finish(db, claim.request_key, 'succeeded',
                              {'original_request_readback': True, **evidence}, str(remote_id))


def release_unsent(db, invoice_id, kind, target_id, *, operator_id, reason, source, remote_evidence):
    """An authorized administrator attested the original POST created nothing."""
    for claim in open_claims(db, invoice_id, kind, target_id):
        ownership.confirm_not_sent(db, claim.id, operator_id=operator_id, reason=reason,
                                   source=source, remote_evidence=remote_evidence)
