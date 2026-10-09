from datetime import timedelta
import smtplib

import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import sessionmaker
from test_proposals import proposing, submitted, submission, quoting, priced_catalog, catalog, managed, portal_metadata, auth_context
from app.auth.models import ArkUser
from app.customer.models import CustomerAssignment, CustomerExternalIdentity
from app.core.time import beijing_now
from app.portal import notification_worker as worker, admin_service
from app.portal.errors import PortalError
from app.portal.models import Account, Membership, OrderRequest, OutboxEvent


@pytest.fixture
def notifications(proposing, monkeypatch):
    ctx, order = proposing
    ctx.settings.PORTAL_NOTIFICATION_ENABLED = ctx.settings.PORTAL_MAIL_ENABLED = True
    ctx.settings.PORTAL_EMPLOYEE_ORIGIN = 'https://ark.example.com'
    ctx.settings.APP_ENV = 'production'
    monkeypatch.setattr(worker, 'get_settings', lambda: ctx.settings)
    monkeypatch.setattr(worker, 'smtp_sender', lambda *args: pytest.fail('Real SMTP is forbidden'))
    ctx.db.get(ArkUser, 1).email = 'old-sales@example.com'
    ctx.account.verified_at = beijing_now()
    ctx.db.commit()
    factory = sessionmaker(bind=ctx.db.get_bind())
    ctx.worker_sessions = []
    def tracked_factory():
        db = factory(); ctx.worker_sessions.append(db); return db
    ctx.factory = tracked_factory
    ctx.order_id = order['request_id']
    return ctx


def source(ctx, event='order_submitted'):
    row = ctx.db.scalar(select(OutboxEvent).where(OutboxEvent.event_type.in_(worker.BUSINESS_EVENTS)))
    row.event_type, row.event_key = event, event + ':' + ctx.order_id
    identifier = row.public_id
    ctx.db.commit()
    return identifier


def rows(ctx, event=worker.MAIL_EVENT):
    ctx.db.expire_all()
    return ctx.db.scalars(select(OutboxEvent).where(OutboxEvent.event_type == event).order_by(OutboxEvent.id)).all()


def test_staff_fanout_and_send_have_stable_identity_and_no_private_business_content(notifications):
    ctx = notifications; source_id = source(ctx)
    assert worker.run_once(ctx.factory) == 'expanded'
    sent = []
    def send(mail):
        assert not ctx.db.in_transaction()
        assert ctx.worker_sessions and all(not db.in_transaction() for db in ctx.worker_sessions)
        sent.append(mail); return True
    assert worker.run_once(ctx.factory, send) == 'sent'
    assert worker.run_once(ctx.factory, send) == 'idle'
    assert len(sent) == 1 and sent[0].recipient == 'old-sales@example.com'
    assert '/portal/orders?request=' + ctx.order_id in sent[0].body
    assert all(value not in sent[0].body for value in ['Example Street', '81.00', '27.0000', 'token='])
    assert 'old-sales@example.com' not in repr(sent[0])
    child = rows(ctx)[0]
    assert child.status == 'sent' and child.secret_envelope is None
    assert child.payload_json['source_event_id'] == source_id
    assert 'email' not in str(child.payload_json)


def test_fanout_retry_does_not_duplicate_children(notifications):
    ctx = notifications; source_id = source(ctx)
    assert worker.run_once(ctx.factory) == 'expanded'
    row = ctx.db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == source_id))
    row.status, row.next_attempt_at = 'pending', beijing_now() - timedelta(minutes=1)
    ctx.db.commit()
    assert worker.run_once(ctx.factory) == 'expanded'
    assert len(rows(ctx)) == 1


def test_current_owner_is_resolved_after_fanout(notifications):
    ctx = notifications; source(ctx)
    assert worker.run_once(ctx.factory) == 'expanded'
    new_owner = ctx.db.get(ArkUser, 2)
    new_owner.is_active, new_owner.email = True, 'new-sales@example.com'
    assignment = ctx.db.get(CustomerAssignment, ctx.access.assignment_id)
    assignment.user_id = 2; ctx.access.sales_user_id = 2
    ctx.access.binding_fingerprint = admin_service.binding_fingerprint(ctx.access.customer_id, ctx.db.get(CustomerExternalIdentity, ctx.access.external_identity_id), assignment)
    ctx.db.scalar(select(OrderRequest)).servicing_user_id = 2
    ctx.db.commit()
    sent = []
    assert worker.run_once(ctx.factory, lambda mail: sent.append(mail.recipient) or True) == 'sent'
    assert sent == ['new-sales@example.com']


@pytest.mark.parametrize('change', ['account', 'membership', 'verification', 'access'])
def test_customer_authorization_rechecked_before_sending(notifications, change):
    ctx = notifications; source(ctx, 'order_proposed')
    assert worker.run_once(ctx.factory) == 'expanded'
    if change == 'account': ctx.account.status = 'disabled'
    elif change == 'membership': ctx.member.status = 'disabled'
    elif change == 'verification': ctx.account.verified_at = None
    else: ctx.access.status = 'suspended'
    ctx.db.commit()
    assert worker.run_once(ctx.factory) == 'cancelled'
    assert rows(ctx)[0].status == 'cancelled'
    assert ctx.db.scalar(select(OrderRequest)).status == 'submitted'


def test_current_employee_permission_rechecked(notifications, monkeypatch):
    ctx = notifications; source(ctx)
    assert worker.run_once(ctx.factory) == 'expanded'
    def denied(*args): raise PortalError('ACTION_FORBIDDEN', 'denied', 403)
    monkeypatch.setattr(admin_service, 'employee_principal', denied)
    assert worker.run_once(ctx.factory) == 'cancelled'


def test_individual_customer_delivery_preserves_successes_on_partial_failure(notifications):
    ctx = notifications; source(ctx, 'order_invoice_created')
    account = Account(email_normalized='second@example.com', email_display='second@example.com', contact_name='Second', status='active', verified_at=beijing_now())
    ctx.db.add(account); ctx.db.flush()
    ctx.db.add(Membership(account_id=account.id, access_id=ctx.access.id, site_id=ctx.site.id, status='active')); ctx.db.commit()
    assert worker.run_once(ctx.factory) == 'expanded'
    sent = []
    assert worker.run_once(ctx.factory, lambda mail: sent.append(mail) or True) == 'sent'
    def fail(mail): raise smtplib.SMTPException('sensitive-recipient password')
    assert worker.run_once(ctx.factory, fail) == 'pending'
    children = rows(ctx)
    assert [row.status for row in children] == ['sent', 'pending']
    children[1].next_attempt_at = beijing_now() - timedelta(seconds=1); ctx.db.commit()
    assert worker.run_once(ctx.factory, lambda mail: sent.append(mail) or True) == 'sent'
    assert [mail.recipient for mail in sent] == ['buyer@example.com', 'second@example.com']
    assert '/orders/' + ctx.order_id in sent[0].body
    assert 'token=' not in sent[0].body


def test_transport_failure_backoff_dead_and_safe_logs(notifications, capsys, caplog):
    ctx = notifications; source(ctx)
    worker.run_once(ctx.factory)
    def fail(mail): raise smtplib.SMTPException('secret@example.com password=secret')
    assert worker.run_once(ctx.factory, fail) == 'pending'
    row = rows(ctx)[0]
    assert row.last_error_code == 'MAIL_TRANSPORT_FAILED' and row.next_attempt_at > beijing_now() + timedelta(seconds=50)
    row.attempt_count, row.next_attempt_at = 7, beijing_now() - timedelta(seconds=1)
    ctx.db.commit()
    assert worker.run_once(ctx.factory, fail) == 'dead'
    assert rows(ctx)[0].lease_token is None
    assert 'password=secret' not in capsys.readouterr().out + caplog.text


def test_expired_lease_reclaim_rejects_stale_completion(notifications):
    ctx = notifications; source(ctx)
    first = worker.claim(ctx.db); ctx.db.commit()
    row = ctx.db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == first[0]))
    row.lease_until = beijing_now() - timedelta(seconds=1); ctx.db.commit()
    second = worker.claim(ctx.db); ctx.db.commit()
    assert first[0] == second[0] and first[1] != second[1]
    assert worker.finish(ctx.db, *first, outcome='sent') == 'lease_lost'
    assert worker.prepare(ctx.db, *second) is None
    ctx.db.commit()
    assert len(rows(ctx)) == 1


def test_disabled_switch_does_not_open_database(notifications):
    ctx = notifications; ctx.settings.PORTAL_NOTIFICATION_ENABLED = False
    def forbidden(): pytest.fail('disabled worker opened database')
    assert worker.run_once(forbidden) == 'disabled'


def test_notification_configuration_requires_mail_and_trusted_employee_origin():
    from test_contracts import config
    from app.portal.configuration import validate_configuration
    for patch in [{'PORTAL_MAIL_ENABLED': False}, {'PORTAL_EMPLOYEE_ORIGIN': 'https://ark.example/path'}, {'PORTAL_EMPLOYEE_ORIGIN': 'http://ark.example'}, {'PORTAL_ENABLED': False}]:
        values = {'PORTAL_NOTIFICATION_ENABLED': True, 'PORTAL_MAIL_ENABLED': True, 'PORTAL_EMPLOYEE_ORIGIN': 'https://ark.example', **patch}
        with pytest.raises(ValueError): validate_configuration(config(**values))
    validate_configuration(config(PORTAL_NOTIFICATION_ENABLED=True, PORTAL_MAIL_ENABLED=True, PORTAL_EMPLOYEE_ORIGIN='https://ark.example'))
    assert set(worker.LABELS) == worker.BUSINESS_EVENTS


@pytest.mark.parametrize('event', ['order_submitted', 'order_proposed'])
def test_changed_binding_cancels_queued_notification(notifications, event):
    ctx = notifications; source(ctx, event)
    assert worker.run_once(ctx.factory) == 'expanded'
    identity = ctx.db.get(CustomerExternalIdentity, ctx.access.external_identity_id)
    identity.normalized_value = 'different-company'
    ctx.db.commit()
    def forbidden(mail): pytest.fail('Changed company binding must not receive mail')
    assert worker.run_once(ctx.factory, forbidden) == 'cancelled'
    assert rows(ctx)[0].last_error_code == 'AUTHORIZATION_CHANGED'
    assert ctx.db.scalar(select(OrderRequest)).status == 'submitted'


def test_expired_before_smtp_is_retried_without_recording_delivery(notifications):
    ctx = notifications; source(ctx)
    assert worker.run_once(ctx.factory) == 'expanded'
    assert worker.run_once(ctx.factory, lambda mail: False) == 'pending'
    child = rows(ctx)[0]
    assert child.last_error_code == 'LEASE_EXPIRED_BEFORE_SEND'
    assert child.lease_token is None and child.lease_until is None
    child.next_attempt_at = beijing_now() - timedelta(seconds=1)
    ctx.db.commit()
    sent = []
    assert worker.run_once(ctx.factory, lambda mail: sent.append(mail) or True) == 'sent'
    assert len(sent) == 1


def test_actual_lease_expiry_during_send_is_reclaimed(notifications, monkeypatch):
    from app.portal import mail_worker
    ctx = notifications; source(ctx)
    clock = [beijing_now()]
    monkeypatch.setattr(worker, 'beijing_now', lambda: clock[0])
    monkeypatch.setattr(mail_worker, 'beijing_now', lambda: clock[0])
    assert worker.run_once(ctx.factory) == 'expanded'
    def elapsed(mail):
        clock[0] += timedelta(seconds=worker.LEASE_SECONDS + 1)
        assert mail.valid_until < clock[0]
        return False
    assert worker.run_once(ctx.factory, elapsed) == 'lease_lost'
    child = rows(ctx)[0]
    assert child.status == 'sending' and child.attempt_count == 1
    ctx.db.commit()
    delivered = []
    assert worker.run_once(ctx.factory, lambda mail: delivered.append(mail) or True) == 'sent'
    child = rows(ctx)[0]
    assert child.status == 'sent' and child.attempt_count == 2
    assert len(delivered) == 1 and child.lease_token is None
