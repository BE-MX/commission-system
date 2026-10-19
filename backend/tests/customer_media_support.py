"""Persist test roles so HTTP tests exercise live authorization."""
from app.auth.models import ArkPermission, ArkRole, ArkRolePermission, ArkUserRole


def set_grants(db, user_id, codes):
    role = db.query(ArkRole).filter_by(name=f"media-test-{user_id}").first()
    if role is None:
        role = ArkRole(name=f"media-test-{user_id}", label="Media test")
        db.add(role)
        db.flush()
        db.add(ArkUserRole(user_id=user_id, role_id=role.id))
    db.query(ArkRolePermission).filter_by(role_id=role.id).delete()
    for code in codes:
        permission = db.query(ArkPermission).filter_by(code=code).first()
        if permission is None:
            permission = ArkPermission(code=code, module="customer_media", action=code.split(":")[1], label=code)
            db.add(permission)
            db.flush()
        db.add(ArkRolePermission(role_id=role.id, permission_id=permission.id))
    db.commit()
