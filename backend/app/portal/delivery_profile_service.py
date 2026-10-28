"""Customer-shared delivery defaults; never change existing quote/order snapshots."""
from uuid import uuid4

from app.portal import auth_service
from app.portal.models import AuditEvent


def view(db, principal):
    from app.portal.customer_settings_service import delivery_view
    return delivery_view(db, principal.access, principal.account)


def read(db, token):
    principal, _ = auth_service.authenticate(db, token)
    return view(db, principal)


def save(db, token, csrf, expected, body):
    principal, _ = auth_service.authenticate(db, token, csrf=csrf, write=True)
    account = principal.account
    from app.portal.customer_settings_service import save_delivery
    result = save_delivery(db, principal.access, expected, body.delivery)
    db.add(AuditEvent(actor_type='customer', actor_id=account.id, access_id=principal.access.id,
        object_type='account', object_public_id=account.public_id, action='delivery_profile.updated',
        before_version=expected, after_version=result["row_version"], reason='',
        safe_diff_json={}, trace_id=str(uuid4())))
    db.flush()
    return view(db, principal)
