"""Current JWT/HTTP safe push summary; local read never grants execution rights."""
import pytest
from sqlalchemy.orm import Session
from app.auth.models import ArkUser
from app.invoice import edit_authority, lifecycle_remote, order_push_facts as facts
from app.portal.authority import lock_authority
from test_mysql_order_push_execution import setup_push, execute, business
from test_mysql_order_push_recovery import accepted_after_expiry, mirror, recover, read_evidence

FIELDS = {"review_required", "pending_attempt_count", "last_observed_at", "result_class", "original_order_id", "resolution"}


def read(c, token=None):
    import asyncio
    return asyncio.run(c.e.write(f'/api/invoice/invoices/{c.e.invoice_id}/lifecycle', {}, 'GET', token or c.e.admin_token))


def test_empty_summary_is_private_and_read_only(editor, monkeypatch, tmp_path):
    c=setup_push(editor,monkeypatch,tmp_path);before=business(editor)
    response=read(c)
    assert response.status_code==200,response.text
    assert response.headers['cache-control']=='private, no-store'
    summary=response.json()['data']['order_push_summary']
    assert set(summary)==FIELDS and summary==dict(review_required=False,pending_attempt_count=0,
        last_observed_at=None,result_class='not_observed',original_order_id=None,resolution=None)
    assert c.tokens==[] and c.posts==[] and business(editor)==before


@pytest.mark.parametrize('bound',[False,True])
def test_late_original_reference_summary_recovery_and_no_raw_facts(editor,monkeypatch,tmp_path,bound):
    c=setup_push(editor,monkeypatch,tmp_path);mirror(c)
    accepted_after_expiry(c,monkeypatch,review_before='bind_order' if bound else 'confirm_not_created')
    before=business(editor);response=read(c)
    assert response.status_code==200 and business(editor)==before,response.text
    summary=response.json()['data']['order_push_summary']
    assert set(summary)==FIELDS and summary['review_required'] and summary['pending_attempt_count']==1
    assert summary['result_class']=='accepted' and summary['original_order_id']==c.target
    assert summary['resolution']==('confirm_existing' if bound else 'bind_order')
    assert summary['last_observed_at'].endswith('+08:00')
    for forbidden in ('attempt_key','payload_fingerprint','token_fingerprint','private-provider-body','Original order observation'):
        assert forbidden not in response.text
    evidence=read_evidence(c);calls=[]
    monkeypatch.setattr(lifecycle_remote,'read',lambda *a:calls.append(a[1:]) or evidence)
    assert recover(c,summary['resolution'],c.target if not bound else None).status_code==200
    after=read(c).json()['data']['order_push_summary']
    assert not after['review_required'] and after['resolution'] is None and after['original_order_id'] is None
    assert len(c.posts)==1 and len(calls)==1


@pytest.mark.parametrize('change',['draft','cancelled','different_binding','attempt'])
def test_summary_does_not_offer_late_recovery_for_ineligible_current_state(editor,monkeypatch,tmp_path,change):
    c=setup_push(editor,monkeypatch,tmp_path);accepted_after_expiry(c,monkeypatch,review_before=True)
    with Session(editor.ctx.engine) as db:
        lock_authority(db);invoice=edit_authority.lock_document(db,editor.invoice_id)
        if change=='draft':invoice.status='draft'
        elif change=='cancelled':invoice.status='cancelled'
        elif change=='different_binding':invoice.xiaoman_order_id='1234'
        else:invoice.sync_attempt={'token':'synthetic-current-execution'}
        db.commit()
    before=business(editor);response=read(c)
    assert response.status_code==200 and business(editor)==before,response.text
    assert response.json()['data']['order_push_summary']['review_required']
    assert response.json()['data']['order_push_summary']['resolution'] is None
    assert len(c.posts)==1


@pytest.mark.parametrize('revoke',['inactive','action','scope'])
def test_summary_old_jwt_cannot_return_private_order_reference(editor,monkeypatch,tmp_path,revoke):
    c=setup_push(editor,monkeypatch,tmp_path);accepted_after_expiry(c,monkeypatch,review_before=True)
    if revoke=='inactive':
        with Session(editor.ctx.engine) as db:
            lock_authority(db);db.get(ArkUser,editor.ctx.admin).is_active=False;db.commit()
    else:
        from test_mysql_invoice_cancellation_refresh import demote_admin
        demote_admin(editor,[] if revoke=='action' else ['invoice:admin'])
    before=business(editor);response=read(c)
    assert response.status_code==(404 if revoke=='scope' else 403),response.text
    assert response.headers['cache-control']=='private, no-store'
    assert c.target not in response.text and 'order_push_summary' not in response.text
    assert business(editor)==before and len(c.posts)==1
