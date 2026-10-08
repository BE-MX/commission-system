"""T56 v1.3: all three evidence types hash the DATETIME representation actually stored."""
from datetime import datetime, timedelta, timezone
import multiprocessing
import os

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core import time as platform_time
from app.invoice.models import Invoice
from app.portal import (auth_service as auth, quote_service, proposal_service, proposal_decisions,
    approval_service, pi_amendment_service as amendments, pi_revision_source, revision_evidence)
from app.portal.models import Quote, Revision, RequestLine, OrderRequest, OutboxEvent, Site
from app.portal.schemas import SubmitInput, AcceptInput, ApproveInput, PiProposalInput, SitePolicy
from test_mysql_decision_recovery import proposal_body
from test_mysql_notification_process import business_snapshot
from proposal_process_worker import run


@pytest.mark.parametrize('server_zone', ['UTC', 'America/Los_Angeles'])
def test_microsecond_creation_three_evidence_types_survive_mysql_and_new_process(trade, monkeypatch, server_zone):
    ctx = trade
    issued = platform_time.beijing_now().replace(microsecond=654321)
    class IssuingClock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = issued.replace(tzinfo=platform_time.BEIJING_TIMEZONE)
            return value.astimezone(tz) if tz is not None else value.astimezone(timezone.utc).replace(tzinfo=None)
    monkeypatch.setattr(platform_time, 'datetime', IssuingClock)
    monkeypatch.setattr(pi_revision_source, 'get_settings', auth.get_settings)
    assert platform_time.beijing_now().microsecond == 654321
    with Session(ctx.engine) as db:
        quoted = quote_service.create(db, ctx.token, ctx.csrf, ctx.quote_body)
        db.commit()
        minutes = SitePolicy.model_validate(db.scalar(select(Site).where(Site.code == auth.get_settings().PORTAL_SITE_CODE)).policy_json).quote_valid_minutes
        body = SubmitInput.model_validate({**ctx.body.model_dump(mode='json'),
            'quote_id':quoted['quote_id'], 'quote_content_hash':quoted['content_hash']})
        from app.portal import order_service
        submitted = order_service.submit(db, ctx.token, ctx.csrf, ctx.key, body); db.commit()
        request_id = submitted['request_id']
        proposed = proposal_service.create(db, ctx.actor, request_id, 1, proposal_body(ctx)); db.commit()
        receipt = proposed['original_receipt']
        accepted = proposal_decisions.decide(db, ctx.token, ctx.csrf, request_id, receipt['revision_id'], 2,
            AcceptInput(proposal_hash=receipt['content_hash']), accept=True); db.commit()
        approval_service.approve(db, ctx.actor, request_id, accepted['row_version'],
            ApproveInput(accepted_revision_id=receipt['revision_id'])); db.commit()
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        invoice = db.get(Invoice, order.invoice_id)
        invoice.remark = 'Precision-stable PI amendment'; db.commit()
        amendment = amendments.create(db, ctx.actor, request_id, order.row_version,
            PiProposalInput(invoice_document_version=invoice.portal_document_version,
                valid_for_hours=24, reason='Confirm complete precision-stable PI')); db.commit()
        amendment_receipt = amendment['original_receipt']
    expected = {
        quoted['quote_id']:{'kind':'quote', 'expires_at':(issued+timedelta(minutes=minutes)).replace(microsecond=0).isoformat(),
            'content_hash':quoted['content_hash'], 'payment_terms':quoted['payment_terms_snapshot']},
        receipt['revision_id']:{'kind':'proposal', 'expires_at':(issued+timedelta(hours=24)).replace(microsecond=0).isoformat(),
            'content_hash':receipt['content_hash'], 'payment_terms':quoted['payment_terms_snapshot']},
        amendment_receipt['revision_id']:{'kind':'pi_amendment', 'expires_at':(issued+timedelta(hours=24)).replace(microsecond=0).isoformat(),
            'content_hash':amendment_receipt['content_hash'], 'payment_terms':quoted['payment_terms_snapshot']}}
    # A fresh Session reads committed MySQL rows, not the writer's identity map.
    with Session(ctx.engine) as db:
        quote = db.scalar(select(Quote).where(Quote.public_id == quoted['quote_id']))
        assert quote.expires_at.microsecond == 0 and quote.result_hash == quoted['content_hash']
        assert quote_service.view(quote)['content_hash'] == quoted['content_hash']
        actual = {quote.public_id:{'kind':'quote', 'expires_at':quote.expires_at.isoformat(),
            'content_hash':quote.result_hash, 'payment_terms':quote.payment_terms_snapshot}}
        for identifier in (receipt['revision_id'], amendment_receipt['revision_id']):
            revision = db.scalar(select(Revision).where(Revision.public_id == identifier))
            lines = db.scalars(select(RequestLine).where(RequestLine.revision_id == revision.id)).all()
            assert revision.expires_at.microsecond == 0
            revision_evidence.verify(revision, lines)
            actual[identifier] = {'kind':revision.kind, 'expires_at':revision.expires_at.isoformat(),
                'content_hash':revision.content_hash, 'payment_terms':revision.payment_terms_snapshot}
        assert actual == expected
    before = business_snapshot(ctx)
    def outbox_snapshot():
        with Session(ctx.engine) as db:
            return db.execute(select(*OutboxEvent.__table__.columns).order_by(OutboxEvent.id)).all()
    events_before = outbox_snapshot()
    # Restart just across Beijing midnight with a non-Beijing default process zone.
    moment = issued.replace(hour=23, minute=59, second=59, microsecond=0)+timedelta(seconds=2)
    absolute = moment.replace(tzinfo=platform_time.BEIJING_TIMEZONE).astimezone(timezone.utc)
    command = {'operation':'read_snapshots', 'quotes':[quoted['quote_id']],
        'revisions':[receipt['revision_id'], amendment_receipt['revision_id']]}
    spawn = multiprocessing.get_context('spawn'); output = spawn.Queue()
    process = spawn.Process(target=run, args=(ctx.engine.url, vars(auth.get_settings()), absolute, server_zone, command, output))
    try:
        process.start()
        loaded = output.get(timeout=25)
        assert loaded[0] == 'snapshots', loaded
        assert loaded[1] != os.getpid() and loaded[3] == expected
        assert loaded[4] == moment.isoformat() and loaded[5][:10] != loaded[4][:10]
        process.join(15); assert process.exitcode == 0
    finally:
        if process.pid is not None:
            process.join(1)
            if process.is_alive(): process.terminate(); process.join(8)
        output.close(); output.join_thread()
    assert business_snapshot(ctx) == before and outbox_snapshot() == events_before
