"""Fresh worker processes recover send-ack loss without granting access or duplicating business."""
from datetime import datetime, timedelta
import multiprocessing
import os
from uuid import uuid4

import pytest
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, sessionmaker
from app.core import time as platform_time
from app.auth import admin_router as employee_admin
from app.auth.admin_schemas import UserUpdateRequest
from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission
from app.customer.models import CustomerAccount, CustomerAssignment, CustomerExternalIdentity
from app.invoice.models import Invoice, InvoiceItem
from app.receipt.models import ReceiptIntent
from app.portal import auth_service as auth, admin_service, mapping_service, notification_worker, mail_worker
from app.portal.models import (Account, Membership, CustomerAccess, AuthChallenge, Invitation, PortalSession,
    PreauthSession, RateBucket, MappingRevision, Quote, OrderRequest, Revision, RequestLine, CommandReceipt,
    AuditEvent, Conversion, Publication, PiAmendment, OutboxEvent, Site, AuthorityBarrier)
from app.portal.schemas import ChallengeInput, InvitationInput, MappingInput, AccountUpdate
from test_mysql_services import submit
from notification_process_worker import run

BUSINESS = (ArkRole, ArkPermission, ArkUserRole, ArkRolePermission, CustomerAccount, CustomerAssignment,
    CustomerExternalIdentity, Site, AuthorityBarrier, ArkUser, Account, Membership, CustomerAccess, AuthChallenge, Invitation, PortalSession,
    PreauthSession, RateBucket, MappingRevision, Quote, OrderRequest, Revision, RequestLine, CommandReceipt,
    AuditEvent, Conversion, Publication, PiAmendment, Invoice, InvoiceItem, ReceiptIntent)


def business_snapshot(ctx):
    with Session(ctx.engine) as db:
        return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(*model.__table__.primary_key.columns)).all()) for model in BUSINESS)


def process(ctx, settings, instant, kind, *, crash=False, probe=None):
    spawn = multiprocessing.get_context('spawn'); output = spawn.Queue(); gate = spawn.Event()
    worker = spawn.Process(target=run, args=(ctx.engine.url, vars(settings), instant, kind, crash or probe is not None, gate, output))
    received = []
    try:
        worker.start()
        started = output.get(timeout=25); assert started[0] == 'started', started
        assert started[1] != os.getpid(); received.append(started)
        result = output.get(timeout=25)
        if crash:
            assert result[0] == 'accepted' and result[2] == 2, result
            assert worker.is_alive()
            received.append(result)
            worker.terminate(); worker.join(8)
            assert worker.exitcode is not None and worker.exitcode != 0
        else:
            if result[0] == 'accepted':
                assert result[2] == 2; received.append(result)
                if probe is not None:
                    probe(); gate.set()
                result = output.get(timeout=25)
            assert result[0] == 'finished', result
            received.append(result); worker.join(8); assert worker.exitcode == 0
        return received
    finally:
        if worker.pid is not None:
            worker.join(1)
            if worker.is_alive(): worker.terminate(); worker.join(8)
        output.close(); output.join_thread()


def target(ctx, kind, settings):
    factory = sessionmaker(bind=ctx.engine)
    # Resolve prior test-owned queue rows through actual workers before creating the target.
    # This database is attested and exclusively owned by the opt-in test launcher.
    for worker in (mail_worker, notification_worker):
        # The shared owned suite can have more than 100 prior events. Bound
        # cleanup by the real queue size plus one final idle observation.
        topics = mail_worker.AUTH_EVENTS if worker is mail_worker else notification_worker.DELIVERY_EVENTS
        with factory() as db:
            limit = db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.event_type.in_(topics))) + 1
        for _ in range(limit):
            if worker.run_once(factory, lambda _: pytest.fail('Unrelated queued mail must not send')) == 'idle':
                break
        else: pytest.fail('Prior owned queue did not quiesce')
    with Session(ctx.engine) as db:
        # Match actual claim eligibility: scheduled retries and active leases
        # are not runnable. Never alter them to make a worker claim succeed.
        now = platform_time.beijing_now()
        runnable = db.scalars(select(OutboxEvent).where(
            OutboxEvent.event_type.in_(mail_worker.AUTH_EVENTS | notification_worker.DELIVERY_EVENTS),
            or_(and_(OutboxEvent.status == 'pending', OutboxEvent.next_attempt_at <= now),
                and_(OutboxEvent.status == 'sending', OutboxEvent.lease_until <= now)))).all()
        assert not runnable, 'Prior owned queue still contains claimable events'
    with Session(ctx.engine) as db:
        access = db.get(CustomerAccess, ctx.access_id)
        if kind == 'mapping':
            published = mapping_service.publish(db, ctx.admin, access.public_id, access.row_version,
                MappingInput(base_version=0, entries=[{'kind':'sku', 'source_key':ctx.item_id, 'item_id':ctx.item_id,
                    'display_value':'Customer visible label'}])); db.commit()
            event_id = db.scalar(select(OutboxEvent.public_id).where(OutboxEvent.event_key == 'mapping-published:'+published['id']))
        elif kind == 'order':
            employee = db.get(ArkUser, ctx.actor); employee.email = 'representative@example.test'; db.commit()
            request = submit(ctx, db); db.commit()
            event_id = db.scalar(select(OutboxEvent.public_id).where(OutboxEvent.aggregate_public_id == request['request_id'],
                OutboxEvent.event_type == 'order_submitted'))
        elif kind == 'invitation':
            invited = admin_service.invite(db, ctx.admin, access.public_id, uuid4(),
                InvitationInput(email=uuid4().hex+'@example.test', contact_name='Invited buyer')); db.commit()
            event_id = db.scalar(select(OutboxEvent.public_id).where(OutboxEvent.aggregate_public_id == invited['invitation_id']))
        else:
            _, token, csrf = auth.bootstrap(db, '127.0.0.1'); db.commit()
            challenge = auth.challenge(db, auth.require_preauth(db, token, csrf),
                ChallengeInput(email=db.get(Account,ctx.account_id).email_normalized,purpose='login'), '127.0.0.1'); db.commit()
            event_id = db.scalar(select(OutboxEvent.public_id).where(OutboxEvent.aggregate_public_id == challenge.public_id))
    if kind in {'mapping','order'}:
        assert notification_worker.run_once(factory, lambda _: pytest.fail('Source expands before sending')) == 'expanded'
        with Session(ctx.engine) as db:
            source = db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == event_id))
            assert source.status == 'expanded' and source.event_type == ('mapping_published' if kind == 'mapping' else 'order_submitted')
            children = db.scalars(select(OutboxEvent).where(
                OutboxEvent.payload_json['source_event_id'].as_string() == event_id,
                OutboxEvent.aggregate_public_id == source.aggregate_public_id)).all()
            assert len(children) == 1 and children[0].event_type == ('mapping_mail' if kind == 'mapping' else 'business_mail')
            event_id = children[0].public_id
    return event_id


CASES = [('mapping','supersede'), ('invitation','expire'), ('auth_code','expire')]
CASES += [(kind, change) for kind in ('mapping','order','invitation','auth_code') for change in ('resume','revoke')]


@pytest.fixture
def notification_case(trade):
    ctx = trade
    with Session(ctx.engine) as db:
        previous = set(db.scalars(select(OutboxEvent.id)).all())
    try: yield ctx
    finally:
        # Close only newly-created pending test rows after assertions and joined child processes.
        # In particular, superseding publishes a legitimate new source that belongs to this case.
        with Session(ctx.engine) as db:
            rows = db.scalars(select(OutboxEvent).where(OutboxEvent.id.not_in(previous),
                OutboxEvent.status.in_(['pending','sending']))).all()
            for row in rows: mail_worker.close_event(row,'cancelled','TEST_FIXTURE_CLEANUP')
            db.commit()


@pytest.mark.parametrize('kind,change', CASES)
def test_send_ack_loss_and_fresh_process_recovery(notification_case, monkeypatch, kind, change):
    ctx = notification_case; settings = auth.get_settings()
    settings.PORTAL_MAIL_ENABLED = settings.PORTAL_NOTIFICATION_ENABLED = True
    settings.PORTAL_EMPLOYEE_ORIGIN = 'https://ark.example.test'
    monkeypatch.setattr(mail_worker,'get_settings',lambda:settings)
    monkeypatch.setattr(notification_worker,'get_settings',lambda:settings)
    monkeypatch.setattr(mail_worker,'smtp_sender',lambda _:pytest.fail('Real SMTP forbidden'))
    monkeypatch.setattr(notification_worker,'smtp_sender',lambda _:pytest.fail('Real SMTP forbidden'))
    issued = platform_time.beijing_now().replace(microsecond=0)+timedelta(minutes=2)
    moment = [issued.replace(tzinfo=platform_time.BEIJING_TIMEZONE)]
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            return moment[0].astimezone(tz) if tz is not None else moment[0].replace(tzinfo=None)
    monkeypatch.setattr(platform_time,'datetime',Clock)
    identifier = target(ctx,kind,settings)
    before = business_snapshot(ctx)
    first = process(ctx,settings,moment[0],kind,crash=True)
    with Session(ctx.engine) as db:
        row = db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == identifier))
        assert row.status == 'sending' and row.attempt_count == 1 and row.lease_until == issued+timedelta(seconds=120)
        original_key, old_lease = row.event_key, row.lease_token
        secret = row.secret_envelope
        assert (secret is not None) == (kind in {'invitation','auth_code'})
        if kind == 'invitation':
            invitation = db.scalar(select(Invitation).where(Invitation.public_id == row.aggregate_public_id))
            revoked_account_id = invitation.account_id
        else: revoked_account_id = ctx.account_id
        expires = row.secret_expires_at
    assert business_snapshot(ctx) == before
    if change == 'resume':
        waiting = process(ctx,settings,moment[0]+timedelta(seconds=119),kind)
        assert waiting[-1] == ('finished','idle') and len(waiting) == 2
        assert waiting[0][1] != first[0][1]
        with Session(ctx.engine) as db:
            row = db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == identifier))
            assert row.status == 'sending' and row.attempt_count == 1 and row.lease_token == old_lease
    elif change == 'revoke':
        with Session(ctx.engine) as db:
            if kind == 'order':
                assert employee_admin.update_user(ctx.actor,UserUpdateRequest(is_active=False),db,{'sub':str(ctx.admin)}).code == 200
            else:
                account = db.get(Account,revoked_account_id)
                admin_service.update_account(db,ctx.admin,account.public_id,account.row_version,
                    AccountUpdate(status='disabled',reason='Revoke before restarted notification prepare')); db.commit()
    elif change == 'supersede':
        with Session(ctx.engine) as db:
            access = db.get(CustomerAccess,ctx.access_id)
            mapping_service.publish(db,ctx.admin,access.public_id,access.row_version,
                MappingInput(base_version=access.mapping_version,entries=[])); db.commit()
    baseline = business_snapshot(ctx)
    next_time = expires.replace(tzinfo=platform_time.BEIJING_TIMEZONE) if change == 'expire' else moment[0]+timedelta(seconds=121)
    def protect_new_lease():
        with Session(ctx.engine) as db:
            row = db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == identifier))
            valid = row.status == 'sending' and row.attempt_count == 2 and row.lease_token != old_lease
            assert valid, 'Recovery must hold a distinct active lease before finishing'
            new_lease = row.lease_token
            worker = mail_worker if kind in {'invitation','auth_code'} else notification_worker
            assert worker.finish(db,identifier,old_lease,outcome='sent') == 'lease_lost'
            db.rollback(); db.refresh(row)
            unchanged = row.status == 'sending' and row.lease_token == new_lease and row.attempt_count == 2
            assert unchanged, 'Stale worker must not finish the newer sending lease'
        assert business_snapshot(ctx) == baseline
    second = process(ctx,settings,next_time,kind,probe=protect_new_lease if change == 'resume' else None)
    assert second[0][1] != first[0][1]
    if change == 'resume':
        assert second[-1] == ('finished','sent') and len(second) == 3
        assert second[1][1] == first[1][1] == '<portal-'+identifier+'@leshine.invalid>'
    else:
        assert len(second) == 2 and second[-1] == ('finished','idle' if change == 'expire' else 'cancelled')
    assert business_snapshot(ctx) == baseline
    with Session(ctx.engine) as db:
        row = db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == identifier))
        expected = 'sent' if change == 'resume' else 'expired' if change == 'expire' else 'cancelled'
        assert row.status == expected and row.event_key == original_key
        assert row.attempt_count == (1 if change == 'expire' else 2)
        assert row.secret_envelope is None and row.secret_key_version is None
        assert row.lease_token is None and row.lease_until is None
        if change == 'revoke': assert row.last_error_code == 'AUTHORIZATION_CHANGED'
        elif change == 'supersede': assert row.last_error_code == 'NOTIFICATION_SUPERSEDED'
        elif change == 'expire': assert row.last_error_code == 'SECRET_EXPIRED'
        worker = mail_worker if kind in {'invitation','auth_code'} else notification_worker
        assert worker.finish(db,identifier,old_lease,outcome='sent') == 'lease_lost'; db.rollback()
    assert business_snapshot(ctx) == baseline