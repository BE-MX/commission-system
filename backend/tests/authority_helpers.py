"""Live-authority seeding for hardened endpoints.

The invoice/receipt/portal authority paths read the actor's current roles and
permissions from the database (get_live_user_authorization); JWT "permissions"
claims only gate legacy dependencies. Tests therefore seed exactly the grants
each actor holds. The authority barrier row itself is seeded once by the shared
engine fixture (tests/conftest.py), mirroring migration 175; engines built
outside that fixture must create and seed ark_order_portal_auth_barriers
themselves.
"""

from app.auth.models import (
    ArkPermission,
    ArkRole,
    ArkRolePermission,
    ArkUser,
    ArkUserRole,
)


def seed_authority(db, user_id: int, *codes: str, roles=()) -> None:
    """Give an active user one dedicated role carrying exactly ``codes``.

    Safe to call for an existing user (attaches an additional role) and safe to
    repeat for the same permission codes (reuses rows). Commits so the grants
    survive the per-request rollback used by shared-session TestClient
    overrides.
    """
    if db.get(ArkUser, user_id) is None:
        db.add(ArkUser(
            id=user_id, username=f"authority-{user_id}", password_hash="x",
            real_name=f"Authority {user_id}", is_active=True,
        ))
    index = db.query(ArkUserRole).filter_by(user_id=user_id).count()
    role = ArkRole(name=f"authority_role_{user_id}_{index}", label=f"Authority role {user_id}")
    db.add(role)
    db.flush()
    db.add(ArkUserRole(user_id=user_id, role_id=role.id))
    for code in codes:
        permission = db.query(ArkPermission).filter_by(code=code).one_or_none()
        if permission is None:
            module, _, action = code.partition(":")
            permission = ArkPermission(
                code=code, module=module, action=action, label=code,
                kind="action", is_legacy=False, sort=1,
            )
            db.add(permission)
            db.flush()
        db.add(ArkRolePermission(role_id=role.id, permission_id=permission.id))
    for name in roles:
        named = db.query(ArkRole).filter_by(name=name).one_or_none()
        if named is None:
            named = ArkRole(name=name, label=name)
            db.add(named)
            db.flush()
        db.add(ArkUserRole(user_id=user_id, role_id=named.id))
    db.commit()
