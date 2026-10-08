"""Durable mapping delivery, scoped recovery and unchanged business state (isolated SQLite)."""
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from test_mapping_service import catalog, managed, portal_metadata, auth_context, body as mapping_body
from app.core.time import beijing_now
from app.portal import mapping_service, mapping_notifications as mapping, mapping_notification_admin as service
from app.portal import notification_admin_service as delivery, notification_worker as worker, mail_worker
from app.portal.errors import PortalError
from app.portal.models import Account, Membership, MappingRevision, OutboxEvent, AuditEvent, CommandReceipt, Site, CustomerAccess
from app.portal.schemas import MappingInput, NotificationRetryInput


@pytest.fixture
def mapping_mail(catalog, monkeypatch):
    ctx, items = catalog
    ctx.settings.PORTAL_NOTIFICATION_ENABLED = ctx.settings.PORTAL_MAIL_ENABLED = True
    monkeypatch.setattr(worker, 'get_settings', lambda: ctx.settings)
    monkeypatch.setattr(worker, 'smtp_sender', lambda *a: pytest.fail('Real SMTP is forbidden'))
    ctx.account.verified_at = beijing_now()
    ctx.db.commit()
    ctx.sessions = []
    factory = sessionmaker(bind=ctx.db.get_bind())
    def tracked():
        session = factory(); ctx.sessions.append(session); return session
    ctx.factory = tracked
    return ctx


def publish(ctx, entries=None):
    ctx.db.expire_all()
    result = mapping_service.publish(ctx.db, 1, ctx.access.public_id, ctx.access.row_version,
        mapping_body(ctx.access.mapping_version) if entries is None else MappingInput(base_version=ctx.access.mapping_version, entries=entries))
    ctx.db.commit()
    return result


def events(ctx, kind=None):
    ctx.db.expire_all()
    query = select(OutboxEvent).where(OutboxEvent.event_type.in_(mapping.EVENTS)).order_by(OutboxEvent.id)
    if kind: query = query.where(OutboxEvent.event_type == kind)
    return ctx.db.scalars(query).all()


def count(ctx, model): return ctx.db.scalar(select(func.count()).select_from(model))


def dead(ctx):
    assert worker.run_once(ctx.factory) == 'expanded'
    child = events(ctx, mapping.MAIL_EVENT)[0]
    child.status, child.attempt_count, child.last_error_code = 'dead', 8, 'MAIL_TRANSPORT_FAILED'
    ctx.db.commit()
    return child.public_id


def retry_body(ctx, identifier):
    row = ctx.db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == identifier))
    return NotificationRetryInput(fingerprint=delivery.fingerprint(row), reason='Mail transport recovered')


def test_publish_event_and_revision_are_atomic(mapping_mail, monkeypatch):
    ctx = mapping_mail
    original = mapping_service.OutboxEvent
    def failure(**kwargs): raise RuntimeError('injected before event insert')
    monkeypatch.setattr(mapping_service, 'OutboxEvent', failure)
    with pytest.raises(RuntimeError): mapping_service.publish(ctx.db, 1, ctx.access.public_id, 1, mapping_body())
    ctx.db.rollback()
    assert count(ctx, MappingRevision) == count(ctx, OutboxEvent) == count(ctx, AuditEvent) == 0
    assert ctx.access.mapping_version == 0 and ctx.access.row_version == 1
    monkeypatch.setattr(mapping_service, 'OutboxEvent', original)
    result = publish(ctx)
    event = events(ctx)[0]
    assert event.event_key == 'mapping-published:' + result['id']
    assert event.aggregate_public_id == ctx.access.public_id
    assert event.payload_json == {'access_public_id': ctx.access.public_id, 'mapping_revision_public_id': result['id'], 'mapping_version': 1}


def test_fanout_delivery_and_repeated_expansion_preserve_business(mapping_mail):
    ctx = mapping_mail; publish(ctx)
    snapshot = deepcopy(ctx.db.scalar(select(MappingRevision)).snapshot_json)
    assert worker.run_once(ctx.factory) == 'expanded'
    source = events(ctx, mapping.SOURCE_EVENT)[0]
    source.status, source.next_attempt_at = 'pending', beijing_now()-timedelta(seconds=1)
    ctx.db.commit()
    assert worker.run_once(ctx.factory) == 'expanded'
    assert len(events(ctx, mapping.MAIL_EVENT)) == 1
    sent = []
    def send(mail):
        assert all(not session.in_transaction() for session in ctx.sessions)
        sent.append(mail); return True
    ctx.db.commit()
    assert worker.run_once(ctx.factory, send) == 'sent'
    assert worker.run_once(ctx.factory, send) == 'idle'
    assert len(sent) == 1 and sent[0].recipient == ctx.account.email_normalized
    assert '/collection' in sent[0].body
    assert all(value not in sent[0].body for value in ['Silk Collection', 'Midnight', 'model:101', 'token=', '27.00'])
    assert ctx.account.email_normalized not in repr(sent[0])
    child = events(ctx, mapping.MAIL_EVENT)[0]
    assert child.secret_envelope is None and 'request_id' not in child.payload_json
    assert ctx.access.mapping_version == 1 and ctx.db.scalar(select(MappingRevision)).snapshot_json == snapshot


@pytest.mark.parametrize('stage', ['before_expand', 'after_expand'])
def test_new_revision_cancels_old_source_or_child(mapping_mail, stage):
    ctx = mapping_mail; publish(ctx)
    if stage == 'after_expand': assert worker.run_once(ctx.factory) == 'expanded'
    publish(ctx, [])
    assert worker.run_once(ctx.factory, lambda _: pytest.fail('Superseded mapping must not send')) == 'cancelled'
    old = events(ctx)[0 if stage == 'before_expand' else 1]
    assert old.last_error_code == 'NOTIFICATION_SUPERSEDED'
    assert ctx.access.mapping_version == 2


@pytest.mark.parametrize('change', ['account', 'member', 'access', 'verified'])
def test_current_authority_cancels_delivery(mapping_mail, change):
    ctx = mapping_mail; publish(ctx)
    assert worker.run_once(ctx.factory) == 'expanded'
    if change == 'account': ctx.account.status = 'disabled'
    elif change == 'member': ctx.member.status = 'disabled'
    elif change == 'access': ctx.access.status = 'suspended'
    else: ctx.account.verified_at = None
    ctx.db.commit()
    assert worker.run_once(ctx.factory, lambda _: pytest.fail('Disabled recipient must not send')) == 'cancelled'
    assert events(ctx, mapping.MAIL_EVENT)[0].last_error_code == 'AUTHORIZATION_CHANGED'
    assert ctx.access.mapping_version == 1 and count(ctx, MappingRevision) == 1


def test_no_price_or_order_capability_still_allows_catalog_notice(mapping_mail):
    ctx = mapping_mail; publish(ctx)
    ctx.access.can_order = ctx.access.can_view_price = False; ctx.db.commit()
    assert worker.run_once(ctx.factory) == 'expanded'
    assert worker.run_once(ctx.factory, lambda _: True) == 'sent'


def test_recovery_scopes_filters_atomicity_and_replay(mapping_mail):
    ctx = mapping_mail; publish(ctx); identifier = dead(ctx)
    for kind in ['auth_code', 'order_submitted', mapping.SOURCE_EVENT]:
        ctx.db.add(OutboxEvent(event_key='polluted-'+kind, event_type=kind, aggregate_public_id=ctx.access.public_id,
            payload_json={'request_id': ctx.access.public_id}, status='dead', last_error_code='NOTIFICATION_SOURCE_INVALID', secret_envelope=b'private-secret', next_attempt_at=beijing_now()))
    ctx.db.commit()
    listing = service.list_events(ctx.db, 1, ctx.access.public_id)
    assert listing['total'] == 2 and listing['access_id'] == ctx.access.public_id
    assert all(value not in str(listing) for value in ['private-secret', 'payload_json', 'lease_token', '@'])
    ctx.db.commit()
    body, key = retry_body(ctx, identifier), uuid4()
    first = service.retry(ctx.db, 1, ctx.access.public_id, identifier, key, body)
    ctx.db.rollback()
    assert events(ctx, mapping.MAIL_EVENT)[0].status == 'dead' and count(ctx, CommandReceipt) == 0
    first = service.retry(ctx.db, 1, ctx.access.public_id, identifier, key, body); ctx.db.commit()
    assert first['original_receipt']['access_id'] == ctx.access.public_id and 'request_id' not in first['original_receipt']
    assert worker.run_once(ctx.factory, lambda _: True) == 'sent'
    replay = service.retry(ctx.db, 1, ctx.access.public_id, identifier, key, body)
    assert replay['replayed'] and replay['current']['status'] == 'sent' and replay['original_receipt'] == first['original_receipt']
    with pytest.raises(PortalError) as error: service.retry(ctx.db, 1, ctx.access.public_id, identifier, key, body.model_copy(update={'reason':'different'}))
    assert error.value.code == 'IDEMPOTENCY_CONFLICT'
    for operation in [lambda: service.list_events(ctx.db, 2, ctx.access.public_id),
                      lambda: service.retry(ctx.db, 2, ctx.access.public_id, identifier, key, body)]:
        with pytest.raises(PortalError) as error: operation()
        assert error.value.status == 404
    assert ctx.access.mapping_version == 1 and count(ctx, MappingRevision) == 1


def test_superseded_dead_notification_cannot_be_requeued(mapping_mail):
    ctx = mapping_mail; publish(ctx); identifier = dead(ctx); body = retry_body(ctx, identifier)
    publish(ctx, [])
    with pytest.raises(PortalError) as error: service.retry(ctx.db, 1, ctx.access.public_id, identifier, uuid4(), body)
    assert error.value.code == 'NOTIFICATION_SUPERSEDED'
    assert events(ctx, mapping.MAIL_EVENT)[0].status == 'dead'


def test_expired_lease_reclaim_and_lost_send_ack_are_not_new_mapping(mapping_mail, monkeypatch):
    ctx = mapping_mail; publish(ctx)
    now = [beijing_now()]
    monkeypatch.setattr(worker, 'beijing_now', lambda: now[0])
    monkeypatch.setattr(mail_worker, 'beijing_now', lambda: now[0])
    monkeypatch.setattr(mapping, 'beijing_now', lambda: now[0])
    assert worker.run_once(ctx.factory) == 'expanded'
    messages = []
    def lost_ack(mail):
        messages.append(mail.message_id)
        now[0] += timedelta(seconds=worker.LEASE_SECONDS+1)
        raise OSError('provider accepted but reply lost')
    assert worker.run_once(ctx.factory, lost_ack) == 'lease_lost'
    assert worker.run_once(ctx.factory, lambda mail: messages.append(mail.message_id) or True) == 'sent'
    assert messages[0] == messages[1]
    assert events(ctx, mapping.MAIL_EVENT)[0].attempt_count == 2
    assert ctx.access.mapping_version == 1 and count(ctx, MappingRevision) == 1


def test_http_mapping_notifications(mapping_mail):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.portal.admin_router import router
    ctx = mapping_mail; publish(ctx); identifier = dead(ctx)
    app=FastAPI(); app.include_router(router,prefix='/api/portal/admin/v1')
    app.dependency_overrides[get_db]=lambda:ctx.db
    app.dependency_overrides[get_current_user]=lambda:{'sub':'1'}
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            base='/api/portal/admin/v1/customers/'+ctx.access.public_id+'/mapping/notifications'
            result=await client.get(base)
            assert result.status_code==200 and result.headers['cache-control']=='private, no-store'
            assert result.json()['data']['total']==2
            url=base+'/'+identifier+'/retry'; body=retry_body(ctx,identifier).model_dump(mode='json')
            assert (await client.post(url,json=body)).status_code==428
            headers={'Idempotency-Key':str(uuid4())}
            assert (await client.post(url,json={**body,'email':'other@example.com'},headers=headers)).status_code==422
            first=await client.post(url,json=body,headers=headers)
            assert first.status_code==200 and first.json()['data']['current']['status']=='pending'
            assert (await client.post(url,json=body,headers=headers)).json()['data']['replayed']
            assert (await client.get(base,params={'page_size':101})).status_code==422
    asyncio.run(check())

def test_cancelled_source_cannot_authorize_child_recovery(mapping_mail):
    ctx = mapping_mail; publish(ctx); identifier = dead(ctx); body = retry_body(ctx, identifier)
    source = events(ctx, mapping.SOURCE_EVENT)[0]
    source.status = 'cancelled'; ctx.db.commit()
    with pytest.raises(PortalError) as error:
        service.retry(ctx.db, 1, ctx.access.public_id, identifier, uuid4(), body)
    assert error.value.code == 'NOTIFICATION_SOURCE_INVALID'
    assert events(ctx, mapping.MAIL_EVENT)[0].status == 'dead'
    assert count(ctx, CommandReceipt) == 0


@pytest.mark.parametrize('field,value', [('membership_id','99999'), ('membership_id','not-a-number'),
    ('membership_id','9223372036854775808'), ('membership_id','1'*5000), ('recipient_kind','staff'), ('event_key','forged-key')])
def test_corrupt_recipient_cannot_be_manually_recovered(mapping_mail, field, value):
    ctx=mapping_mail; publish(ctx); identifier=dead(ctx)
    row=events(ctx,mapping.MAIL_EVENT)[0]
    if field=='event_key': row.event_key=value
    else: row.payload_json={**row.payload_json,field:value}
    ctx.db.commit()
    before_audit=count(ctx,AuditEvent)
    with pytest.raises(PortalError) as error:
        service.retry(ctx.db,1,ctx.access.public_id,identifier,uuid4(),retry_body(ctx,identifier))
    assert error.value.code=='NOTIFICATION_RECIPIENT_INVALID'
    assert row.status=='dead' and row.attempt_count==8
    assert count(ctx,CommandReceipt)==0 and count(ctx,AuditEvent)==before_audit


@pytest.mark.parametrize('other_site',[False,True])
def test_existing_foreign_member_cannot_authorize_recovery(mapping_mail, portal_metadata, other_site):
    ctx=mapping_mail; publish(ctx); identifier=dead(ctx)
    foreign_site=Site(code='other',name='Other',status='enabled',allowed_origin='https://other.example.com') if other_site else ctx.site
    ctx.db.execute(portal_metadata.tables['ark_customer_accounts'].insert(), {'id':2})
    foreign_account=Account(email_normalized='other@example.com',email_display='other@example.com',contact_name='Other buyer',status='active',verified_at=beijing_now())
    ctx.db.add_all([foreign_site,foreign_account]); ctx.db.flush()
    foreign_access=CustomerAccess(site_id=foreign_site.id,customer_id=2,okki_namespace='okki:test',okki_company_id='2',
        external_identity_id=1,binding_fingerprint='a'*64,assignment_id=1,sales_user_id=1,status='enabled',can_order=True,can_view_price=True)
    ctx.db.add(foreign_access);ctx.db.flush()
    foreign_member=Membership(site_id=foreign_site.id,account_id=foreign_account.id,access_id=foreign_access.id,status='active')
    ctx.db.add(foreign_member);ctx.db.flush()
    row=events(ctx,mapping.MAIL_EVENT)[0]
    row.payload_json={**row.payload_json,'membership_id':str(foreign_member.id)}
    # A valid existing member and matching stable key must still fail the site/access binding.
    row.event_key=f"notify:{row.payload_json['source_event_id']}:customer:{foreign_member.id}"
    ctx.db.commit()
    before_audit=count(ctx,AuditEvent)
    with pytest.raises(PortalError) as error:
        service.retry(ctx.db,1,ctx.access.public_id,identifier,uuid4(),retry_body(ctx,identifier))
    assert error.value.code=='NOTIFICATION_RECIPIENT_INVALID'
    assert row.status=='dead' and row.attempt_count==8
    assert count(ctx,CommandReceipt)==0 and count(ctx,AuditEvent)==before_audit
