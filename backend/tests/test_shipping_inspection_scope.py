"""Inspection scope uses outbound ownership, not the inspector's identity."""
import pytest
from sqlalchemy import text
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto
from tests.test_shipping_inspection import (
    _user, _bind_okki, _pc_client, _submit_one, storage,
    product_display_source, outbound_scope_seed,
)

READ = "shipping_inspection:read"
ALL = "shipping_inspection:inspection_read_all"


@pytest.fixture
def scoped_inspections(db, storage, outbound_scope_seed):
    sales = _user(db, "sales")
    inspector = _user(db, "inspector")
    _bind_okki(db, sales)
    _submit_one(db, inspector)
    _submit_one(db, inspector, "OB002", "IT003")
    records = db.query(ShippingInspection).order_by(ShippingInspection.outbound_record_id).all()
    photos = [db.query(ShippingInspectionPhoto).filter_by(inspection_id=r.id).first() for r in records]
    # The same private media route serves videos too.
    photos[1].media_type = "video"
    db.commit()
    return sales, records, photos


def test_list_pagination_and_all_read_paths_are_scoped(db, scoped_inspections):
    sales, records, photos = scoped_inspections
    with _pc_client(db, sales, [READ, "shipping_inspection:write"]) as client:
        listing = client.get('/api/shipping-inspection/records', params={'page_size':1}).json()['data']
        assert listing['total'] == 1
        assert [r['id'] for r in listing['items']] == [records[0].id]
        assert client.get('/api/shipping-inspection/records', params={'page':2, 'page_size':1}).json()['data']['items'] == []
        assert client.get('/api/shipping-inspection/records', params={'keyword':'客户乙'}).json()['data']['total'] == 0
        assert client.get(f'/api/shipping-inspection/records/{records[0].id}').status_code == 200
        assert client.get(f'/api/shipping-inspection/images/{photos[0].file_path}').status_code == 200
        assert client.get(f'/api/shipping-inspection/records/{records[1].id}').status_code == 404
        assert client.get(f'/api/shipping-inspection/images/{photos[1].file_path}').status_code == 404
        assert client.post(f'/api/shipping-inspection/records/{records[1].id}/recall', json={'edit_version':0}).status_code == 404
        assert db.get(ShippingInspection, records[1].id).status == 'submitted'
        assert client.post(f'/api/shipping-inspection/records/{records[0].id}/recall', json={'edit_version':0}).status_code == 200


def test_permissions_are_independent_and_all_scope_is_not_write(db, scoped_inspections):
    sales, records, photos = scoped_inspections
    with _pc_client(db, sales, [READ, 'shipping_inspection:read_all']) as client:
        assert client.get('/api/shipping-inspection/records').json()['data']['total'] == 1
    with _pc_client(db, sales, [READ, ALL]) as client:
        assert client.get('/api/shipping-inspection/records').json()['data']['total'] == 2
        assert client.get('/api/shipping-inspection/outbound-records').json()['data']['total'] == 1
        assert client.get(f'/api/shipping-inspection/records/{records[1].id}').status_code == 200
        assert client.get(f'/api/shipping-inspection/images/{photos[1].file_path}').status_code == 200
        assert client.post(f'/api/shipping-inspection/records/{records[1].id}/recall', json={'edit_version':0}).status_code == 403
    with _pc_client(db, sales, [ALL]) as client:
        assert client.get('/api/shipping-inspection/records').status_code == 403


def test_unbound_user_fails_closed_but_explicit_all_and_super_admin_work(db, scoped_inspections):
    _, records, photos = scoped_inspections
    user = _user(db, 'unbound')
    with _pc_client(db, user, [READ]) as client:
        for route in ('records', f'records/{records[0].id}', f'images/{photos[0].file_path}'):
            assert client.get('/api/shipping-inspection/' + route).status_code == 422
    for perms, roles in (([READ, ALL], []), ([], ['super_admin'])):
        with _pc_client(db, user, perms, roles=roles) as client:
            assert client.get('/api/shipping-inspection/records').json()['data']['total'] == 2


def test_ownership_changes_apply_and_missing_scope_column_never_returns_all(db, scoped_inspections):
    sales, records, _ = scoped_inspections
    db.execute(text("UPDATE lsordertest.okki_orders SET user_id='9002' WHERE company_id='C1'"))
    db.commit()
    with _pc_client(db, sales, [READ]) as client:
        assert client.get('/api/shipping-inspection/records').json()['data']['total'] == 0
        assert client.get(f'/api/shipping-inspection/records/{records[0].id}').status_code == 404
    from app.shipping_inspection import outbound_service
    outbound_service._columns_cache.clear()
    db.execute(text('ALTER TABLE lsordertest.okki_outbound_records DROP COLUMN company_id'))
    with _pc_client(db, sales, [READ]) as client:
        assert client.get('/api/shipping-inspection/records').status_code == 500


def test_permission_seed_is_data_scope_and_not_automatically_granted(db):
    from app.auth.service import seed_role_permissions
    from app.auth.models import ArkPermission, ArkRole
    seed_role_permissions(db)
    permission = db.query(ArkPermission).filter_by(code=ALL).one()
    assert permission.kind == 'data'
    for role in db.query(ArkRole).all():
        assert ALL not in [p.code for p in role.permissions]
