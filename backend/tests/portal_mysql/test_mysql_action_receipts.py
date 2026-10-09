"""Real customer HTTP receipt lookups; owned MySQL only, no supplier or SMTP."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import queue
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.invoice.models import Invoice
from app.portal import (auth_service as auth, router, proposal_service,
    approval_service, proposal_decisions, pi_amendment_service as amendments,
    pi_revision_source, pricing, catalog_service)
from app.portal.authority import lock_authority
from app.portal.domain import content_hash
from app.portal.models import (Account, CommandReceipt, CustomerAccess, OrderRequest,
    PortalSession, Revision)
from app.portal.schemas import AcceptInput, PiProposalInput, ReasonInput, VerifyInput
from test_mysql_concurrency import wait_for_lock
from test_mysql_decision_recovery import LoseResponse, proposal_body, snapshot
from test_mysql_invitation_race import invite, challenge
from test_mysql_services import accepted_request, disable_account, submit


ACTIONS = ['cancel', 'accept_proposal', 'reject_proposal', 'accept_pi', 'reject_pi']


def prepare(ctx, monkeypatch, action):
    monkeypatch.setattr(pi_revision_source, 'get_settings', auth.get_settings)
    if action.endswith('_pi'):
        request_id, body = accepted_request(ctx)
        with Session(ctx.engine) as db:
            approval_service.approve(db, ctx.actor, request_id, 3, body); db.commit()
            order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
            invoice = db.get(Invoice, order.invoice_id)
            invoice.remark = 'Original receipt recovery PI'; db.commit()
            proposed = amendments.create(db, ctx.actor, request_id, order.row_version,
                PiProposalInput(invoice_document_version=invoice.portal_document_version,
                    reason='Confirm complete revised PI')); db.commit()
            revision = proposed['original_receipt']
            expected = proposed['row_version']
    else:
        with Session(ctx.engine) as db:
            request_id = submit(ctx, db)['request_id']; db.commit()
            expected, revision = 1, None
            if action != 'cancel':
                proposed = proposal_service.create(db, ctx.actor, request_id, expected, proposal_body(ctx)); db.commit()
                revision = proposed['original_receipt']; expected = proposed['row_version']
    body = {'proposal_hash': revision['content_hash']} if action.startswith('accept') else {'reason':'Original receipt recovery reason'}
    locator = {'action':action, 'payload_hash':content_hash(body)}
    if revision:
        locator.update(revision_id=revision['revision_id'], proposal_hash=revision['content_hash'])
    tail = '/cancel' if action == 'cancel' else '/proposals/'+revision['revision_id']+('/accept' if action.startswith('accept') else '/reject')
    return SimpleNamespace(ctx=ctx, action=action, request_id=request_id,
        expected=expected, body=body, locator=locator,
        command_path='/api/portal/v1/orders/'+request_id+tail,
        query_path='/api/portal/v1/orders/'+request_id+'/action-receipt')


@pytest.fixture
def receipt_case(trade, monkeypatch, request):
    case = prepare(trade, monkeypatch, getattr(request, 'param', 'accept_proposal'))
    settings = auth.get_settings(); settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    monkeypatch.setattr(router, 'get_settings', lambda:settings)
    case.app = FastAPI(); case.app.include_router(router.router, prefix='/api/portal/v1')
    case.connections = queue.Queue()
    case.request_connections = set()
    class RequestSession(Session):
        pass
    case.request_session = RequestSession
    @event.listens_for(RequestSession, 'after_begin')
    def connected(db, transaction, connection):
        if not transaction.nested:
            case.request_connections.add(connection)
            case.connections.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    def database():
        with RequestSession(trade.engine, autoflush=False, expire_on_commit=False) as db:
            yield db
    case.app.dependency_overrides[get_db] = database
    case.settings = settings
    case.headers = {'X-Real-IP':'127.0.0.1', 'Origin':settings.PORTAL_ORIGIN,
        'Cookie':router.cookie_name('session')+'='+trade.token, 'X-Portal-CSRF':trade.csrf}
    return case


async def request(case, method='GET', *, params=None, token=None, transport=None):
    headers = dict(case.headers)
    if token is not None: headers['Cookie'] = router.cookie_name('session')+'='+token
    async with httpx.AsyncClient(transport=transport or httpx.ASGITransport(app=case.app,
        client=('127.0.0.1',51000)), base_url=case.settings.PORTAL_ORIGIN, headers=headers) as client:
        if method == 'POST':
            return await client.post(case.command_path, json=case.body,
                headers={'If-Match':'"'+str(case.expected)+'"'})
        return await client.get(case.query_path, params=case.locator if params is None else params)


def assert_no_store(response):
    assert 'no-store' in response.headers['cache-control']
    assert response.headers['pragma'] == 'no-cache'


def lookup(case, expected_status=None, **kwargs):
    """Observe every SQL DML during just this HTTP request; only auth idle may write."""
    before = snapshot(case.ctx); mutations = []
    def observe(connection, cursor, statement, parameters, context, many):
        words = statement.lower().lstrip()
        if words.startswith(('insert ', 'update ', 'delete ')):
            mutations.append(words.split()[0:3])
            assert words.startswith('update '+PortalSession.__tablename__), 'Receipt lookup attempted commercial DML'
    event.listen(case.ctx.engine, 'before_cursor_execute', observe)
    try: response = asyncio.run(request(case, **kwargs))
    finally: event.remove(case.ctx.engine, 'before_cursor_execute', observe)
    if expected_status is not None: assert response.status_code == expected_status, response.text
    assert_no_store(response)
    assert snapshot(case.ctx) == before
    return response


@pytest.mark.parametrize('receipt_case', ACTIONS, indirect=True)
def test_action_receipt_missing_endpoint_red_then_found_false(receipt_case):
    c = receipt_case
    response = lookup(c, expected_status=200)
    assert response.status_code == 200, response.text
    assert response.json()['data'] == {'found':False, 'command':c.locator | {'request_id':c.request_id}}


@pytest.mark.parametrize('receipt_case', ACTIONS, indirect=True)
def test_committed_http_action_lost_response_recovers_only_original_receipt(receipt_case):
    c = receipt_case; transport = LoseResponse(c.app, c.command_path)
    with pytest.raises(httpx.ReadError, match='Lost committed'):
        asyncio.run(request(c, 'POST', transport=transport))
    original = transport.lost
    assert original is not None and original['replayed'] is False
    before = snapshot(c.ctx)
    result = lookup(c)
    assert result.status_code == 200, result.text
    data = result.json()['data']
    assert data['found'] is True and data['command'] == c.locator | {'request_id':c.request_id}
    assert data['receipt']['replayed'] is True
    assert data['receipt']['original_receipt'] == original['original_receipt']
    assert data['receipt']['current_state'] == original['current_state']
    assert data['receipt']['row_version'] == original['row_version']
    if c.action.endswith('_pi'):
        assert 'status' not in data['receipt']['original_receipt']
        assert data['receipt']['amendment_state'] == ('accepted' if c.action.startswith('accept') else 'withdrawn')
    assert snapshot(c.ctx) == before


@pytest.mark.parametrize('receipt_case', ACTIONS, indirect=True)
def test_other_body_hash_does_not_reveal_recorded_reason(receipt_case):
    c = receipt_case
    assert asyncio.run(request(c, 'POST')).status_code == 200
    changed = c.locator | {'payload_hash':content_hash({'reason':'A different private reason'})}
    response = lookup(c, params=changed)
    assert response.status_code == 200 and response.json()['data']['found'] is False
    assert 'receipt' not in response.json()['data'] and 'Original receipt recovery reason' not in response.text


@pytest.mark.parametrize('mutate', [
    lambda value:value.pop('payload_hash'),
    lambda value:value.update(payload_hash='A'*64),
    lambda value:value.update(action='approve'),
    lambda value:value.pop('revision_id'),
    lambda value:value.pop('proposal_hash'),
    lambda value:value.update(revision_id='not-a-uuid'),
    lambda value:value.update(proposal_hash='PRIVATE_BAD_HASH'),
    lambda value:value.update(unexpected='PRIVATE_EXTRA_VALUE'),
])
def test_invalid_query_is_sanitized_422_no_store(receipt_case, mutate):
    c = receipt_case; locator = deepcopy(c.locator); mutate(locator)
    response = lookup(c, params=locator)
    assert response.status_code == 422, response.text
    assert response.json()['data']['error_code'] == 'INVALID_INPUT'
    assert 'PRIVATE_' not in response.text


def test_cancel_forbids_revision_or_proposal_hash(receipt_case):
    c = receipt_case
    for extra in ({'revision_id':str(uuid4())}, {'proposal_hash':'a'*64}):
        response = lookup(c, params={'action':'cancel','payload_hash':content_hash({'reason':'Original reason'})} | extra)
        assert response.status_code == 422


@pytest.mark.parametrize('view_price',[True,False])
def test_current_capabilities_deny_receipt_even_when_it_exists(receipt_case,monkeypatch,view_price):
    from app.portal import admin_service
    from app.portal.schemas import CustomerUpdate
    from test_mysql_otp_race import issue
    c=receipt_case;assert asyncio.run(request(c,'POST')).status_code==200
    with Session(c.ctx.engine) as db:
        access=db.get(CustomerAccess,c.ctx.access_id)
        admin_service.update_customer(db,c.ctx.admin,access.public_id,access.row_version,
            CustomerUpdate(status='enabled',capabilities={'can_order':False,'can_view_price':view_price},
                reason='Make procurement read-only'));db.commit()
    old=lookup(c);assert old.status_code==401 and 'original_receipt' not in old.text
    attempt=issue(c.ctx,monkeypatch)
    with Session(c.ctx.engine) as db:
        principal,session,new_token=auth.verify(db,auth.require_preauth(db,attempt.token,attempt.csrf),
            VerifyInput(challenge_id=attempt.public_id,code=attempt.code),'127.0.0.1');db.commit()
        assert principal.access.can_order is False and principal.access.can_view_price is view_price
    response=lookup(c,token=new_token)
    assert response.status_code==403 and response.json()['data']['error_code']=='ACTION_FORBIDDEN'
    assert 'original_receipt' not in response.text

def test_current_disabled_customer_and_anonymous_cannot_read_original_receipt(receipt_case):
    c = receipt_case; assert asyncio.run(request(c, 'POST')).status_code == 200
    response = lookup(c, token='')
    assert response.status_code == 401
    with Session(c.ctx.engine) as db: disable_account(c.ctx,db); db.commit()
    response = lookup(c)
    assert response.status_code == 401 and 'original_receipt' not in response.text


def test_wrong_order_revision_kind_and_hash_do_not_cross_scope(receipt_case):
    c = receipt_case
    with Session(c.ctx.engine) as db:
        other_key = uuid4()
        from app.portal import quote_service, order_service
        from app.portal.schemas import SubmitInput
        quoted = quote_service.create(db,c.ctx.token,c.ctx.csrf,c.ctx.quote_body); db.commit()
        other = order_service.submit(db,c.ctx.token,c.ctx.csrf,other_key,SubmitInput(
            quote_id=quoted['quote_id'],quote_content_hash=quoted['content_hash'],
            customer_po=c.ctx.quote_body.customer_po,remark='')); db.commit()
        foreign_revision = db.scalar(select(Revision).join(OrderRequest,Revision.request_id==OrderRequest.id)
            .where(OrderRequest.public_id==other['request_id']))
        foreign_revision_id = foreign_revision.public_id
    response = lookup(c, params=c.locator | {'revision_id':foreign_revision_id})
    assert response.status_code == 404
    response = lookup(c, params=c.locator | {'action':'accept_pi'})
    assert response.status_code == 404
    response = lookup(c, params=c.locator | {'proposal_hash':'0'*64})
    assert response.status_code == 200 and response.json()['data']['found'] is False


def test_same_company_different_actor_keeps_existing_scope_semantics(receipt_case):
    c = receipt_case; assert asyncio.run(request(c, 'POST')).status_code == 200
    with Session(c.ctx.engine) as db:
        other_member = invite(c.ctx,db); attempt = challenge(db,other_member)
        principal,session,token = auth.verify(db,auth.require_preauth(db,attempt.token,attempt.csrf),
            VerifyInput(challenge_id=attempt.public_id,code=attempt.code),'127.0.0.1'); db.commit()
        assert principal.account.id != c.ctx.account_id and principal.access.id == c.ctx.access_id
    response = lookup(c, token=token)
    assert response.status_code == 200 and response.json()['data']['found'] is True


def test_current_other_company_cannot_read_receipt(receipt_case):
    from app.core.time import beijing_now
    from app.customer.models import CustomerAccount, CustomerAssignment, CustomerExternalIdentity
    from app.portal.access_policy import binding_fingerprint
    c = receipt_case; assert asyncio.run(request(c, 'POST')).status_code == 200
    foreign = SimpleNamespace(**vars(c.ctx))
    with Session(c.ctx.engine) as db:
        original = db.get(CustomerAccess,c.ctx.access_id)
        company = CustomerAccount(display_name='Different receipt company',canonical_company_name='Different receipt company',
            record_status='active',identity_status='verified')
        db.add(company); db.flush()
        identity = CustomerExternalIdentity(customer_id=company.id,source_system='okki',source_account_key='okki:test',
            identifier_type='company_id',raw_value=str(company.id),normalized_value=str(company.id),identity_strength='strong',
            cardinality='one_to_one',verification_status='verified',status='active')
        assignment = CustomerAssignment(customer_id=company.id,user_id=c.ctx.actor,assignment_role='primary',
            assignment_status='active',assignment_source='manual',effective_from=beijing_now()-timedelta(days=1))
        db.add_all([identity,assignment]); db.flush()
        access = CustomerAccess(site_id=original.site_id,customer_id=company.id,okki_namespace='okki:test',
            okki_company_id=str(company.id),external_identity_id=identity.id,assignment_id=assignment.id,
            sales_user_id=c.ctx.actor,status='enabled',can_order=True,can_view_price=True,
            binding_fingerprint=binding_fingerprint(company.id,identity,assignment))
        db.add(access); db.flush(); foreign.access_id=access.id; db.commit()
        invited=invite(foreign,db); attempt=challenge(db,invited)
        principal,session,token=auth.verify(db,auth.require_preauth(db,attempt.token,attempt.csrf),
            VerifyInput(challenge_id=attempt.public_id,code=attempt.code),'127.0.0.1'); db.commit()
        assert principal.access.id != c.ctx.access_id and principal.account.id != c.ctx.account_id
    response=lookup(c,token=token)
    assert response.status_code==404 and response.json()['data']['error_code']=='RESOURCE_NOT_FOUND'
    assert 'original_receipt' not in response.text

@pytest.mark.parametrize('commit', [True,False])
def test_lookup_waits_for_original_command_commit_or_rollback(receipt_case, commit):
    c = receipt_case
    # Use a real first command and a real second HTTP query; observe the
    # authorization lock wait, not an inferred timeout or a mocked receipt.
    with Session(c.ctx.engine) as first, ThreadPoolExecutor(max_workers=1) as pool:
        original = proposal_decisions.decide(first,c.ctx.token,c.ctx.csrf,c.request_id,
            c.locator['revision_id'],c.expected,AcceptInput.model_validate(c.body),accept=True)
        first.flush()
        future = pool.submit(asyncio.run,request(c))
        try:
            wait_for_lock(c.ctx.engine,c.connections.get(timeout=3)); assert not future.done()
            if commit:first.commit()
            else:first.rollback()
            response = future.result(timeout=8)
        finally:first.rollback()
    assert_no_store(response)
    assert response.status_code == 200 and response.json()['data']['found'] is commit
    if commit: assert response.json()['data']['receipt']['original_receipt'] == original['original_receipt']

@pytest.mark.parametrize('receipt_case', ['accept_proposal','reject_proposal','accept_pi','reject_pi'], indirect=True)
def test_historical_receipt_survives_new_stage_and_disabled_new_writes(receipt_case, monkeypatch):
    from app.portal.schemas import PublishPiInput
    c = receipt_case
    response = asyncio.run(request(c,'POST')); assert response.status_code == 200
    original = response.json()['data']['original_receipt']
    with Session(c.ctx.engine) as db:
        order=db.scalar(select(OrderRequest).where(OrderRequest.public_id==c.request_id))
        if c.action=='accept_proposal':
            from app.portal.schemas import ApproveInput
            approval_service.approve(db,c.ctx.actor,c.request_id,order.row_version,
                ApproveInput(accepted_revision_id=c.locator['revision_id'])); db.commit()
        elif c.action=='reject_proposal':
            next_body=proposal_body(c.ctx); next_body.fees.shipping_amount='46.00'
            proposal_service.create(db,c.ctx.actor,c.request_id,order.row_version,next_body); db.commit()
        elif c.action=='accept_pi':
            invoice=db.get(Invoice,order.invoice_id)
            amendments.publish(db,c.ctx.actor,c.request_id,order.row_version,PublishPiInput(
                accepted_revision_id=c.locator['revision_id'],invoice_document_version=invoice.portal_document_version)); db.commit()
        else:
            invoice=db.get(Invoice,order.invoice_id)
            amendments.create(db,c.ctx.actor,c.request_id,order.row_version,PiProposalInput(
                invoice_document_version=invoice.portal_document_version,reason='New complete PI for later review')); db.commit()
        revision=db.scalar(select(Revision).where(Revision.public_id==c.locator['revision_id']))
        expiry=revision.expires_at
    monkeypatch.setattr(proposal_decisions,'beijing_now',lambda:expiry+timedelta(seconds=1))
    monkeypatch.setattr(amendments,'beijing_now',lambda:expiry+timedelta(seconds=1))
    calls=[]
    def forbidden(*args,**kwargs):calls.append('source');raise AssertionError('Receipt lookup fetched commercial evidence')
    monkeypatch.setattr(pricing,'resolve',forbidden);monkeypatch.setattr(catalog_service,'load_observations',forbidden)
    c.settings.PORTAL_WRITES_ENABLED=False
    response=lookup(c)
    assert response.status_code==200 and response.json()['data']['found'] is True
    receipt=response.json()['data']['receipt']
    assert receipt['original_receipt']==original and receipt['row_version']>original['row_version']
    assert calls==[]
    if c.action=='accept_pi':assert receipt['amendment_state']=='current'
    if c.action=='reject_pi':assert receipt['amendment_state']=='pending_customer'


@pytest.mark.parametrize('receipt_case',['cancel','reject_proposal','reject_pi'],indirect=True)
@pytest.mark.parametrize('vector',['nel','unicode_white_space','bom_is_content'])
def test_reason_hash_matches_actual_pydantic_normalization(receipt_case, vector):
    c=receipt_case
    edges={'nel':'\u0085','unicode_white_space':'\t\n\v\f\r \u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000',
        'bom_is_content':'\ufeff'}
    edge=edges[vector]
    c.body={'reason':edge+'Original receipt recovery reason'+edge}
    canonical=ReasonInput.model_validate(c.body).model_dump(mode='json')
    expected='Original receipt recovery reason' if vector!='bom_is_content' else c.body['reason']
    assert canonical['reason']==expected
    c.locator['payload_hash']=content_hash(canonical)
    response=asyncio.run(request(c,'POST'));assert response.status_code==200
    with Session(c.ctx.engine) as db:
        action={'cancel':'cancel','reject_proposal':'reject_proposal','reject_pi':'pi_rejected'}[c.action]
        saved=db.scalar(select(CommandReceipt).where(CommandReceipt.object_public_id==c.request_id,CommandReceipt.action==action))
        assert saved.payload_hash==c.locator['payload_hash']
    response=lookup(c);assert response.status_code==200 and response.json()['data']['found'] is True


def test_read_query_rejects_unrelated_dirty_caller_before_authorization(receipt_case):
    from app.portal import action_receipt_queries
    from app.portal.errors import PortalError
    c=receipt_case;before=snapshot(c.ctx)
    with Session(c.ctx.engine,autoflush=False) as db:
        row=db.get(Account,c.ctx.account_id);row.contact_name='Uncommitted unrelated customer edit'
        with pytest.raises(PortalError) as error:
            action_receipt_queries.query(db,c.ctx.token,c.request_id,action_receipt_queries.ActionReceiptQuery.model_validate(c.locator))
        assert error.value.status==409
        db.rollback()
    assert snapshot(c.ctx)==before

def drain_connections(case):
    while True:
        try:case.connections.get_nowait()
        except queue.Empty:return


@pytest.mark.parametrize('commit_revocation',[True,False])
def test_revocation_commits_or_rolls_back_before_query_authorization(receipt_case,commit_revocation):
    c=receipt_case;assert asyncio.run(request(c,'POST')).status_code==200
    drain_connections(c)
    with Session(c.ctx.engine) as first,ThreadPoolExecutor(max_workers=1) as pool:
        disable_account(c.ctx,first);first.flush()
        future=pool.submit(asyncio.run,request(c))
        try:
            wait_for_lock(c.ctx.engine,c.connections.get(timeout=3));assert not future.done()
            if commit_revocation:first.commit()
            else:first.rollback()
            response=future.result(timeout=8)
        finally:first.rollback()
    assert_no_store(response)
    assert response.status_code==(401 if commit_revocation else 200)
    if not commit_revocation:assert response.json()['data']['found'] is True
    else:assert 'original_receipt' not in response.text


def test_authorized_query_commits_before_waiting_revocation(receipt_case):
    c=receipt_case;assert asyncio.run(request(c,'POST')).status_code==200
    entered,resume=Event(),Event();revoker_started=queue.Queue();mutations=[]
    def hold_commit(db):
        if db.in_nested_transaction():return
        db.flush();entered.set();assert resume.wait(6)
    def observe(connection,cursor,statement,parameters,context,many):
        words=statement.lower().lstrip()
        if connection in c.request_connections and words.startswith(('insert ','update ','delete ')):
            mutations.append(words.split()[0:3])
            assert words.startswith('update '+PortalSession.__tablename__),'Read query wrote commercial state'
    def revoke():
        with Session(c.ctx.engine) as db:
            revoker_started.put(db.scalar(text('SELECT CONNECTION_ID()')))
            disable_account(c.ctx,db);db.commit()
    event.listen(c.request_session,'before_commit',hold_commit)
    event.listen(c.ctx.engine,'before_cursor_execute',observe)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            lookup_future=pool.submit(asyncio.run,request(c))
            try:
                assert entered.wait(5)
                revoke_future=pool.submit(revoke)
                wait_for_lock(c.ctx.engine,revoker_started.get(timeout=3));assert not revoke_future.done()
                resume.set()
                response=lookup_future.result(timeout=8);revoke_future.result(timeout=8)
            finally:resume.set()
    finally:
        event.remove(c.request_session,'before_commit',hold_commit)
        event.remove(c.ctx.engine,'before_cursor_execute',observe)
    assert_no_store(response)
    assert response.status_code==200 and response.json()['data']['found'] is True
    assert len(mutations)==1  # Only auth idle renewal from the query connection.
    denied=lookup(c);assert denied.status_code==401 and 'original_receipt' not in denied.text