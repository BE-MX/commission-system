"""Mapping notifications reference immutable revisions, never copied customer labels."""
from sqlalchemy import select

from app.core.time import beijing_now
from app.portal.access_policy import customer_principal, validate_binding
from app.portal.auth_service import enabled_site
from app.portal.domain import content_hash
from app.portal.errors import PortalError, reject
from app.portal.mail_worker import Mail, close_event
from app.portal.models import Account, CustomerAccess, MappingRevision, Membership, OutboxEvent

SOURCE_EVENT = 'mapping_published'
MAIL_EVENT = 'mapping_mail'
EVENTS = {SOURCE_EVENT, MAIL_EVENT}


def scoped_mapping(db, row):
    site = enabled_site(db)
    payload = row.payload_json
    if row.event_type not in EVENTS or not isinstance(payload, dict) or row.secret_envelope is not None:
        reject('NOTIFICATION_SOURCE_INVALID', 'Mapping notification source is invalid.', 404)
    access = db.scalar(select(CustomerAccess).where(CustomerAccess.public_id == row.aggregate_public_id)
        .execution_options(populate_existing=True))
    if access is None or access.site_id != site.id or payload.get('access_public_id') != access.public_id:
        reject('NOTIFICATION_OBJECT_INVALID', 'Mapping notification object is invalid.', 404)
    validate_binding(db, access)
    if access.status != 'enabled':
        reject('AUTHORIZATION_CHANGED', 'Customer access is not enabled.', 403)
    revision = db.scalar(select(MappingRevision).where(
        MappingRevision.public_id == payload.get('mapping_revision_public_id'), MappingRevision.access_id == access.id)
        .execution_options(populate_existing=True))
    if revision is None or revision.status != 'published' or not isinstance(revision.snapshot_json, dict) or (
        revision.snapshot_json.get('snapshot_schema') != 1 or content_hash(revision.snapshot_json) != revision.digest
    ):
        reject('NOTIFICATION_SOURCE_INVALID', 'Mapping revision evidence is invalid.', 404)
    if row.event_type == SOURCE_EVENT and (
        type(payload.get('mapping_version')) is not int or payload['mapping_version'] != revision.version
        or row.event_key != f'mapping-published:{revision.public_id}'
    ):
        reject('NOTIFICATION_SOURCE_INVALID', 'Mapping version reference is invalid.', 404)
    if revision.version != access.mapping_version:
        reject('NOTIFICATION_SUPERSEDED', 'Mapping notification was superseded.', 409)
    return site, access, revision


def source_for(db, row, access, revision):
    source = db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == row.payload_json.get('source_event_id'))
        .execution_options(populate_existing=True))
    if source is None or source.event_type != SOURCE_EVENT or source.status != 'expanded':
        reject('NOTIFICATION_SOURCE_INVALID', 'Mapping source event is unavailable.', 404)
    _, source_access, source_revision = scoped_mapping(db, source)
    if source_access.id != access.id or source_revision.id != revision.id:
        reject('NOTIFICATION_SOURCE_INVALID', 'Mapping source is outside this access.', 404)
    return source


def recipient_for(db, row, site, access, source):
    identifier = row.payload_json.get('membership_id')
    if not isinstance(identifier, str) or not 1 <= len(identifier) <= 19 or not identifier.isascii() or (
        not identifier.isdecimal() or not 0 < int(identifier) <= 9223372036854775807
    ) or row.payload_json.get('recipient_kind') != 'customer':
        reject('NOTIFICATION_RECIPIENT_INVALID', 'Mapping recipient reference is invalid.', 404)
    member = db.get(Membership, int(identifier), populate_existing=True)
    if member is None or member.access_id != access.id or member.site_id != site.id or (
        row.event_key != f'notify:{source.public_id}:customer:{member.id}'
    ):
        reject('NOTIFICATION_RECIPIENT_INVALID', 'Mapping recipient is outside this access.', 404)
    return member


def validate_recovery(db, row):
    site, access, revision = scoped_mapping(db, row)
    if row.event_type == MAIL_EVENT:
        source = source_for(db, row, access, revision)
        recipient_for(db, row, site, access, source)
    return site, access, revision


def expand(db, row):
    site, access, revision = scoped_mapping(db, row)
    members = db.scalars(select(Membership).join(Account, Account.id == Membership.account_id).where(
        Membership.access_id == access.id, Membership.site_id == site.id, Membership.status == 'active',
        Account.status == 'active', Account.verified_at.is_not(None)).order_by(Membership.id)).all()
    for member in members:
        key = f'notify:{row.public_id}:customer:{member.id}'
        if db.scalar(select(OutboxEvent.id).where(OutboxEvent.event_key == key)) is None:
            db.add(OutboxEvent(event_key=key, event_type=MAIL_EVENT, aggregate_public_id=access.public_id,
                payload_json={'access_public_id': access.public_id, 'mapping_revision_public_id': revision.public_id,
                    'source_event_id': row.public_id, 'recipient_kind': 'customer', 'membership_id': str(member.id)},
                next_attempt_at=beijing_now()))
    close_event(row, 'expanded' if members else 'cancelled', None if members else 'NO_ACTIVE_RECIPIENT')
    db.flush()


def prepare(db, row):
    try:
        if row.event_type == SOURCE_EVENT:
            expand(db, row)
            return None
        site, access, revision = scoped_mapping(db, row)
        source = source_for(db, row, access, revision)
        member = recipient_for(db, row, site, access, source)
        principal = customer_principal(db, member.account_id, member.id)
        if principal.account.verified_at is None:
            reject('AUTHORIZATION_CHANGED', 'Verified mailbox required.', 403)
        principal.require('catalog')
        body = ('Your product display names have been updated.\n\n'
                'Sign in to view your current collection:\n' + site.allowed_origin + '/collection\n\n'
                'This notice does not change any existing order or pro forma invoice.')
        return Mail(principal.account.email_normalized, 'LeShine · Collection update', body,
                    f'<portal-{row.public_id}@leshine.invalid>', row.lease_until)
    except PortalError as error:
        if error.status >= 500:
            raise
        code = error.code if error.code.startswith('NOTIFICATION_') else 'AUTHORIZATION_CHANGED'
        close_event(row, 'cancelled' if code in {'AUTHORIZATION_CHANGED', 'NOTIFICATION_SUPERSEDED'} else 'dead', code)
        return None
