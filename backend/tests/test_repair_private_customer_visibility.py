"""Visibility repair preserves existing permissions and ownership boundaries."""
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.auth.models import ArkPermission, ArkPermissionAudit, ArkRole, ArkRolePermission, ArkUserRole
from scripts import repair_private_customer_visibility as repair
from tests.test_customer_workflow import _user


@pytest.mark.parametrize('targets,existing,expected', [
    ([16], None, (16, None)),
    ([16, 17], None, (None, 'needs_primary_review')),
    ([16, 17], 17, (17, None)),
    ([16], 17, (None, 'ownership_conflict')),
    ([], None, (None, 'needs_primary_review')),
])
def test_primary_is_never_arbitrarily_selected_or_transferred(targets, existing, expected):
    assert repair.choose_primary(targets, existing) == expected


def test_permission_addition_is_audited_additive_and_idempotent(db):
    operator = _user(db, 1)
    role = ArkRole(name='salesperson', label='Salesperson')
    old = ArkPermission(code='order:read', module='order', action='read', label='Read orders')
    new = ArkPermission(code='customer:read', module='customer', action='read', label='Read own customers')
    all_customers = ArkPermission(code='customer:read_all', module='customer', action='read_all', label='Read all')
    db.add_all([role, old, new, all_customers])
    db.flush()
    db.add(ArkRolePermission(role_id=role.id, permission_id=old.id))
    db.flush()
    assert repair.grant_customer_read(db, operator) is True
    assert repair.grant_customer_read(db, operator) is False
    assert {p.permission_id for p in db.query(ArkRolePermission).filter_by(role_id=role.id)} == {old.id, new.id}
    audit = db.query(ArkPermissionAudit).one()
    assert audit.added_codes == ['customer:read']
    assert audit.removed_codes == []
    assert audit.operator_user_id == operator.id


def _source(db, owners):
    db.execute(text('ALTER TABLE lsordertest.customer_info ADD COLUMN update_time DATETIME'))
    db.execute(text('INSERT INTO lsordertest.customer_info (company_id, company_name, owner_user_ids) VALUES (:id, :name, :owners)'),
               {'id': '42', 'name': 'Example', 'owners': owners})


def test_source_owner_change_prevents_any_projection(db, monkeypatch):
    _source(db, '[99]')
    monkeypatch.setattr(repair, '_sync_one_customer', lambda *a, **k: pytest.fail('must not project'))
    result = repair.repair_customer(db, {'company_id': '42', 'owner_user_ids': [16], 'targets': []}, SimpleNamespace(id=1), with_orders=False)
    assert result['status'] == 'source_owner_changed'


def test_failed_assignment_rolls_back_customer_projection(db, monkeypatch):
    user = _user(db, 16)
    role = ArkRole(name='salesperson', label='Salesperson')
    db.add(role)
    db.flush()
    db.add(ArkUserRole(user_id=user.id, role_id=role.id))
    _source(db, '["56046345"]')
    db.commit()
    monkeypatch.setattr(repair, '_resolve_okki_owner', lambda *_: (user, '56046345'))
    def failed_projection(session, *_args, **_kwargs):
        session.add(ArkRole(name='should_rollback', label='Temporary'))
        session.flush()
        return {'company_id': '42', 'customer_id': 999, 'assigned': False}
    monkeypatch.setattr(repair, '_sync_one_customer', failed_projection)
    result = repair.repair_customer(db, {'company_id': '42', 'owner_user_ids': [56046345],
        'targets': [{'id': 16, 'username': user.username, 'external_account_id': '56046345'}]}, user, with_orders=False)
    assert result['status'] == 'assignment_failed'
    assert db.query(ArkRole).filter_by(name='should_rollback').count() == 0
