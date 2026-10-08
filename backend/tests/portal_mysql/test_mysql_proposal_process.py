"""T56: persisted proposal terms and strict expiry survive fresh service processes."""
from datetime import datetime, timedelta, timezone
import multiprocessing
import os
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core import time as platform_time
from app.portal import auth_service as auth, proposal_service, proposal_decisions
from app.portal.models import OrderRequest, Revision, PortalSession
from app.portal.schemas import AcceptInput
from test_mysql_services import submit, assert_one_pi
from test_mysql_decision_recovery import proposal_body, snapshot
from proposal_process_worker import run


@pytest.mark.parametrize('server_zone',['UTC','America/Los_Angeles'])
@pytest.mark.parametrize('operation',['accept','approve'])
@pytest.mark.parametrize('boundary',['before','at','after'])
def test_restarted_process_keeps_payment_terms_and_expiry(trade,monkeypatch,server_zone,operation,boundary):
    ctx = trade
    issued = platform_time.beijing_now().replace(hour=23,minute=59,second=59,microsecond=0)
    class IssuingClock(datetime):
        @classmethod
        def now(cls,tz=None):
            value = issued.replace(tzinfo=platform_time.BEIJING_TIMEZONE)
            return value.astimezone(tz) if tz is not None else value.astimezone(timezone.utc).replace(tzinfo=None)
    with Session(ctx.engine) as db:
        request = submit(ctx,db); db.commit(); request_id = request['request_id']
        # Keep the synthetic test login valid across the 24h proposal boundary,
        # so expiry rejection cannot be an authentication false positive.
        session = db.get(PortalSession,ctx.session_id)
        session.expires_at = session.idle_expires_at = issued+timedelta(days=3); db.commit()
    with monkeypatch.context() as clock:
        clock.setattr(platform_time,'datetime',IssuingClock)
        with Session(ctx.engine) as db:
            proposed = proposal_service.create(db,ctx.actor,request_id,1,proposal_body(ctx)); db.commit()
            receipt = proposed['original_receipt']
            order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
            revision = db.get(Revision,order.active_revision_id)
            assert revision.created_at == issued and revision.expires_at == issued+timedelta(hours=24)
            expiration = revision.expires_at
            version = proposed['row_version']
            if operation == 'approve':
                decision = proposal_decisions.decide(db,ctx.token,ctx.csrf,request_id,receipt['revision_id'],version,
                    AcceptInput(proposal_hash=receipt['content_hash']),accept=True)
                db.commit(); version = decision['row_version']
            db.refresh(revision)
            evidence = {'expires_at':revision.expires_at.isoformat(),'payment_terms':revision.payment_terms_snapshot,
                'content_hash':revision.content_hash,'accepted_by':revision.customer_accepted_by}
            assert evidence['payment_terms'] == {'code':'prepaid','display_text':'Payment before shipment','deposit_percent':'100.00'}
            original = tuple(db.execute(select(*Revision.__table__.columns).where(Revision.id == revision.id)).one())
            revision_id = revision.id
    moment = expiration+timedelta(seconds={'before':-1,'at':0,'after':1}[boundary])
    absolute = moment.replace(tzinfo=platform_time.BEIJING_TIMEZONE).astimezone(timezone.utc)
    baseline = snapshot(ctx)
    command = {'request_id':request_id,'revision_id':receipt['revision_id'],'hash':receipt['content_hash'],
        'version':version,'operation':operation,'actor':ctx.actor,'token':ctx.token,'csrf':ctx.csrf}
    spawn = multiprocessing.get_context('spawn'); output = spawn.Queue()
    worker = spawn.Process(target=run,args=(ctx.engine.url,vars(auth.get_settings()),absolute,server_zone,command,output))
    try:
        worker.start()
        loaded = output.get(timeout=25)
        assert loaded[0] == 'loaded',loaded
        assert loaded[1] != os.getpid() and loaded[3] == evidence
        assert loaded[4] == moment.isoformat() and loaded[5] != loaded[4]
        if boundary == 'after':
            assert moment.time().isoformat() == '00:00:00'
            assert loaded[5][:10] != loaded[4][:10]
        verdict = output.get(timeout=25)
        worker.join(15); assert worker.exitcode == 0
        if boundary == 'before':
            assert verdict[0] == 'success',verdict
            assert verdict[1]['replayed'] is False
            if operation == 'approve': assert_one_pi(ctx,request_id)
        else:
            assert verdict == ('denied','PROPOSAL_EXPIRED',409)
            assert snapshot(ctx) == baseline
    finally:
        if worker.pid is not None:
            worker.join(3)
            if worker.is_alive(): worker.terminate(); worker.join(5)
        output.close(); output.join_thread()
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        persisted = db.get(Revision,revision_id)
        assert persisted.expires_at == expiration and persisted.payment_terms_snapshot == evidence['payment_terms']
        assert persisted.content_hash == evidence['content_hash']
        if boundary != 'before' or operation == 'approve':
            assert tuple(db.execute(select(*Revision.__table__.columns).where(Revision.id == revision_id)).one()) == original
        elif operation == 'accept':
            assert persisted.customer_accepted_by == ctx.account_id and persisted.customer_accepted_at == moment
            assert order.accepted_revision_id == revision_id and order.row_version == 3
        if boundary != 'before':
            assert order.invoice_id is None and order.status == ('awaiting_customer' if operation == 'accept' else 'ready_for_review')