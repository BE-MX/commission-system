"""Live employee authorization and permission seed use real auth model queries."""
import pytest
from sqlalchemy import select, func

from test_access_policy import binding_db
from app.auth.models import ArkRole, ArkPermission, ArkUserRole, ArkRolePermission
from app.auth.service import seed_role_permissions
from app.portal.access_policy import employee_principal
from app.portal.errors import PortalError


@pytest.fixture
def authorization_db(binding_db):
    db, _, metadata = binding_db
    for model in (ArkRole, ArkPermission, ArkUserRole, ArkRolePermission):
        model.__table__.to_metadata(metadata)
    metadata.create_all(db.get_bind())
    role = ArkRole(id=1, name="sales", label="Sales")
    permission = ArkPermission(id=1, code="portal_access:admin", module="portal_access",
                               action="admin", label="Portal", kind="action", is_legacy=False, sort=10)
    db.add_all([role, permission])
    db.flush()
    db.add_all([ArkUserRole(user_id=1, role_id=1), ArkRolePermission(role_id=1, permission_id=1)])
    db.commit()
    return db


def test_live_employee_permission_revocation(authorization_db):
    db = authorization_db
    assert employee_principal(db, 1, "portal_access:admin")["id"] == 1
    db.execute(ArkRolePermission.__table__.delete().where(ArkRolePermission.role_id == 1))
    db.commit()
    with pytest.raises(PortalError) as error:
        employee_principal(db, 1, "portal_access:admin")
    assert error.value.status == 403


def test_super_admin_bypass_disappears_when_role_removed(authorization_db):
    db = authorization_db
    role = db.get(ArkRole, 1)
    role.name = "super_admin"
    db.commit()
    assert employee_principal(db, 1, "portal_site:admin")["roles"] == ["super_admin"]
    role.name = "sales"
    db.commit()
    with pytest.raises(PortalError):
        employee_principal(db, 1, "portal_site:admin")


def test_portal_permission_seed_is_repeatable_and_preserves_kind(authorization_db):
    db = authorization_db
    seed_role_permissions(db)
    seed_role_permissions(db)
    rows = db.scalars(select(ArkPermission).where(ArkPermission.code.like("portal_%"))).all()
    assert len(rows) == 8
    assert {row.code: row.kind for row in rows} == {
        "portal_order:read": "action", "portal_order:write": "action", "portal_order:read_all": "data",
        "portal_access:read": "action", "portal_access:admin": "action",
        "portal_mapping:read": "action", "portal_mapping:write": "action", "portal_site:admin": "action"}
