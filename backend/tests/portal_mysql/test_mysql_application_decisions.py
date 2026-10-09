"""Actual customer negative decisions preserve evidence and do not create PI."""
import json
from pathlib import Path
from uuid import UUID
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.portal import revision_evidence
from app.portal.models import OrderRequest, Revision, RequestLine, CommandReceipt, AuditEvent, OutboxEvent
from test_mysql_application_trade import commerce, business_snapshot  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_customer_application_browser import ROOT, live_application, run_browser


def test_actual_customer_proposal_rejection_and_request_cancellation(commerce,request):
    c=commerce
    runtime=[request.config.getoption('portal_browser_'+name) for name in ('node','module','chromium')]
    if not all(runtime):pytest.skip('Explicit owned Node, Playwright and Chrome paths required')
    node,playwright,chrome=(str(Path(value).resolve(strict=True)) for value in runtime)
    output=Path(request.config.getoption('portal_mysql_workspace')).resolve()/'decisions-evidence';output.mkdir()
    before=business_snapshot(c)
    with live_application(c) as (origin,shell):
        summary=run_browser(c,shell,node,ROOT/'frontend-portal/tests/applicationDecisions.browser.mjs',origin,playwright,chrome,output)
        (output/'runner-summary.json').write_text(json.dumps(summary),encoding='utf-8')
        assert summary['exit_code']==0 and not summary['timed_out'] and summary['child_reaped'] and not summary['cleanup_failure']
        report=json.loads((output/'report.json').read_text())
        assert report['status']=='pass' and report['rejects']==report['cancels']==1 and report['businessResponseInterceptions']==0
        assert str(UUID(report['requestId']))==report['requestId']
        after=business_snapshot(c)
        # Full-column financial/publication graph is unchanged. Identity OTP and
        # request/revision/command/outbox writes are the explicitly allowed flow.
        assert tuple(after[i] for i in (3,4,5,7,8))==tuple(before[i] for i in (3,4,5,7,8))
        with Session(c.app.ctx.engine) as db:
            order=db.scalar(select(OrderRequest).where(OrderRequest.public_id==report['requestId']))
            assert order.status=='cancelled' and order.row_version==4 and order.account_id==c.buyer_id
            assert order.invoice_id is None and order.accepted_revision_id is None and order.customer_po=='PO-DECISION'
            revisions=db.scalars(select(Revision).where(Revision.request_id==order.id).order_by(Revision.revision_no)).all()
            assert len(revisions)==2 and [r.kind for r in revisions]==['submitted','proposal']
            assert revisions[1].public_id==report['revisionId'] and order.active_revision_id==revisions[1].id
            assert revisions[0].product_amount==81 and revisions[0].total_amount is None
            assert revisions[1].product_amount==81 and revisions[1].total_amount==128
            for revision in revisions:
                lines=db.scalars(select(RequestLine).where(RequestLine.revision_id==revision.id)).all()
                revision_evidence.verify(revision,lines)
                assert len(lines)==1 and lines[0].qty==3 and str(lines[0].product_id)==c.product_id
                assert lines[0].standard_json['model']==c.standard['model'] and lines[0].standard_json['color']==c.standard['color']
                assert revision.customer_accepted_at is None and revision.customer_accepted_by is None
            commands=db.scalars(select(CommandReceipt).where(CommandReceipt.object_public_id==order.public_id)).all()
            customer=[row for row in commands if row.first_actor_type=='customer']
            assert sorted(row.action for row in customer)==['cancel','reject_proposal']
            assert all(row.first_actor_id==c.buyer_id for row in customer)
            assert next(row for row in customer if row.action=='cancel').result_reference_json['status']=='cancelled'
            events=db.scalars(select(AuditEvent).where(AuditEvent.object_public_id==order.public_id,AuditEvent.action.in_(['order.cancelled','order.proposal_rejected']))).all()
            assert len(events)==2 and all(row.actor_type=='customer' and row.actor_id==c.buyer_id for row in events)
            assert {row.action:row.reason for row in events}=={'order.cancelled':report['cancelReason'],'order.proposal_rejected':report['rejectReason']}
            notices=db.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_public_id==order.public_id,OutboxEvent.event_type.in_(['order_cancelled','order_proposal_rejected']))).all()
            assert sorted(row.event_type for row in notices)==['order_cancelled','order_proposal_rejected']
            assert {row.event_type:row.payload_json for row in notices}=={
                'order_cancelled':{'request_id':order.public_id},
                'order_proposal_rejected':{'request_id':order.public_id,'revision_id':revisions[1].public_id}}
        assert not shell.pdf_documents and not shell.arm_accept and shell.fault_count==0
        assert c.calls==[] and c.forbidden_writes==[]
