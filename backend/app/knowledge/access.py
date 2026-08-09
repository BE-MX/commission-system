"""Central knowledge platform-permission and resource-ACL decisions."""

from app.knowledge.models import KnowledgeLibraryMember


ROLES = {"viewer", "editor", "reviewer", "admin"}
CAPABILITIES = {
    "read": ROLES,
    "write": {"editor", "admin"},
    "review": {"reviewer", "admin"},
    "admin": {"admin"},
}


def user_id(identity: dict) -> int:
    return int(identity["sub"])


def is_super_admin(identity: dict) -> bool:
    return "super_admin" in identity.get("roles", [])


def has_platform(identity: dict, permission: str) -> bool:
    if is_super_admin(identity):
        return True
    permissions = set(identity.get("permissions", []))
    if "knowledge:admin" in permissions:
        return True
    if permission == "knowledge:read" and permissions.intersection(
        {"knowledge:read", "knowledge:write", "knowledge:review"}
    ):
        return True
    return permission in permissions


def member_role(db, identity: dict, library_id: int) -> str | None:
    if is_super_admin(identity):
        return "admin"
    row = db.query(KnowledgeLibraryMember).filter(
        KnowledgeLibraryMember.library_id == library_id,
        KnowledgeLibraryMember.user_id == user_id(identity),
    ).first()
    return row.role if row else None


def can(db, identity: dict, library_id: int, capability: str) -> bool:
    role = member_role(db, identity, library_id)
    return role in CAPABILITIES[capability]
