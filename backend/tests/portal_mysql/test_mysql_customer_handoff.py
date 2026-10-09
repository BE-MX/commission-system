"""Customer suspension races and reviewed handoff preserve financial history."""
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4
import pytest
from sqlalchemy import Column, MetaData, Table, select
from sqlalchemy.orm import Session
from app.auth.models import ArkUser, ArkUserRole
from app.core.time import beijing_now
from app.customer import workflow_service
from app.customer.models import CustomerAccount, CustomerAction, CustomerOpportunity, CustomerEvent
from app.invoice.models import Invoice, InvoiceItem
from app.portal import (admin_service, auth_service as auth, quote_service, order_service,
    approval_service, proposal_service, proposal_decisions, ownership_service,
    binding_review_service, order_queries, pi_service, revision_evidence)
from app.portal.errors import PortalError
from app.portal.models import (Account, CustomerAccess, PortalSession, OrderRequest, Revision,
    Quote, Publication, AuditEvent, Conversion, OutboxEvent, RequestLine)
from app.portal.schemas import (CustomerUpdate, TransferInput, SubmitInput, AcceptInput,
    ChallengeInput, VerifyInput)
from app.portal.security import open_secret
from test_mysql_services import accepted_request, assert_one_pi, compete, count, submit
from test_mysql_decision_recovery import proposal_body, snapshot


@pytest.mark.parametrize('operation',['submit','approve'])
@pytest.mark.parametrize('suspend_first',[False,True])
def test_customer_pause_and_business_write_obey_commit_order(trade,operation,suspend_first):
    ctx = trade
    request_id,body = accepted_request(ctx) if operation == 'approve' else (None,None)
    def pause(db):
        access = db.get(CustomerAccess,ctx.access_id)
        return admin_service.update_customer(db,ctx.admin,access.public_id,access.row_version,
            CustomerUpdate(status='suspended',capabilities={'can_order':True,'can_view_price':True},reason='Pause this customer'))
    def write(db):
        return submit(ctx,db) if operation == 'submit' else approval_service.approve(db,ctx.actor,request_id,3,body)
    first,second = compete(ctx,pause if suspend_first else write,write if suspend_first else pause)
    if suspend_first:
        assert first['status'] == 'suspended'
        assert second == {'status':401 if operation == 'submit' else 403,
            'error':'AUTH_REQUIRED' if operation == 'submit' else 'ACTION_FORBIDDEN'}
    else:
        assert second['status'] == 'suspended'
        if operation == 'submit': request_id = first['request_id']; assert first['status'] == 'submitted'
        else: assert first['current_state'] == 'invoice_created'; assert_one_pi(ctx,request_id)
    with Session(ctx.engine) as db:
        access = db.get(CustomerAccess,ctx.access_id)
        assert access.status == 'suspended' and db.get(PortalSession,ctx.session_id).revoked_at is not None
        pauses = db.scalars(select(AuditEvent).where(AuditEvent.access_id == ctx.access_id,
            AuditEvent.action == 'access_updated')).all()
        assert len(pauses) == 1 and pauses[0].actor_id == ctx.admin and pauses[0].safe_diff_json['status'] == 'suspended'
        if operation == 'submit':
            assert count(db,OrderRequest,OrderRequest.access_id == ctx.access_id) == int(not suspend_first)
            if not suspend_first:
                order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
                assert order.status == 'submitted' and order.invoice_id is None and order.row_version == 1
                assert count(db,AuditEvent,(AuditEvent.object_public_id == request_id)&(AuditEvent.action == 'order.submitted')) == 1
                assert count(db,OutboxEvent,(OutboxEvent.aggregate_public_id == request_id)&(OutboxEvent.event_type == 'order_submitted')) == 1
        else:
            order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
            assert order.status == ('ready_for_review' if suspend_first else 'invoice_created')
            assert order.row_version == (3 if suspend_first else 4)
            assert count(db,Invoice,Invoice.source_order_id == request_id) == int(not suspend_first)
            assert count(db,Conversion,Conversion.request_id == order.id) == int(not suspend_first)
            assert count(db,AuditEvent,(AuditEvent.object_public_id == request_id)&(AuditEvent.action == 'order.invoice_created')) == int(not suspend_first)
            assert count(db,OutboxEvent,(OutboxEvent.aggregate_public_id == request_id)&(OutboxEvent.event_type == 'order_invoice_created')) == int(not suspend_first)
    baseline = snapshot(ctx)
    with Session(ctx.engine) as db:
        with pytest.raises(PortalError) as caught: order_service.submit(db,ctx.token,ctx.csrf,ctx.key,ctx.body)
        assert caught.value.code == 'AUTH_REQUIRED'; db.rollback()
    assert snapshot(ctx) == baseline


@pytest.mark.parametrize('history_policy',['remove','explicit_grant'])
def test_reviewed_transfer_requires_new_acceptance_and_keeps_old_pi(trade,monkeypatch,history_policy):
    ctx = trade
    metadata = MetaData()
    for model in (CustomerAction,CustomerOpportunity,CustomerEvent):
        Table(model.__tablename__,metadata,*(Column(c.name,c.type,primary_key=c.primary_key,
            nullable=c.nullable,default=c.default,server_default=c.server_default) for c in model.__table__.columns))
    metadata.create_all(ctx.engine,checkfirst=True)
    old_pi_request,old_approval = accepted_request(ctx)
    with Session(ctx.engine) as db:
        approval_service.approve(db,ctx.actor,old_pi_request,3,old_approval); db.commit()
        old_order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == old_pi_request))
        old_invoice_id = old_order.invoice_id
        # A second, not-yet-invoiced request is the explicitly selected handoff.
        quote = quote_service.create(db,ctx.token,ctx.csrf,ctx.quote_body); db.commit()
        pending = SimpleNamespace(**vars(ctx)); pending.key = uuid4()
        pending.body = SubmitInput(quote_id=quote['quote_id'],quote_content_hash=quote['content_hash'],
            customer_po=ctx.quote_body.customer_po,remark='')
    pending_request,old_accepted = accepted_request(pending)
    with Session(ctx.engine) as db:
        access = db.get(CustomerAccess,ctx.access_id); access_public_id = access.public_id
        db.get(CustomerAccount,access.customer_id).profile_input_seq = 0
        replacement = ArkUser(username='new-sales-'+uuid4().hex,password_hash='not-a-login',real_name='New salesperson',is_active=True)
        db.add(replacement); db.flush(); replacement_id = replacement.id
        for role_id in db.scalars(select(ArkUserRole.role_id).where(ArkUserRole.user_id == ctx.actor)).all():
            db.add(ArkUserRole(user_id=replacement_id,role_id=role_id))
        db.commit()
        unused_quote = quote_service.create(db,ctx.token,ctx.csrf,ctx.quote_body); db.commit()
        historical_audits = tuple(db.execute(select(*AuditEvent.__table__.columns).order_by(AuditEvent.id)).all())
        historical_ids = [row.id for row in historical_audits]
        old_pi = tuple(db.execute(select(*Invoice.__table__.columns).where(Invoice.id == old_invoice_id)).one())
        old_items = tuple(db.execute(select(*InvoiceItem.__table__.columns).where(InvoiceItem.invoice_id == old_invoice_id)).all())
        old_publications = tuple(db.execute(select(*Publication.__table__.columns).where(Publication.invoice_id == old_invoice_id)).all())
        old_revision = tuple(db.execute(select(*Revision.__table__.columns).where(Revision.public_id == str(old_accepted.accepted_revision_id))).one())
        old_hash = db.scalar(select(Revision.content_hash).where(Revision.public_id == str(old_accepted.accepted_revision_id)))
        email = db.get(Account,ctx.account_id).email_normalized
        customer_id = access.customer_id
    # Whole-second clock matches the test-owned upstream DATETIME(0) columns.
    with monkeypatch.context() as scoped:
        clock = beijing_now().replace(microsecond=0)
        scoped.setattr(workflow_service,'beijing_now',lambda:clock)
        with Session(ctx.engine) as db:
            assigned = workflow_service.transfer_primary_owner(db,customer_id=customer_id,new_user_id=replacement_id,
                operated_by=ctx.admin,change_reason='Reviewed isolated salesperson handoff')
            new_assignment = assigned.id; db.commit()
    with Session(ctx.engine) as db:
        access = db.get(CustomerAccess,ctx.access_id)
        assert access.status == 'review_required' and access.sales_user_id == ctx.actor
        assert db.get(PortalSession,ctx.session_id).revoked_at is not None
        assert db.scalar(select(Quote.status).where(Quote.public_id == unused_quote['quote_id'])) == 'expired'
        review = binding_review_service.context(db,ctx.admin,access_public_id)
        transferred = ownership_service.transfer_customer(db,ctx.admin,access_public_id,review['row_version'],
            TransferInput(review_fingerprint=review['review_fingerprint'],assignment_id=str(new_assignment),
                pending_request_ids=[pending_request],history_policy=history_policy,
                history_days=30 if history_policy == 'explicit_grant' else None,reason='Confirm selected pending order handoff'))
        db.commit()
        assert transferred['status'] == 'suspended' and transferred['reassigned_request_ids'] == [pending_request]
        assert transferred['history_grants'] == int(history_policy == 'explicit_grant')
        enabled = admin_service.update_customer(db,ctx.admin,access_public_id,transferred['row_version'],
            CustomerUpdate(status='enabled',capabilities={'can_order':True,'can_view_price':True},reason='Reopen reviewed customer'))
        db.commit()
        # Reopening cannot reactivate any old session or quote.
        with pytest.raises(PortalError) as caught: auth.authenticate(db,ctx.token)
        assert caught.value.code == 'AUTH_REQUIRED'; db.rollback()
    auth_time = beijing_now()+timedelta(seconds=61)
    monkeypatch.setattr(auth,'beijing_now',lambda:auth_time)
    with Session(ctx.engine) as db:
        _,preauth,csrf = auth.bootstrap(db,'127.0.0.1'); db.commit()
        challenge = auth.challenge(db,auth.require_preauth(db,preauth,csrf),ChallengeInput(email=email,purpose='login'),'127.0.0.1'); db.commit()
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_public_id == challenge.public_id))
        settings = auth.get_settings()
        code = open_secret(settings.PORTAL_MAIL_KEYS['v1'],event.secret_envelope,event_key=event.event_key,purpose='login',object_id=challenge.public_id)
        principal,session,token = auth.verify(db,auth.require_preauth(db,preauth,csrf),
            VerifyInput(challenge_id=challenge.public_id,code=code),'127.0.0.1'); db.commit()
        assert principal.access.id == ctx.access_id and principal.access.sales_user_id == replacement_id
        pending.token,pending.csrf,pending.actor = token,auth._csrf(session),replacement_id
    baseline = snapshot(ctx)
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == pending_request))
        assert order.status == 'submitted' and order.accepted_revision_id is None
        assert order.servicing_user_id == replacement_id and order.sales_user_id_snapshot == ctx.actor
        with pytest.raises(PortalError) as caught:
            approval_service.approve(db,replacement_id,pending_request,order.row_version,old_accepted)
        assert caught.value.code == 'CUSTOMER_ACCEPTANCE_REQUIRED'; db.rollback()
        with pytest.raises(PortalError) as caught: order_queries.employee_detail(db,ctx.actor,pending_request)
        assert caught.value.code == 'RESOURCE_NOT_FOUND'; db.rollback()
        assert order_queries.employee_detail(db,replacement_id,pending_request)['request_id'] == pending_request; db.rollback()
        if history_policy == 'remove':
            with pytest.raises(PortalError) as caught: order_queries.employee_detail(db,replacement_id,old_pi_request)
            assert caught.value.code == 'RESOURCE_NOT_FOUND'; db.rollback()
        else:
            assert order_queries.employee_detail(db,replacement_id,old_pi_request)['request_id'] == old_pi_request; db.rollback()
        _,_,customer_old_pi = pi_service.capture(db,pending.token,old_pi_request)
        assert customer_old_pi['total_amount'] == '128.00'; db.rollback()
    assert snapshot(ctx) == baseline
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == pending_request))
        proposed = proposal_service.create(db,replacement_id,pending_request,order.row_version,proposal_body(pending)); db.commit()
        receipt = proposed['original_receipt']
        new_revision = db.scalar(select(Revision).where(Revision.public_id == receipt['revision_id']))
        assert new_revision.authority_versions_json['sales_user_id'] == replacement_id
        assert receipt['content_hash'] != old_hash
        lines = db.scalars(select(RequestLine).where(RequestLine.revision_id == new_revision.id)).all()
        assert revision_evidence.digest(new_revision,lines) == receipt['content_hash']
        old_owner_evidence = SimpleNamespace(**{c.name:getattr(new_revision,c.name) for c in Revision.__table__.columns})
        old_owner_evidence.authority_versions_json = {**new_revision.authority_versions_json,'sales_user_id':ctx.actor}
        assert revision_evidence.digest(old_owner_evidence,lines) != receipt['content_hash']
        with pytest.raises(PortalError) as caught:
            approval_service.approve(db,replacement_id,pending_request,proposed['row_version'],
                type(old_accepted)(accepted_revision_id=receipt['revision_id']))
        assert caught.value.code == 'CUSTOMER_ACCEPTANCE_REQUIRED'; db.rollback()
        decided = proposal_decisions.decide(db,pending.token,pending.csrf,pending_request,receipt['revision_id'],
            proposed['row_version'],AcceptInput(proposal_hash=receipt['content_hash']),accept=True); db.commit()
        approval_service.approve(db,replacement_id,pending_request,decided['row_version'],
            type(old_accepted)(accepted_revision_id=receipt['revision_id'])); db.commit()
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == pending_request))
        assert order.status == 'invoice_created' and order.sales_user_id_snapshot == ctx.actor
        invoice = db.get(Invoice,order.invoice_id)
        assert invoice.sales_user_id == replacement_id and invoice.total_amount == 128
        assert count(db,Invoice,Invoice.source_order_id == pending_request) == 1
        assert tuple(db.execute(select(*Invoice.__table__.columns).where(Invoice.id == old_invoice_id)).one()) == old_pi
        assert tuple(db.execute(select(*InvoiceItem.__table__.columns).where(InvoiceItem.invoice_id == old_invoice_id)).all()) == old_items
        assert tuple(db.execute(select(*Publication.__table__.columns).where(Publication.invoice_id == old_invoice_id)).all()) == old_publications
        assert tuple(db.execute(select(*Revision.__table__.columns).where(Revision.public_id == str(old_accepted.accepted_revision_id))).one()) == old_revision
        assert tuple(db.execute(select(*AuditEvent.__table__.columns).where(AuditEvent.id.in_(historical_ids)).order_by(AuditEvent.id)).all()) == historical_audits
        handoff = db.scalar(select(AuditEvent).where(AuditEvent.object_public_id == access_public_id,AuditEvent.action == 'customer_transferred'))
        assert handoff.actor_id == ctx.admin and handoff.safe_diff_json['reassigned_request_ids'] == [pending_request]