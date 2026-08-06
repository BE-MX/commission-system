"""Design Image Studio RBAC seed contract tests."""

from app.auth.models import ArkPermission, ArkRole, ArkRolePermission
from app.auth.service import seed_role_permissions


PERMISSION_CODES = {
    "design_image:read",
    "design_image:write",
    "design_image:admin",
}


def test_design_image_permission_seed_is_idempotent_and_has_stable_metadata(db):
    db.add_all([
        ArkRole(name="admin", label="系统管理员", is_system=True),
        ArkRole(name="designer", label="设计师", is_system=False),
    ])
    db.commit()

    seed_role_permissions(db)
    seed_role_permissions(db)

    permissions = (
        db.query(ArkPermission)
        .filter(ArkPermission.code.in_(PERMISSION_CODES))
        .all()
    )
    assert {permission.code for permission in permissions} == PERMISSION_CODES
    assert db.query(ArkPermission).filter(
        ArkPermission.code.in_(PERMISSION_CODES)
    ).count() == 3
    metadata = {
        permission.code: (permission.module, permission.action, permission.kind)
        for permission in permissions
    }
    assert metadata == {
        "design_image:read": ("design_image", "read", "page"),
        "design_image:write": ("design_image", "write", "action"),
        "design_image:admin": ("design_image", "admin", "action"),
    }


def test_only_existing_system_admin_expansion_receives_new_permissions(db):
    admin = ArkRole(name="admin", label="系统管理员", is_system=True)
    broad_business_role = ArkRole(name="designer", label="设计师", is_system=False)
    db.add_all([admin, broad_business_role])
    db.commit()

    seed_role_permissions(db)

    permission_ids = {
        permission.id
        for permission in db.query(ArkPermission).filter(
            ArkPermission.code.in_(PERMISSION_CODES)
        )
    }
    assert permission_ids
    admin_permission_ids = {
        row.permission_id
        for row in db.query(ArkRolePermission).filter(
            ArkRolePermission.role_id == admin.id,
            ArkRolePermission.permission_id.in_(permission_ids),
        )
    }
    business_permission_ids = {
        row.permission_id
        for row in db.query(ArkRolePermission).filter(
            ArkRolePermission.role_id == broad_business_role.id,
            ArkRolePermission.permission_id.in_(permission_ids),
        )
    }
    assert admin_permission_ids == permission_ids
    assert business_permission_ids == set()
