"""T59 v1.3: durable follow-up proposal/rejection commands survive lost HTTP replies."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.invoice.models import Invoice, InvoiceItem
from app.receipt.models import ReceiptIntent
from app.portal import (auth_service as auth, approval_service, proposal_service, proposal_decisions,
    pi_amendment_service as amendments, pi_revision_source, pricing, catalog_service)
from app.portal.errors import PortalError
from app.portal.models import (OrderRequest, Revision, CommandReceipt, AuditEvent, OutboxEvent,
    PiAmendment, Conversion, Publication)
from app.portal.schemas import PiProposalInput, ReasonInput, VerifyInput
from test_mysql_decision_recovery import make_app, LoseResponse, proposal_body, snapshot
from test_mysql_invitation_race import invite, challenge
from test_mysql_services import submit, accepted_request, compete, count


def prepare_case(ctx, monkeypatch, kind):
    monkeypatch.setattr(pi_revision_source, 'get_settings', auth.get_settings)
    with Session(ctx.engine) as db:
        if kind == 'reject_proposal':
            submitted = submit(ctx, db); db.commit()
            request_id = submitted['request_id']
            proposal = proposal_service.create(db, ctx.actor, request_id, 1, proposal_body(ctx)); db.commit()
            return SimpleNamespace(request_id=request_id, expected=2, action=kind,
                revision_id=proposal['original_receipt']['revision_id'], command={'reason':'Please revise the complete terms'})
    request_id, body = accepted_request(ctx)
    with Session(ctx.engine) as db:
        approval_service.approve(db, ctx.actor, request_id, 3, body); db.commit()
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        invoice = db.get(Invoice, order.invoice_id)
        invoice.remark = 'Complete PI A for follow-up review'; db.commit()
        command = PiProposalInput(invoice_document_version=invoice.portal_document_version,
            valid_for_hours=24, reason='Confirm complete PI A').model_dump(mode='json')
        expected = order.row_version
        revision_id = None
        if kind == 'pi_rejected':
            proposed = amendments.create(db, ctx.actor, request_id, expected, PiProposalInput.model_validate(command)); db.commit()
            expected = proposed['row_version']; revision_id = proposed['original_receipt']['revision_id']
            command = {'reason':'Please revise the complete PI'}
        return SimpleNamespace(request_id=request_id, expected=expected,
            action='pi_proposed' if kind == 'pi-proposals' else kind, revision_id=revision_id, command=command)


def path_for(case):
    if case.action == 'pi_proposed':
        return '/api/portal/admin/v1/orders/'+case.request_id+'/pi-proposals'
    return '/api/portal/v1/orders/'+case.request_id+'/proposals/'+case.revision_id+'/reject'


def invoice_snapshot(ctx):
    with Session(ctx.engine) as db:
        return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
            for model in (Invoice, InvoiceItem, ReceiptIntent, Conversion, Publication))


@pytest.mark.parametrize('kind', ['pi-proposals', 'reject_proposal', 'pi_rejected'])
@pytest.mark.parametrize('change', ['expiry', 'replacement'])
@pytest.mark.parametrize('unavailable', ['price', 'inventory'])
def test_followup_commands_replay_committed_response_without_revalidation(trade, monkeypatch, kind, change, unavailable):
    ctx = trade; case = prepare_case(ctx, monkeypatch, kind)
    app, settings, headers, login_body = make_app(ctx, monkeypatch)
    path = path_for(case); original_match = {'If-Match':'"'+str(case.expected)+'"'}
    async def run():
        transport = LoseResponse(app, path)
        async with httpx.AsyncClient(transport=transport, base_url=settings.PORTAL_ORIGIN, headers=headers) as client:
            login = await client.post('/api/auth/login', json=login_body)
            assert login.status_code == 200
            client.headers['Authorization'] = 'Bearer '+login.json()['access_token']
            with pytest.raises(httpx.ReadError, match='Lost committed'):
                await client.post(path, json=case.command, headers=original_match)
            original = transport.lost
            assert original is not None and original['replayed'] is False
            revision_id = original['original_receipt']['revision_id']
            with Session(ctx.engine) as db:
                order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == case.request_id))
                old = db.scalar(select(Revision).where(Revision.public_id == revision_id))
                assert order.row_version == case.expected+1
                expiry = old.expires_at
                old_fields = tuple(db.execute(select(*Revision.__table__.columns).where(Revision.id == old.id)).one())
                saved = db.scalar(select(CommandReceipt).where(CommandReceipt.object_public_id == case.request_id,
                    CommandReceipt.action == case.action))
                expected_actor = ctx.actor if kind == 'pi-proposals' else ctx.account_id
                assert saved.first_actor_id == expected_actor
                if kind != 'pi-proposals':
                    assert old.customer_accepted_by is None
                document_version = None if kind == 'reject_proposal' else db.get(Invoice, order.invoice_id).portal_document_version
            if change == 'replacement':
                with Session(ctx.engine) as db:
                    order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == case.request_id))
                    if kind == 'reject_proposal':
                        body = proposal_body(ctx); body.fees.shipping_amount = '46.00'
                        replacement = proposal_service.create(db, ctx.actor, case.request_id, order.row_version, body); db.commit()
                    else:
                        invoice = db.get(Invoice, order.invoice_id)
                        if kind == 'pi-proposals':
                            invoice.remark = 'Complete PI B replaces A'; db.commit()
                        # After rejection, the same PI document can legally receive a new proposal command.
                        replacement = amendments.create(db, ctx.actor, case.request_id, order.row_version,
                            PiProposalInput(invoice_document_version=invoice.portal_document_version,
                                reason='Confirm current replacement B')); db.commit()
                    new_revision = replacement['original_receipt']['revision_id']
                    assert new_revision != revision_id
            else:
                module = amendments if kind != 'reject_proposal' else proposal_decisions
                monkeypatch.setattr(module, 'beijing_now', lambda:expiry+timedelta(seconds=1))
            baseline = snapshot(ctx); stable_invoices = invoice_snapshot(ctx); calls = []
            def source_unavailable(*args, **kwargs):
                calls.append(unavailable)
                raise PortalError('PRICE_UNAVAILABLE' if unavailable == 'price' else 'INVENTORY_UNAVAILABLE',
                    'Owned source unavailable', 503)
            target, name = (pricing, 'resolve') if unavailable == 'price' else (catalog_service, 'load_observations')
            with monkeypatch.context() as scoped:
                scoped.setattr(target, name, source_unavailable)
                control = await client.post('/api/portal/v1/quotes', json=ctx.quote_body.model_dump(mode='json'))
                assert control.status_code == 503 and calls
                assert control.json()['data']['error_code'] == ('PRICE_UNAVAILABLE' if unavailable == 'price' else 'INVENTORY_UNAVAILABLE')
                assert snapshot(ctx) == baseline
                calls.clear()
                replay = await client.post(path, json=case.command, headers=original_match)
                assert replay.status_code == 200 and 'no-store' in replay.headers['cache-control']
                result = replay.json()['data']
                assert result['replayed'] and result['original_receipt'] == original['original_receipt']
                assert calls == [] and snapshot(ctx) == baseline
                conflict = await client.post(path, json={**case.command, 'reason':'Different reason for the same command'}, headers=original_match)
                assert conflict.status_code == 409 and conflict.json()['data']['error_code'] == 'IDEMPOTENCY_CONFLICT'
                assert calls == [] and snapshot(ctx) == baseline
            with Session(ctx.engine) as db:
                order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == case.request_id))
                old = db.scalar(select(Revision).where(Revision.public_id == revision_id))
                assert tuple(db.execute(select(*Revision.__table__.columns).where(Revision.id == old.id)).one()) == old_fields
                saved = db.scalars(select(CommandReceipt).where(CommandReceipt.object_public_id == case.request_id,
                    CommandReceipt.action == case.action,
                    CommandReceipt.command_key == ('pi-propose:'+str(case.expected) if kind == 'pi-proposals' else revision_id))).all()
                assert len(saved) == 1 and saved[0].first_actor_id == expected_actor
                assert result['row_version'] == order.row_version and result['current_state'] == order.status
                assert count(db, Invoice, Invoice.source_order_id == case.request_id) == int(kind != 'reject_proposal')
                if change == 'replacement':
                    if kind == 'reject_proposal':
                        assert order.status == 'awaiting_customer' and order.accepted_revision_id is None
                        assert db.get(Revision, order.active_revision_id).public_id == new_revision
                    else:
                        state = db.scalar(select(PiAmendment).where(PiAmendment.request_id == order.id))
                        assert state.status == 'pending_customer' and state.accepted_revision_id is None
                        assert db.get(Revision, state.active_revision_id).public_id == new_revision
                        assert result['amendment_state'] == state.status
                        current_doc = db.get(Invoice, order.invoice_id).portal_document_version
                        assert current_doc == document_version + int(kind == 'pi-proposals')
            assert snapshot(ctx) == baseline and invoice_snapshot(ctx) == stable_invoices
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['reject_proposal', 'pi_rejected'])
@pytest.mark.parametrize('new_member_first', [False, True])
@pytest.mark.parametrize('commit_first', [True, False])
def test_two_members_reject_preserve_committed_first_actor(trade, monkeypatch, kind, new_member_first, commit_first):
    ctx = trade
    with Session(ctx.engine) as db:
        invited = invite(ctx, db); attempt = challenge(db, invited)
        principal, session, other_token = auth.verify(db, auth.require_preauth(db, attempt.token, attempt.csrf),
            VerifyInput(challenge_id=attempt.public_id, code=attempt.code), '127.0.0.1')
        other_csrf = auth._csrf(session)
        assert principal.access.id == ctx.access_id and principal.account.id != ctx.account_id
        db.commit()
    case = prepare_case(ctx, monkeypatch, kind)
    members = [(ctx.token, ctx.csrf, ctx.account_id), (other_token, other_csrf, invited.account_id)]
    if new_member_first: members.reverse()
    original_invoices = invoice_snapshot(ctx)
    with Session(ctx.engine) as db:
        old = db.scalar(select(Revision).where(Revision.public_id == case.revision_id))
        old_fields = tuple(db.execute(select(*Revision.__table__.columns).where(Revision.id == old.id)).one())
    def reject(db, member):
        return proposal_decisions.decide(db, member[0], member[1], case.request_id, case.revision_id,
            case.expected, ReasonInput.model_validate(case.command), accept=False)
    first, second = compete(ctx, lambda db:reject(db, members[0]), lambda db:reject(db, members[1]),
        finalize=lambda db: db.commit() if commit_first else db.rollback())
    assert first['replayed'] is False and second['replayed'] is commit_first
    if commit_first: assert second['original_receipt'] == first['original_receipt']
    winner = members[0 if commit_first else 1][2]
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == case.request_id))
        saved = db.scalars(select(CommandReceipt).where(CommandReceipt.object_public_id == case.request_id,
            CommandReceipt.action == case.action)).all()
        assert len(saved) == 1 and saved[0].first_actor_id == winner and saved[0].first_actor_type == 'customer'
        assert order.row_version == case.expected+1
        old = db.scalar(select(Revision).where(Revision.public_id == case.revision_id))
        assert tuple(db.execute(select(*Revision.__table__.columns).where(Revision.id == old.id)).one()) == old_fields
        event_type = 'order_proposal_rejected' if kind == 'reject_proposal' else 'pi_rejected'
        action = 'order.proposal_rejected' if kind == 'reject_proposal' else 'order.pi_rejected'
        events = db.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_public_id == case.request_id,
            OutboxEvent.event_type == event_type)).all()
        audits = db.scalars(select(AuditEvent).where(AuditEvent.object_public_id == case.request_id,
            AuditEvent.action == action)).all()
        assert len(events) == len(audits) == 1 and audits[0].actor_id == winner
        if kind == 'reject_proposal':
            assert order.status == 'submitted' and order.accepted_revision_id is None
        else:
            amendment = db.scalar(select(PiAmendment).where(PiAmendment.request_id == order.id))
            assert amendment.status == 'withdrawn' and amendment.accepted_revision_id is None
    assert invoice_snapshot(ctx) == original_invoices


def test_expired_pi_reproposal_uses_new_if_match_for_same_document(trade, monkeypatch):
    ctx = trade; case = prepare_case(ctx, monkeypatch, 'pi-proposals')
    app, settings, headers, login_body = make_app(ctx, monkeypatch)
    path = path_for(case); original_match = {'If-Match':'"'+str(case.expected)+'"'}
    async def run():
        transport = LoseResponse(app, path)
        async with httpx.AsyncClient(transport=transport, base_url=settings.PORTAL_ORIGIN, headers=headers) as client:
            login = await client.post('/api/auth/login', json=login_body); assert login.status_code == 200
            client.headers['Authorization'] = 'Bearer '+login.json()['access_token']
            with pytest.raises(httpx.ReadError, match='Lost committed'):
                await client.post(path, json=case.command, headers=original_match)
            first = transport.lost
            with Session(ctx.engine) as db:
                revision = db.scalar(select(Revision).where(Revision.public_id == first['original_receipt']['revision_id']))
                expiry = revision.expires_at
                original_fields = tuple(db.execute(select(*Revision.__table__.columns).where(Revision.id == revision.id)).one())
            new_match = {'If-Match':'"'+str(first['row_version'])+'"'}
            before = snapshot(ctx); invoices_before = invoice_snapshot(ctx)
            blocked = await client.post(path, json=case.command, headers=new_match)
            assert blocked.status_code == 409 and blocked.json()['data']['error_code'] == 'VERSION_CONFLICT'
            assert snapshot(ctx) == before
            current = expiry+timedelta(seconds=1)
            monkeypatch.setattr(amendments, 'beijing_now', lambda:current)
            monkeypatch.setattr(pi_revision_source, 'beijing_now', lambda:current)
            observations = []
            def current_inventory(db, rows):
                from decimal import Decimal
                from app.portal.inventory import InventoryObservation
                observations.append(len(rows))
                return {row.public_id:InventoryObservation(Decimal('1000'), 'g', current, 'synthetic-test-mirror') for row in rows}
            monkeypatch.setattr(catalog_service, 'load_observations', current_inventory)
            second_response = await client.post(path, json=case.command, headers=new_match)
            assert second_response.status_code == 200, second_response.json()
            second = second_response.json()['data']
            assert second['replayed'] is False and observations
            a, b = first['original_receipt'], second['original_receipt']
            assert a['revision_id'] != b['revision_id'] and a['invoice_document_version'] == b['invoice_document_version']
            assert b['expires_at'] == (current+timedelta(hours=24)).isoformat()
            assert invoice_snapshot(ctx) == invoices_before
            baseline = snapshot(ctx); observations.clear()
            for match, receipt in ((original_match, a), (new_match, b)):
                replay = await client.post(path, json=case.command, headers=match)
                assert replay.status_code == 200
                data = replay.json()['data']
                assert data['replayed'] and data['original_receipt'] == receipt
                assert data['row_version'] == second['row_version'] and data['amendment_state'] == 'pending_customer'
                assert observations == [] and snapshot(ctx) == baseline
            with Session(ctx.engine) as db:
                order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == case.request_id))
                amendment = db.scalar(select(PiAmendment).where(PiAmendment.request_id == order.id))
                assert db.get(Revision, amendment.active_revision_id).public_id == b['revision_id']
                assert amendment.accepted_revision_id is None
                revision = db.scalar(select(Revision).where(Revision.public_id == a['revision_id']))
                assert tuple(db.execute(select(*Revision.__table__.columns).where(Revision.id == revision.id)).one()) == original_fields
                commands = db.scalars(select(CommandReceipt).where(CommandReceipt.object_public_id == case.request_id,
                    CommandReceipt.action == 'pi_proposed')).all()
                assert len(commands) == 2 and {row.command_key for row in commands} == {
                    'pi-propose:'+str(case.expected), 'pi-propose:'+str(first['row_version'])}
                assert all(row.first_actor_id == ctx.actor for row in commands)
                assert count(db, Invoice, Invoice.source_order_id == case.request_id) == 1
                assert count(db, OutboxEvent, (OutboxEvent.aggregate_public_id == case.request_id) & (OutboxEvent.event_type == 'pi_proposed')) == 2
                assert count(db, AuditEvent, (AuditEvent.object_public_id == case.request_id) & (AuditEvent.action == 'order.pi_proposed')) == 2
            assert snapshot(ctx) == baseline and invoice_snapshot(ctx) == invoices_before
    asyncio.run(run())
