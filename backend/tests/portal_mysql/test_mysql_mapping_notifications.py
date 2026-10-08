"""Real MySQL mapping event/worker and recovery, using owned process and no real SMTP."""
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker
from app.core.time import beijing_now
from app.portal import auth_service, mapping_service, mapping_notifications, mapping_notification_admin
from app.portal import notification_worker as worker, notification_admin_service as delivery, mail_worker
from app.portal.errors import PortalError
from app.portal.models import Account, Membership, CustomerAccess, MappingRevision, OutboxEvent, CommandReceipt, AuditEvent
from app.portal.schemas import MappingInput, NotificationRetryInput
from test_mysql_services import compete
from test_mysql_notification_process import business_snapshot


@pytest.fixture
def delivery_context(trade, monkeypatch):
    ctx=trade
    settings=auth_service.get_settings()
    settings.PORTAL_MAIL_ENABLED=settings.PORTAL_NOTIFICATION_ENABLED=True
    monkeypatch.setattr(worker,'get_settings',lambda:settings)
    monkeypatch.setattr(worker,'smtp_sender',lambda *a:pytest.fail('Real SMTP forbidden'))
    now=beijing_now().replace(microsecond=0)
    for module in (worker,mail_worker,mapping_notifications,mapping_service,delivery):
        monkeypatch.setattr(module,'beijing_now',lambda:now)
    ctx.factory=sessionmaker(bind=ctx.engine)
    with Session(ctx.engine) as db:
        access=db.get(CustomerAccess,ctx.access_id)
        ctx.access_public_id=access.public_id
        result=mapping_service.publish(db,ctx.admin,access.public_id,access.row_version,
            MappingInput(base_version=access.mapping_version,entries=[{'kind':'sku','source_key':ctx.item_id,'item_id':ctx.item_id,'display_value':'Silk Customer Label'}]))
        db.commit()
        ctx.revision_id=result['id']
        ctx.source_id=db.scalar(select(OutboxEvent.public_id).where(OutboxEvent.event_key=='mapping-published:'+result['id']))
        # The immutable business baseline must survive delivery and controlled retry.
        ctx.baseline=(access.mapping_version,access.row_version,deepcopy(db.scalar(select(MappingRevision).where(MappingRevision.public_id==ctx.revision_id)).snapshot_json))
    return ctx


def assert_unchanged(ctx):
    with Session(ctx.engine) as db:
        access=db.get(CustomerAccess,ctx.access_id)
        revision=db.scalar(select(MappingRevision).where(MappingRevision.public_id==ctx.revision_id))
        assert (access.mapping_version,access.row_version,revision.snapshot_json)==ctx.baseline


@pytest.mark.parametrize('commit_first',[True,False])
def test_competing_workers_claim_one_mapping_event(delivery_context,commit_first):
    ctx=delivery_context
    first,second=compete(ctx,worker.claim,worker.claim,finalize=lambda db:db.commit() if commit_first else db.rollback())
    if commit_first:
        assert first[0]==ctx.source_id and second is None
        lease=first
    else:
        assert second[0]==ctx.source_id and second[1]!=first[1]
        lease=second
        with Session(ctx.engine) as db:
            assert worker.finish(db,*first,outcome='sent')=='lease_lost'
            db.rollback()
    with Session(ctx.engine) as db:
        assert worker.prepare(db,*lease) is None
        db.commit()
        source=db.scalar(select(OutboxEvent).where(OutboxEvent.public_id==ctx.source_id))
        children=db.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_public_id==ctx.access_public_id,OutboxEvent.event_type=='mapping_mail')).all()
        assert source.status=='expanded' and source.attempt_count==1 and len(children)==1
    delivered=[]
    assert worker.run_once(ctx.factory,lambda mail:delivered.append(mail) or True)=='sent'
    assert worker.run_once(ctx.factory,lambda _:pytest.fail('No duplicate message'))=='idle'
    assert len(delivered)==1 and 'Silk Customer Label' not in delivered[0].body
    assert_unchanged(ctx)


def test_mysql_json_scope_and_idempotent_recovery(delivery_context):
    ctx=delivery_context
    assert worker.run_once(ctx.factory)=='expanded'
    with Session(ctx.engine) as db:
        child=db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_public_id==ctx.access_public_id,OutboxEvent.event_type=='mapping_mail'))
        child.status,child.attempt_count,child.last_error_code='dead',8,'MAIL_TRANSPORT_FAILED'
        identifier=child.public_id
        db.commit()
        body=NotificationRetryInput(fingerprint=delivery.fingerprint(child),reason='Test transport recovered')
        key=uuid4()
        listing=mapping_notification_admin.list_events(db,ctx.admin,ctx.access_public_id)
        assert listing['total']==2 and {row['event_type'] for row in listing['items']}==mapping_notifications.EVENTS
        assert all('payload_json' not in row and 'lease_token' not in row for row in listing['items'])
        first=mapping_notification_admin.retry(db,ctx.admin,ctx.access_public_id,identifier,key,body)
        db.rollback()
        assert db.get(OutboxEvent,child.id).status=='dead'
        assert db.scalar(select(CommandReceipt).where(CommandReceipt.object_public_id==identifier)) is None
        db.rollback()
        first=mapping_notification_admin.retry(db,ctx.admin,ctx.access_public_id,identifier,key,body)
        db.commit()
    assert worker.run_once(ctx.factory,lambda _:True)=='sent'
    with Session(ctx.engine) as db:
        replay=mapping_notification_admin.retry(db,ctx.admin,ctx.access_public_id,identifier,key,body)
        assert replay['replayed'] and replay['original_receipt']==first['original_receipt'] and replay['current']['status']=='sent'
        with pytest.raises(PortalError) as error:
            mapping_notification_admin.retry(db,ctx.admin,ctx.access_public_id,identifier,key,body.model_copy(update={'reason':'different'}))
        assert error.value.code=='IDEMPOTENCY_CONFLICT'
        db.rollback()
        audits=db.scalars(select(AuditEvent).where(AuditEvent.access_id==ctx.access_id,AuditEvent.action=='notification.retry_requested')).all()
        receipts=db.scalars(select(CommandReceipt).where(CommandReceipt.object_public_id==identifier)).all()
        assert len(audits)==len(receipts)==1
    assert_unchanged(ctx)

@pytest.mark.parametrize('commit_first', [True, False])
def test_two_member_expansion_is_atomic_and_competing_prepare_is_unique(delivery_context, commit_first):
    ctx = delivery_context
    with Session(ctx.engine) as db:
        access = db.get(CustomerAccess, ctx.access_id)
        original = db.scalar(select(Membership).where(Membership.access_id == access.id,
            Membership.account_id == ctx.account_id))
        other = Account(email_normalized=uuid4().hex+'@example.test', email_display='second@example.test',
            contact_name='Second buyer', status='active', verified_at=beijing_now())
        db.add(other); db.flush()
        added = Membership(site_id=access.site_id, account_id=other.id, access_id=access.id, status='active')
        db.add(added); db.flush()
        member_ids = {str(original.id), str(added.id)}
        recipients = {db.get(Account, ctx.account_id).email_normalized, other.email_normalized}
        db.commit()
        lease = worker.claim(db); db.commit()
        assert lease is not None and lease[0] == ctx.source_id
    baseline = business_snapshot(ctx)

    def outbox_snapshot():
        with Session(ctx.engine) as db:
            return db.execute(select(*OutboxEvent.__table__.columns).order_by(OutboxEvent.id)).all()

    before = outbox_snapshot()
    children_query = select(OutboxEvent).where(
        OutboxEvent.payload_json['source_event_id'].as_string() == ctx.source_id)
    inserted = []
    def fail_second_child(mapper, connection, target):
        if target.event_type == 'mapping_mail' and target.payload_json.get('source_event_id') == ctx.source_id:
            inserted.append(target.payload_json['membership_id'])
            if len(inserted) == 2:
                # The previous child's INSERT has really executed in this transaction.
                assert connection.scalar(select(func.count()).select_from(OutboxEvent).where(
                    OutboxEvent.payload_json['source_event_id'].as_string() == ctx.source_id)) == 1
                raise RuntimeError('Injected failure after first mapping child insert')

    event.listen(OutboxEvent, 'before_insert', fail_second_child)
    try:
        with Session(ctx.engine) as db:
            with pytest.raises(RuntimeError, match='after first mapping child insert'):
                worker.prepare(db, *lease)
            db.rollback()
    finally:
        event.remove(OutboxEvent, 'before_insert', fail_second_child)
    assert set(inserted) == member_ids and len(inserted) == 2
    assert outbox_snapshot() == before
    assert business_snapshot(ctx) == baseline
    with Session(ctx.engine) as db:
        source = db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == ctx.source_id))
        assert source.status == 'sending' and source.lease_token == lease[1] and source.attempt_count == 1
        assert not db.scalars(children_query).all()

    # Independent MySQL connections contend on actual prepare, not merely on claim.
    # compete observes the second connection's InnoDB wait before the first finishes.
    action = lambda db: worker.prepare(db, *lease)
    first, second = compete(ctx, action, action,
        finalize=lambda db: db.commit() if commit_first else db.rollback())
    assert first is None and second is None
    with Session(ctx.engine) as db:
        source = db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == ctx.source_id))
        children = db.scalars(children_query).all()
        assert source.status == 'expanded' and source.attempt_count == 1
        assert source.lease_token is None and source.lease_until is None
        assert len(children) == 2
        assert {child.payload_json['membership_id'] for child in children} == member_ids
        assert {child.event_key for child in children} == {
            f'notify:{ctx.source_id}:customer:{identifier}' for identifier in member_ids}
        for child in children:
            assert child.event_type == 'mapping_mail' and child.aggregate_public_id == ctx.access_public_id
            assert child.status == 'pending' and child.attempt_count == 0
            assert child.payload_json == {'access_public_id':ctx.access_public_id,
                'mapping_revision_public_id':ctx.revision_id, 'source_event_id':ctx.source_id,
                'recipient_kind':'customer', 'membership_id':child.payload_json['membership_id']}
            assert child.secret_envelope is None
        child_ids = {child.public_id for child in children}
        # Exactly these two rows were created; no duplicate source or unrelated work.
        all_rows = db.execute(select(*OutboxEvent.__table__.columns).order_by(OutboxEvent.id)).all()
        assert len(all_rows) == len(before) + 2
        source_index = list(OutboxEvent.__table__.columns.keys()).index('public_id')
        assert [row for row in all_rows if row[source_index] not in child_ids | {ctx.source_id}] == [
            row for row in before if row[source_index] != ctx.source_id]
    assert business_snapshot(ctx) == baseline
    delivered = []
    for _ in range(2):
        assert worker.run_once(ctx.factory, lambda mail: delivered.append(mail) or True) == 'sent'
    assert worker.run_once(ctx.factory, lambda _: pytest.fail('No third notification')) == 'idle'
    assert len(delivered) == 2 and {mail.recipient for mail in delivered} == recipients
    assert {mail.message_id for mail in delivered} == {
        f'<portal-{identifier}@leshine.invalid>' for identifier in child_ids}
    assert all('Silk Customer Label' not in mail.body for mail in delivered)
    assert business_snapshot(ctx) == baseline
    assert_unchanged(ctx)
