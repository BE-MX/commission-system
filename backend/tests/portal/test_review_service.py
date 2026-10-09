import pytest
from test_approval_service import approving, accepted, proposing, submitted, submission, quoting, priced_catalog, catalog, managed, portal_metadata, auth_context, approve
from app.portal import review_service, admin_service
from app.portal.errors import PortalError


@pytest.fixture
def reviewer(approving, monkeypatch):
    original = admin_service.employee_principal
    def employee(db, actor_id, permission):
        actor = original(db, actor_id, permission)
        actor['permissions'] = {'portal_order:read', 'portal_order:write', 'invoice:write'}
        return actor
    monkeypatch.setattr(admin_service, 'employee_principal', employee)
    return approving


def test_review_context_current_accepted_revision_and_policy(reviewer):
    ctx, order, revision, _ = reviewer
    data = review_service.context(ctx.db, 1, order.public_id)
    assert data['order']['revision_id'] == revision.public_id
    assert data['order']['row_version'] == 3
    assert set(data['available_actions']) == {'propose', 'reject', 'approve'}
    assert data['policy']['payment_terms'][0]['code'] == 'prepaid'
    assert data['customer']['company_name'] == 'Buyer Company'
    assert data['customer']['customer_id'] == str(ctx.access.customer_id)
    assert data['customer']['okki_company_id'] == ctx.access.okki_company_id
    assert data['standard_lines'][0]['sku_id'] == str(_[0].sku_id)
    assert data['standard_lines'][0]['line_key'] == data['order']['items'][0]['line_key']
    from app.portal.order_queries import customer_detail
    customer = customer_detail(ctx.db, ctx.session_token, order.public_id)
    assert 'standard_lines' not in customer and 'customer' not in customer



def test_read_all_does_not_authorize_managing_another_salesperson(reviewer, monkeypatch):
    ctx, order, _, _ = reviewer
    monkeypatch.setattr(admin_service, 'employee_principal', lambda db, actor_id, permission:
        {'id': actor_id, 'roles': ['super_admin'], 'permissions': {'portal_order:read_all', 'portal_order:write'}})
    with pytest.raises(PortalError) as caught:
        review_service.context(ctx.db, 2, order.public_id)
    assert caught.value.status == 404


def test_disabled_invoice_and_order_switches_remove_new_actions(reviewer):
    ctx, order, _, _ = reviewer
    ctx.settings.PORTAL_INVOICE_ENABLED = False
    assert 'approve' not in review_service.context(ctx.db, 1, order.public_id)['available_actions']
    ctx.settings.PORTAL_WRITES_ENABLED = False
    assert review_service.context(ctx.db, 1, order.public_id)['available_actions'] == []


def test_invoice_permission_is_not_inferred_from_order_write(approving):
    ctx, order, _, _ = approving
    assert 'approve' not in review_service.context(ctx.db, 1, order.public_id)['available_actions']


def test_converted_request_no_initial_commands_and_no_live_inventory_dependency(reviewer):
    ctx, order, revision, _ = reviewer
    approve(ctx, order, revision)
    ctx.observations = {}
    data = review_service.context(ctx.db, 1, order.public_id)
    assert data['available_actions'] == []
    assert data['order']['status'] == 'invoice_created'


def test_review_quantity_rules_use_current_authorization_without_inventory(reviewer):
    from sqlalchemy import select
    from app.portal.models import CatalogGrant
    ctx, order, _, records = reviewer
    item = ctx.items[0]
    item.min_qty, item.step_qty = 3, 2
    ctx.db.commit(); ctx.observations = {}
    result = review_service.context(ctx.db, 1, order.public_id)
    assert result['quantity_rules'] == [{'item_id': item.public_id, 'min_order_qty': 3, 'step_qty': 2}]
    grant = ctx.db.scalar(select(CatalogGrant).where(CatalogGrant.access_id == ctx.access.id, CatalogGrant.catalog_item_id == item.id))
    grant.status = 'disabled'; ctx.db.commit()
    result = review_service.context(ctx.db, 1, order.public_id)
    assert result['quantity_rules'] == []
    assert result['order']['items'][0]['quantity'] == records[0].qty
