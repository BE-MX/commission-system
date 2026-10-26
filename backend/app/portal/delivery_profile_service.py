"""Account-scoped delivery defaults; never change existing quote/order snapshots."""
from uuid import uuid4

from app.portal import auth_service
from app.portal.domain import require_version
from app.portal.models import AuditEvent


def view(principal):
    return {'delivery': principal.account.delivery_json, 'row_version': principal.account.row_version}


def read(db, token):
    principal, _ = auth_service.authenticate(db, token)
    return view(principal)


def save(db, token, csrf, expected, body):
    principal, _ = auth_service.authenticate(db, token, csrf=csrf, write=True)
    account = principal.account
    require_version(account.row_version, expected)
    account.delivery_json = body.delivery.model_dump()
    account.row_version += 1
    db.add(AuditEvent(actor_type='customer', actor_id=account.id, access_id=principal.access.id,
        object_type='account', object_public_id=account.public_id, action='delivery_profile.updated',
        before_version=expected, after_version=account.row_version, reason='',
        safe_diff_json={}, trace_id=str(uuid4())))
    db.flush()
    return view(principal)
