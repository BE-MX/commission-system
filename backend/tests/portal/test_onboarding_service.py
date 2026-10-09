from datetime import timedelta
import pytest
from sqlalchemy import func, select
from test_admin_service import managed, portal_metadata
from test_auth_service import auth_context
from app.core.time import beijing_now
from app.portal import onboarding_service as service, admin_service as admin
from app.portal.models import CatalogItem, CustomerAccess, Invitation
from app.portal.schemas import CustomerCreate
from app.portal.errors import PortalError


def add_customer(ctx, metadata, identifier, owner=1, *, namespace='okki:test', verified='verified'):
    ctx.db.execute(metadata.tables['ark_customer_accounts'].insert(), {'id': identifier, 'display_name': f'Buyer {identifier}',
        'customer_code': f'C-{identifier}', 'record_status': 'active', 'identity_status': 'verified'})
    ctx.db.execute(metadata.tables['ark_customer_assignments'].insert(), {'id': identifier, 'customer_id': identifier,
        'user_id': owner, 'assignment_role': 'primary', 'assignment_status': 'active', 'effective_from': beijing_now() - timedelta(days=1)})
    ctx.db.execute(metadata.tables['ark_customer_external_identities'].insert(), {'id': identifier, 'customer_id': identifier,
        'source_system': 'okki', 'source_account_key': namespace, 'identifier_type': 'company_id', 'normalized_value': str(identifier),
        'identity_strength': 'strong', 'cardinality': 'one_to_one', 'verification_status': verified, 'status': 'active'})
    ctx.db.commit()


@pytest.fixture
def onboarding(managed, portal_metadata):
    ctx = managed
    ctx.settings.PORTAL_OKKI_NAMESPACE = 'okki:test'
    add_customer(ctx, portal_metadata, 2)
    ctx.selection_fingerprint = service.status(ctx.db, 1, 2)["binding_fingerprint"]
    ctx.db.commit()
    return ctx


def body(ctx, **extra):
    return CustomerCreate(binding_fingerprint=ctx.selection_fingerprint, canonical_customer_id='2', assignment_id='2', okki_identity_id='2',
        catalog_item_ids=[], capabilities={'can_order': True, 'can_view_price': True}, **extra)


def test_candidates_show_existing_and_ready_without_foreign_scope(onboarding, portal_metadata):
    ctx = onboarding
    ctx.db.execute(portal_metadata.tables['ark_users'].insert(), {'id': 2, 'is_active': True, 'real_name': 'Other salesperson'})
    ctx.db.commit()
    add_customer(ctx, portal_metadata, 3, owner=2)
    result = service.list_candidates(ctx.db, 1)
    assert result['total'] == 2
    by_id = {row['canonical_customer_id']: row for row in result['items']}
    assert by_id['2']['ready'] and by_id['2']['assignment_id'] == '2'
    assert by_id['1']['existing_access']['id'] == ctx.access.public_id
    assert not by_id['1']['ready']
    assert service.list_candidates(ctx.db, 1, keyword='%')['total'] == 0
    assert service.list_candidates(ctx.db, 1, keyword='C-2')['total'] == 1
    with pytest.raises(PortalError) as caught:
        service.status(ctx.db, 1, 3)
    assert caught.value.status == 404


def test_create_draft_and_readback_cannot_create_second_access(onboarding):
    ctx = onboarding
    created = admin.create_customer(ctx.db, 1, body(ctx))
    ctx.db.commit()
    assert created['status'] == 'draft'
    recovered = service.status(ctx.db, 1, 2)
    assert recovered['existing_access']['id'] == created['id']
    with pytest.raises(PortalError) as caught:
        admin.create_customer(ctx.db, 1, body(ctx))
    assert caught.value.code == 'ACCESS_ALREADY_EXISTS'
    assert ctx.db.scalar(select(func.count()).select_from(CustomerAccess)) == 2
    assert ctx.db.scalar(select(func.count()).select_from(Invitation)) == 0


@pytest.mark.parametrize('field,value,reason', [('verification_status','candidate','VERIFIED_IDENTITY_MISSING'), ('source_account_key','other','VERIFIED_IDENTITY_MISSING')])
def test_ineligible_identity_explained_and_create_revalidated(onboarding, portal_metadata, field, value, reason):
    ctx = onboarding
    table = portal_metadata.tables['ark_customer_external_identities']
    ctx.db.execute(table.update().where(table.c.id == 2).values(**{field:value}))
    ctx.db.commit()
    candidate = service.status(ctx.db, 1, 2)
    assert reason in candidate['blocked_reasons'] and not candidate['ready']
    with pytest.raises(PortalError) as caught:
        admin.create_customer(ctx.db, 1, body(ctx))
    assert caught.value.code == 'IDENTITY_REVIEW_REQUIRED'


def test_multiple_verified_identities_are_not_silently_chosen(onboarding, portal_metadata):
    ctx = onboarding
    table = portal_metadata.tables['ark_customer_external_identities']
    ctx.db.execute(table.insert(), {'id': 9, 'customer_id': 2, 'source_system': 'okki', 'source_account_key': 'okki:test',
        'identifier_type': 'company_id', 'normalized_value': '9', 'identity_strength': 'strong', 'cardinality': 'one_to_one',
        'verification_status': 'verified', 'status': 'active'})
    ctx.db.commit()
    assert service.status(ctx.db, 1, 2)['blocked_reasons'] == ['MULTIPLE_VERIFIED_IDENTITIES']
    with pytest.raises(PortalError): admin.create_customer(ctx.db, 1, body(ctx))


def test_creation_rechecks_assignment_after_selection(onboarding, portal_metadata):
    ctx = onboarding
    assert service.status(ctx.db, 1, 2)['ready']
    table = portal_metadata.tables['ark_customer_assignments']
    ctx.db.execute(table.update().where(table.c.id == 2).values(assignment_status='ended'))
    ctx.db.commit()
    with pytest.raises(PortalError) as caught: admin.create_customer(ctx.db, 1, body(ctx))
    assert caught.value.status == 404


def test_effective_identity_owner_overrides_storage_owner(onboarding, portal_metadata):
    ctx = onboarding
    table = portal_metadata.tables['ark_customer_external_identities']
    ctx.db.execute(table.update().where(table.c.id == 2).values(customer_id=1))
    ctx.db.execute(portal_metadata.tables['ark_customer_object_ownerships'].insert(),
        {'id': 20, 'object_type': 'external_identity', 'object_id': 2, 'current_customer_id': 2})
    ctx.db.commit()
    assert service.status(ctx.db, 1, 2)['ready']
    assert admin.create_customer(ctx.db, 1, body(ctx))['canonical_customer_id'] == '2'


def test_catalog_options_show_published_safe_fields_only(onboarding):
    ctx = onboarding
    for status in ['published', 'draft', 'disabled']:
        ctx.db.add(CatalogItem(site_id=ctx.site.id, product_kind='hair', source_namespace='okki:test',
            product_id=status, sku_id=status, standard_fingerprint='a'*64, standard_json={'length':'20in','weight':'20g'},
            display_name='Standard Weft', color_name='Black', status=status, inventory_unit='g', sale_unit='pack', conversion_factor='20'))
    ctx.db.commit()
    result = service.catalog_options(ctx.db, 1)
    assert result['total'] == 1
    assert set(result['items'][0]) == {'id','model_name','color_name','length','weight','sale_unit','product_kind'}
    assert service.catalog_options(ctx.db, 1, keyword='%')['total'] == 0
    with pytest.raises(PortalError): service.catalog_options(ctx.db, 3)


def test_selected_identity_value_changed_in_place_requires_reselection(onboarding, portal_metadata):
    ctx = onboarding
    submitted = body(ctx)
    table = portal_metadata.tables['ark_customer_external_identities']
    ctx.db.execute(table.update().where(table.c.id == 2).values(normalized_value='changed-company'))
    ctx.db.commit()
    with pytest.raises(PortalError) as caught:
        admin.create_customer(ctx.db, 1, submitted)
    assert caught.value.code == 'IDENTITY_REVIEW_REQUIRED'
    assert ctx.db.scalar(select(func.count()).select_from(CustomerAccess)) == 1


def test_identity_follows_source_record_logical_owner(onboarding, portal_metadata):
    ctx = onboarding
    ctx.db.execute(portal_metadata.tables['ark_customer_source_records'].insert(), {'id': 99, 'customer_id': 1})
    ctx.db.execute(portal_metadata.tables['ark_customer_object_ownerships'].insert(),
        {'id': 21, 'object_type': 'source_record', 'object_id': 99, 'current_customer_id': 2})
    table = portal_metadata.tables['ark_customer_external_identities']
    ctx.db.execute(table.update().where(table.c.id == 2).values(customer_id=1, source_record_id=99))
    ctx.db.commit()
    assert service.status(ctx.db, 1, 2)['ready']
    assert admin.create_customer(ctx.db, 1, body(ctx))['canonical_customer_id'] == '2'
