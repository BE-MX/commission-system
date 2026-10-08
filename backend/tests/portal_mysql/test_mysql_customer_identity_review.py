"""Real merge/split and external rebind cannot widen company portal access.

Customer tables are thin upstream fixtures; portal tables use actual migrations.
Approved upstream proposals are synthetic evidence, not human approval or UI proof.
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
import pytest
from sqlalchemy import Column, MetaData, Table, inspect, select, func
from sqlalchemy.orm import Session
from app.auth.models import ArkUser, ArkUserRole
from app.core.time import beijing_now
from app.customer import models as customers
from app.customer.ownership_execution_service import build_execution_basis, execute_customer_ownership_change, OwnershipExecutionError
from app.customer.proposal_service import canonical_action_hash
from app.invoice.models import CustomerPriceRule, Invoice
from app.portal import (admin_service, auth_service as auth, binding_review_service,
    quote_service, order_service, approval_service, order_queries, pi_service)
from app.portal.access_policy import binding_fingerprint
from app.portal.errors import PortalError
from app.portal.models import (Account, Membership, CustomerAccess, CatalogItem, CatalogGrant,
    OutboxEvent, Quote, PortalSession, Invitation, OrderRequest, Revision)
from app.portal.schemas import (ChallengeInput, VerifyInput, SubmitInput, CustomerUpdate,
    RebindInput, InvitationInput)
from app.portal.security import open_secret
from test_mysql_services import accepted_request
from test_mysql_decision_recovery import snapshot


def upstream_tables(engine):
    """Only new upstream anchors; no shared schema or historical migration claim."""
    metadata = MetaData()
    present = set(inspect(engine).get_table_names())
    for model in vars(customers).values():
        table = getattr(model, '__table__', None)
        if table is None or table.name in present or table.name in metadata.tables:
            continue
        Table(table.name, metadata, *(Column(c.name, c.type, primary_key=c.primary_key,
            nullable=False if c.primary_key else True) for c in table.columns))
    metadata.create_all(engine)


def login(ctx, db, email):
    _, preauth, csrf = auth.bootstrap(db, '127.0.0.1'); db.commit()
    challenge = auth.challenge(db, auth.require_preauth(db, preauth, csrf),
        ChallengeInput(email=email, purpose='login'), '127.0.0.1'); db.commit()
    assert challenge is not None
    event = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_public_id == challenge.public_id))
    settings = auth.get_settings()
    code = open_secret(settings.PORTAL_MAIL_KEYS['v1'], event.secret_envelope,
        event_key=event.event_key, purpose='login', object_id=challenge.public_id)
    principal, session, token = auth.verify(db, auth.require_preauth(db, preauth, csrf),
        VerifyInput(challenge_id=challenge.public_id, code=code), '127.0.0.1'); db.commit()
    return principal, session, token


def second_company(ctx):
    with Session(ctx.engine) as db:
        a = db.get(CustomerAccess, ctx.access_id)
        company = customers.CustomerAccount(display_name='Separate buyer '+uuid4().hex,
            canonical_company_name='Separate buyer', record_status='active', identity_status='verified', profile_input_seq=0)
        employee = ArkUser(username='other-sales-'+uuid4().hex, password_hash='not-a-login', real_name='Other sales', is_active=True)
        account = Account(email_normalized=uuid4().hex+'@example.test', email_display='other@example.test',
            contact_name='Separate buyer', status='active', verified_at=beijing_now())
        db.add_all([company, employee, account]); db.flush()
        for role_id in db.scalars(select(ArkUserRole.role_id).where(ArkUserRole.user_id == ctx.actor)).all():
            db.add(ArkUserRole(user_id=employee.id, role_id=role_id))
        assignment = customers.CustomerAssignment(customer_id=company.id, user_id=employee.id,
            assignment_role='primary', assignment_status='active', assignment_source='manual',
            effective_from=beijing_now()-timedelta(days=1))
        identity = customers.CustomerExternalIdentity(customer_id=company.id, source_system='okki',
            source_account_key=a.okki_namespace, identifier_type='company_id', raw_value=str(company.id),
            normalized_value=str(company.id), identity_strength='strong', cardinality='one_to_one',
            verification_status='verified', status='active')
        db.add_all([assignment, identity]); db.flush()
        access = CustomerAccess(site_id=a.site_id, customer_id=company.id, assignment_id=assignment.id,
            sales_user_id=employee.id, external_identity_id=identity.id, okki_namespace=a.okki_namespace,
            okki_company_id=identity.normalized_value, status='enabled', can_order=True, can_view_price=True,
            binding_fingerprint=binding_fingerprint(company.id, identity, assignment))
        db.add(access); db.flush()
        db.add(Membership(site_id=a.site_id, account_id=account.id, access_id=access.id, status='active'))
        item = db.scalar(select(CatalogItem).where(CatalogItem.public_id == ctx.item_id))
        db.add(CatalogGrant(access_id=access.id, catalog_item_id=item.id))
        db.add(CustomerPriceRule(customer_id=identity.normalized_value, adjust_type='percent', adjust_value=Decimal('-10'), enabled=1))
        db.commit()
        principal, session, token = login(ctx, db, account.email_normalized)
        quote = quote_service.create(db, token, auth._csrf(session), ctx.quote_body); db.commit()
        return SimpleNamespace(**{**vars(ctx), 'actor':employee.id, 'account_id':account.id,
            'access_id':access.id, 'token':token, 'csrf':auth._csrf(session), 'session_id':session.id,
            'key':uuid4(), 'body':SubmitInput(quote_id=quote['quote_id'], quote_content_hash=quote['content_hash'],
                customer_po=ctx.quote_body.customer_po, remark='')})


def approved_governance(db, ctx, other, action, *, merge_into_existing=False):
    now = beijing_now().replace(microsecond=0)
    source = db.get(customers.CustomerAccount, db.get(CustomerAccess, ctx.access_id).customer_id)
    target = db.get(customers.CustomerAccount, db.get(CustomerAccess, other.access_id).customer_id)
    if action == 'merge' and not merge_into_existing:
        target = customers.CustomerAccount(display_name='Reviewed canonical buyer '+uuid4().hex,
            canonical_company_name='Reviewed canonical buyer', record_status='active', identity_status='verified', profile_input_seq=0)
        db.add(target); db.flush()
    for customer in (source, target):
        customer.profile_input_seq = 0
        profile = customers.CustomerProfileVersion(customer_id=customer.id, version_no=1,
            profile_schema_version='customer_profile_v1', canonicalization_version='jcs_v1', input_seq=0,
            profile_json={}, section_hashes={}, section_data_as_of={}, evidence_fact_ids=[],
            change_summary={'changes':[]}, compiler_version='isolated-test', profile_fingerprint=uuid4().hex*2,
            compiled_at=now, created_at=now)
        db.add(profile); db.flush(); customer.current_profile_version_id = profile.id
    fact = customers.CustomerFact(customer_id=source.id, subject_type='customer', fact_key='identity.company_name',
        fact_layer='confirmed', value_type='string', value_json={'value':source.display_name}, verification_status='verified',
        confidence=1, confidence_method_version='isolated-test', confidence_components_json={},
        data_classification='internal_business', visibility_scope='management', classification_reason='Test governance evidence',
        evidence_json={}, fact_fingerprint=uuid4().hex*2, observed_at=now, created_at=now)
    db.add(fact); db.flush()
    basis = build_execution_basis(db, source_customer_id=source.id, target_customer_ids=[target.id])
    plan = {key:{'source_ids':[], 'rebuilds':[]} for key in
        ('assignments','contact_relationships','customer_relationships','dnc','qualifications','research_tasks')}
    assignment = db.get(customers.CustomerAssignment, db.get(CustomerAccess, ctx.access_id).assignment_id)
    new_id = db.scalar(select(func.max(customers.CustomerAssignment.id)))+1
    if action == 'split':
        for partition in basis['ownership_partitions']:
            if partition['object_type'] == 'external_identity':
                partition['target_customer_id'] = source.id
    plan['assignments'] = {'source_ids':[assignment.id], 'rebuilds':[{'source_id':assignment.id, 'new_id':new_id,
        'target_customer_id':target.id if action == 'merge' else source.id,
        'user_id':ctx.actor, 'assignment_role':'collaborator' if merge_into_existing else 'primary'}]}
    payload = {**basis, 'source_customer_id':source.id, 'target_customer_ids':[target.id],
        'source_profile_version_id':source.current_profile_version_id, 'source_profile_input_seq':0,
        'target_profile_versions':[{'customer_id':target.id, 'profile_version_id':target.current_profile_version_id, 'profile_input_seq':0}],
        'evidence_fact_ids':[fact.id], 'transition_plan':plan, 'proposal_redirects':[],
        'reason_code':'verified_duplicate', 'reason_text':'Isolated governance test'}
    payload['keep_customer_id' if action == 'merge' else 'retain_source'] = target.id if action == 'merge' else True
    digest = canonical_action_hash(action_type=action, customer_id=source.id, target_customer_id=target.id,
        payload_json=payload, profile_version_id=source.current_profile_version_id, evidence_fact_ids=[fact.id])
    proposal = customers.CustomerChangeProposal(customer_id=source.id, target_customer_id=target.id, action_type=action,
        payload_schema_version='customer_'+action+'_v1', payload_json=payload, evidence_fact_ids=[fact.id],
        profile_version_id=source.current_profile_version_id, risk_level='critical', data_classification='restricted_internal',
        visibility_scope='management', action_hash=digest, approved_action_hash=digest, status='approved',
        expires_at=now+timedelta(days=1), decided_at=now, decided_by=ctx.admin, created_at=now, updated_at=now)
    db.add(proposal); db.flush()
    return proposal


def rejected(db, expected, operation):
    with pytest.raises(PortalError) as error:
        operation()
    assert error.value.code == expected
    db.rollback()


@pytest.mark.parametrize('action', ['merge', 'split'])
def test_governance_review_does_not_inherit_other_company_orders(trade, monkeypatch, action):
    ctx = trade
    upstream_tables(ctx.engine)
    other = second_company(ctx)
    request_a, approval_a = accepted_request(ctx)
    with Session(ctx.engine) as db:
        approval_service.approve(db, ctx.actor, request_a, 3, approval_a); db.commit()
    request_b, _ = accepted_request(other)
    with Session(ctx.engine) as db:
        a, b = db.get(CustomerAccess, ctx.access_id), db.get(CustomerAccess, other.access_id)
        a_company, a_identity, a_public = a.customer_id, a.external_identity_id, a.public_id
        b_company, b_identity, b_public = b.customer_id, b.external_identity_id, b.public_id
        a_auth, b_auth = a.auth_version, b.auth_version
        unused = quote_service.create(db, ctx.token, ctx.csrf, ctx.quote_body); db.commit()
        invitation = admin_service.invite(db, ctx.admin, a_public, uuid4(), InvitationInput(
            email=uuid4().hex+'@example.test', contact_name='Invited buyer')); db.commit()
        # A verified duplicate merges into a reviewed canonical account without a
        # portal. Split keeps A's company identity and moves explicit business roots.
        proposal = approved_governance(db, ctx, other, action)
        proposal_id, target_id = proposal.id, proposal.target_customer_id; db.commit()
    baseline = snapshot(ctx)
    with Session(ctx.engine) as db:
        result = execute_customer_ownership_change(db, proposal_id=proposal_id, actor_user_id=ctx.admin, idempotency_key='a'*64)
        db.commit()
        assert set(result.affected_customer_ids) == {a_company,target_id}
        a = db.get(CustomerAccess,ctx.access_id)
        assert a.status == 'review_required' and a.auth_version == a_auth+1
        assert db.get(PortalSession,ctx.session_id).revoked_at is not None
        b = db.get(CustomerAccess,other.access_id)
        assert b.status == ('review_required' if action == 'split' else 'enabled')
        assert b.auth_version == b_auth+int(action == 'split')
        assert (db.get(PortalSession,other.session_id).revoked_at is not None) == (action == 'split')
        assert db.scalar(select(Quote.status).where(Quote.public_id == unused['quote_id'])) == 'expired'
        assert db.scalar(select(Invitation.revoked_at).where(Invitation.public_id == invitation['invitation_id'])) is not None
        overlay = db.get(customers.CustomerObjectOwnership, ('external_identity',a_identity))
        assert overlay.storage_customer_id == a_company
        assert overlay.current_customer_id == (target_id if action == 'merge' else a_company)
        assert a.customer_id == a_company and b.customer_id == b_company
        source = db.get(customers.CustomerAccount,a_company)
        assert source.record_status == ('merged' if action == 'merge' else 'active')
        assert source.merged_into_customer_id == (target_id if action == 'merge' else None)
        if action == 'merge':
            assert db.scalar(select(func.count()).select_from(CustomerAccess).where(CustomerAccess.customer_id == target_id)) == 0
        rejected(db,'AUTH_REQUIRED',lambda:auth.authenticate(db,ctx.token))
        if action == 'split': rejected(db,'AUTH_REQUIRED',lambda:auth.authenticate(db,other.token))
    assert snapshot(ctx) == baseline
    # Resolve only B's own explicit binding after split. A's old orders never move.
    if action == 'split':
        with Session(ctx.engine) as db:
            review = binding_review_service.context(db,ctx.admin,b_public)
            rebound = admin_service.rebind_identity(db,ctx.admin,b_public,review['row_version'],
                RebindInput(review_fingerprint=review['review_fingerprint'],identity_id=str(b_identity),reason='Keep B explicit external identity'))
            db.commit()
            admin_service.update_customer(db,ctx.admin,b_public,rebound['row_version'],
                CustomerUpdate(status='enabled',capabilities={'can_order':True,'can_view_price':True},reason='Reopen reviewed B'))
            db.commit(); email = db.get(Account,other.account_id).email_normalized
        monkeypatch.setattr(auth,'beijing_now',lambda:beijing_now()+timedelta(seconds=61))
        with Session(ctx.engine) as db:
            principal,session,token = login(other,db,email)
            assert principal.access.customer_id == b_company
            other.token,other.csrf = token,auth._csrf(session)
    stable = snapshot(ctx)
    with Session(ctx.engine) as db:
        assert order_queries.customer_detail(db,other.token,request_b)['request_id'] == request_b; db.rollback()
        rejected(db,'RESOURCE_NOT_FOUND',lambda:order_queries.customer_detail(db,other.token,request_a))
        rejected(db,'RESOURCE_NOT_FOUND',lambda:pi_service.capture(db,other.token,request_a))
        rejected(db,'RESOURCE_NOT_FOUND',lambda:quote_service.detail(db,other.token,unused['quote_id']))
        stolen = SubmitInput(quote_id=unused['quote_id'],quote_content_hash=unused['content_hash'],
            customer_po=ctx.quote_body.customer_po,remark='')
        rejected(db,'RESOURCE_NOT_FOUND',lambda:order_service.submit(db,other.token,other.csrf,uuid4(),stolen))
        listing = order_queries.customer_list(db,other.token)
        assert listing['total'] == 1 and [row['request_id'] for row in listing['items']] == [request_b]
        db.rollback()
        rejected(db,'RESOURCE_NOT_FOUND',lambda:order_queries.employee_detail(db,other.actor,request_a))
        rejected(db,'AUTH_REQUIRED',lambda:quote_service.create(db,ctx.token,ctx.csrf,ctx.quote_body))
        review_a = binding_review_service.context(db,ctx.admin,a_public)
        if action == 'merge': assert str(a_identity) not in {row['id'] for row in review_a['identities']}
        rejected(db,'IDENTITY_REVIEW_REQUIRED',lambda:admin_service.update_customer(db,ctx.admin,a_public,review_a['row_version'],
            CustomerUpdate(status='enabled',capabilities={'can_order':True,'can_view_price':True},reason='Try reopening A without review')))
    assert snapshot(ctx) == stable
    final = snapshot(ctx)
    for index in (0,3,4):  # Full Invoice, OrderRequest and Revision rows.
        assert final[index] == baseline[index]


def test_merge_of_different_verified_company_ids_is_rejected_before_mutation(trade):
    ctx = trade
    upstream_tables(ctx.engine)
    other = second_company(ctx)
    with Session(ctx.engine) as db:
        proposal = approved_governance(db,ctx,other,'merge',merge_into_existing=True)
        proposal_id = proposal.id; db.commit()
    baseline = snapshot(ctx)
    with Session(ctx.engine) as db:
        with pytest.raises(OwnershipExecutionError) as error:
            execute_customer_ownership_change(db,proposal_id=proposal_id,actor_user_id=ctx.admin,idempotency_key='a'*64)
        assert error.value.error_code == 'OWNERSHIP_EXECUTION_IDENTITY_CONFLICT'
        for owner in (ctx,other):
            assert db.get(CustomerAccess,owner.access_id).status == 'enabled'
            assert db.get(PortalSession,owner.session_id).revoked_at is None
            assert auth.authenticate(db,owner.token)[0].access.id == owner.access_id
            db.rollback()
    assert snapshot(ctx) == baseline

def test_explicit_external_rebind_keeps_old_orders_and_rejects_foreign_identity(trade,monkeypatch):
    ctx = trade
    other = second_company(ctx)
    request_id, approved = accepted_request(ctx)
    with Session(ctx.engine) as db:
        approval_service.approve(db,ctx.actor,request_id,3,approved); db.commit()
        a = db.get(CustomerAccess,ctx.access_id); a_public,a_company = a.public_id,a.customer_id
        original_company_id = a.okki_company_id
        foreign_id = db.get(CustomerAccess,other.access_id).external_identity_id
        replacement = customers.CustomerExternalIdentity(customer_id=a_company,source_system='okki',source_account_key=a.okki_namespace,
            identifier_type='company_id',raw_value='replacement-'+uuid4().hex,normalized_value='replacement-'+uuid4().hex,
            identity_strength='strong',cardinality='one_to_one',verification_status='verified',status='active')
        db.add(replacement); db.flush(); replacement_id = replacement.id
        db.add(CustomerPriceRule(customer_id=replacement.normalized_value,adjust_type='percent',adjust_value=Decimal('-10'),enabled=1))
        db.commit()
        unused = quote_service.create(db,ctx.token,ctx.csrf,ctx.quote_body); db.commit()
        review = binding_review_service.context(db,ctx.admin,a_public)
        stale_review = review
        quote = quote_service.create(db,ctx.token,ctx.csrf,ctx.quote_body); db.commit()
        pending = SimpleNamespace(**vars(ctx)); pending.key = uuid4()
        pending.body = SubmitInput(quote_id=quote['quote_id'],quote_content_hash=quote['content_hash'],
            customer_po=ctx.quote_body.customer_po,remark='')
    pending_id,pending_approval = accepted_request(pending)
    with Session(ctx.engine) as db:
        review = binding_review_service.context(db,ctx.admin,a_public)
    baseline = snapshot(ctx)
    with Session(ctx.engine) as db:
        rejected(db,'REVIEW_CHANGED',lambda:admin_service.rebind_identity(db,ctx.admin,a_public,stale_review['row_version'],
            RebindInput(review_fingerprint=stale_review['review_fingerprint'],identity_id=str(replacement_id),reason='Attempt stale impact review')))
        rejected(db,'IDENTITY_REVIEW_REQUIRED',lambda:admin_service.rebind_identity(db,ctx.admin,a_public,review['row_version'],
            RebindInput(review_fingerprint=review['review_fingerprint'],identity_id=str(foreign_id),reason='Attempt foreign identity')))
    assert snapshot(ctx) == baseline
    with Session(ctx.engine) as db:
        result = admin_service.rebind_identity(db,ctx.admin,a_public,review['row_version'],
            RebindInput(review_fingerprint=review['review_fingerprint'],identity_id=str(replacement_id),reason='Explicit reviewed rebind'))
        db.commit()
        assert result['status'] == 'suspended' and result['expired_quotes'] == 1
        assert db.get(CustomerAccess,ctx.access_id).customer_id == a_company
        assert db.scalar(select(Quote.status).where(Quote.public_id == unused['quote_id'])) == 'expired'
        rejected(db,'AUTH_REQUIRED',lambda:auth.authenticate(db,ctx.token))
        admin_service.update_customer(db,ctx.admin,a_public,result['row_version'],
            CustomerUpdate(status='enabled',capabilities={'can_order':True,'can_view_price':True},reason='Reopen reviewed identity'))
        db.commit()
        email = db.get(Account,ctx.account_id).email_normalized
    monkeypatch.setattr(auth,'beijing_now',lambda:beijing_now()+timedelta(seconds=61))
    with Session(ctx.engine) as db:
        principal,session,token = login(ctx,db,email)
        current_csrf = auth._csrf(session)
        assert principal.access.customer_id == a_company and principal.access.external_identity_id == replacement_id
        assert principal.access.okki_company_id != original_company_id
        stable = snapshot(ctx)
        assert order_queries.customer_detail(db,token,request_id)['request_id'] == request_id; db.rollback()
        _,_,pi = pi_service.capture(db,token,request_id); assert pi['total_amount'] == '128.00'; db.rollback()
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        assert order.customer_id_snapshot == a_company and order.okki_company_id_snapshot == original_company_id
        rejected(db,'AUTH_REQUIRED',lambda:auth.authenticate(db,ctx.token))
        rejected(db,'RESOURCE_NOT_FOUND',lambda:order_queries.customer_detail(db,other.token,request_id))
        rejected(db,'PROPOSAL_CHANGED',lambda:approval_service.approve(db,ctx.actor,pending_id,3,pending_approval))
        assert db.scalar(select(OrderRequest.invoice_id).where(OrderRequest.public_id == pending_id)) is None
    assert snapshot(ctx) == stable
    final = snapshot(ctx)
    for index in (0,3,4):
        assert final[index] == baseline[index]
    # A new commercial request uses the reviewed external identity, while the old
    # accepted request stays immutable and cannot be silently rebound or invoiced.
    with Session(ctx.engine) as db:
        quote = quote_service.create(db,token,current_csrf,ctx.quote_body); db.commit()
        new_ctx = SimpleNamespace(**vars(ctx)); new_ctx.token,new_ctx.csrf,new_ctx.key = token,current_csrf,uuid4()
        new_ctx.body = SubmitInput(quote_id=quote['quote_id'],quote_content_hash=quote['content_hash'],
            customer_po=ctx.quote_body.customer_po,remark='')
    new_id,new_approval = accepted_request(new_ctx)
    with Session(ctx.engine) as db:
        approval_service.approve(db,ctx.actor,new_id,3,new_approval); db.commit()
        new_order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == new_id))
        replacement = db.get(customers.CustomerExternalIdentity,replacement_id)
        assert new_order.customer_id_snapshot == a_company and new_order.okki_company_id_snapshot == replacement.normalized_value
        invoice = db.get(Invoice,new_order.invoice_id)
        assert invoice.customer_id == replacement.normalized_value and invoice.total_amount == 128
        _,_,new_pi = pi_service.capture(db,token,new_id)
        assert new_pi['total_amount'] == '128.00'; db.rollback()
        assert db.scalar(select(OrderRequest.invoice_id).where(OrderRequest.public_id == pending_id)) is None
    current = snapshot(ctx)
    for index in (0,3,4):
        by_id = {row.id:row for row in current[index]}
        assert all(by_id[row.id] == row for row in baseline[index])