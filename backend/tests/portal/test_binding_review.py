import pytest
from sqlalchemy import select
from test_ownership_service import handoff, request_record
from test_admin_service import managed, portal_metadata, new_identity
from test_auth_service import auth_context
from app.customer.models import CustomerExternalIdentity, CustomerAssignment
from app.portal import binding_review_service as review, admin_service as admin
from app.portal.ownership_service import transfer_customer
from app.portal.schemas import TransferInput, RebindInput
from app.portal.errors import PortalError


def transfer_body(ctx, fingerprint, selected=()):
    return TransferInput(assignment_id='2',review_fingerprint=fingerprint,pending_request_ids=list(selected),history_policy='remove',reason='Reviewed reassignment')


def test_context_only_offers_current_assignments_and_safe_pending_rows(handoff):
    ctx=handoff
    pending=request_record(ctx,1,'submitted');request_record(ctx,2,'cancelled');ctx.db.commit()
    result=review.context(ctx.db,1,ctx.access.public_id)
    assert [row['id'] for row in result['assignments']]==['2']
    assert result['requires_assignment_review'] is True and result['order_total']==2
    assert result['pending_total']==1 and result['pending_requests'][0]['id']==pending.public_id
    assert set(result['pending_requests'][0])=={'id','public_no','status','row_version','servicing_user_id'}
    assert result['identities'][0]['company_id']=='1'
    assert len(result['review_fingerprint'])==64


def test_new_order_after_review_rejects_transfer_without_mutation(handoff):
    ctx=handoff
    old=review.context(ctx.db,1,ctx.access.public_id);ctx.db.commit()
    request_record(ctx,1,'submitted');ctx.db.commit()
    with pytest.raises(PortalError) as caught: transfer_customer(ctx.db,1,ctx.access.public_id,1,transfer_body(ctx,old['review_fingerprint']))
    assert caught.value.code=='REVIEW_CHANGED'
    assert ctx.access.sales_user_id==1 and ctx.access.row_version==1


def test_pending_status_change_invalidates_review_even_without_access_version(handoff):
    ctx=handoff
    pending=request_record(ctx,1,'submitted');ctx.db.commit()
    old=review.context(ctx.db,1,ctx.access.public_id);ctx.db.commit()
    pending.status='cancelled';pending.row_version+=1;ctx.db.commit()
    with pytest.raises(PortalError) as caught: transfer_customer(ctx.db,1,ctx.access.public_id,1,transfer_body(ctx,old['review_fingerprint'],[pending.public_id]))
    assert caught.value.code=='REVIEW_CHANGED' and ctx.access.sales_user_id==1


def test_same_assignment_id_changed_in_place_invalidates_review(handoff):
    ctx=handoff
    old=review.context(ctx.db,1,ctx.access.public_id);ctx.db.commit()
    assignment=ctx.db.get(CustomerAssignment,2);assignment.user_id=1;ctx.db.commit()
    with pytest.raises(PortalError) as caught: transfer_customer(ctx.db,1,ctx.access.public_id,1,transfer_body(ctx,old['review_fingerprint']))
    assert caught.value.code=='REVIEW_CHANGED'


def test_same_external_identity_id_changed_in_place_rejects_rebind(managed,portal_metadata):
    ctx=managed;new_identity(ctx,portal_metadata)
    old=review.context(ctx.db,1,ctx.access.public_id);ctx.db.commit()
    identity=ctx.db.get(CustomerExternalIdentity,2);identity.normalized_value='changed-company';ctx.db.commit()
    with pytest.raises(PortalError) as caught:
        admin.rebind_identity(ctx.db,1,ctx.access.public_id,1,RebindInput(identity_id='2',review_fingerprint=old['review_fingerprint'],reason='Reviewed binding'))
    assert caught.value.code=='REVIEW_CHANGED'
    assert ctx.access.okki_company_id=='1' and ctx.access.row_version==1


def test_review_still_requires_scope_and_permission(managed):
    ctx=managed
    for actor,status in [(2,404),(3,403)]:
        with pytest.raises(PortalError) as caught:review.context(ctx.db,actor,ctx.access.public_id)
        assert caught.value.status==status
        ctx.db.rollback()


def test_forged_identity_outside_configured_namespace_is_rejected(managed,portal_metadata):
    ctx=managed;new_identity(ctx,portal_metadata)
    identity=ctx.db.get(CustomerExternalIdentity,2);identity.source_account_key='other-namespace';ctx.db.commit()
    result=review.context(ctx.db,1,ctx.access.public_id)
    assert '2' not in {row['id'] for row in result['identities']}
    with pytest.raises(PortalError) as caught:
        admin.rebind_identity(ctx.db,1,ctx.access.public_id,1,RebindInput(identity_id='2',review_fingerprint=result['review_fingerprint'],reason='Forged choice'))
    assert caught.value.code=='IDENTITY_REVIEW_REQUIRED' and ctx.access.okki_company_id=='1'
