"""Live source access and dependency validation, independent of legacy CRM rights."""

from fastapi import HTTPException
from sqlalchemy import or_, select
from app.auth.models import ArkRole, ArkUser, ArkUserRole
from app.whatsapp.access import live_actor, readable_accounts, require_body
from app.whatsapp.models import WhatsAppAccount
from app.client_desk.private_scope import user_id


SALESPERSON_ROLE = "salesperson"


def enrolled(settings, uid, roles=()):
    return uid in settings.CLIENT_DESK_PILOT_USER_IDS or (
        settings.CLIENT_DESK_SALESPERSON_ACCESS_ENABLED and SALESPERSON_ROLE in roles
    )


def enrolled_user_ids(settings):
    members = ArkUser.id.in_(settings.CLIENT_DESK_PILOT_USER_IDS)
    if settings.CLIENT_DESK_SALESPERSON_ACCESS_ENABLED:
        salespeople = (
            select(ArkUserRole.user_id)
            .join(ArkRole, ArkRole.id == ArkUserRole.role_id)
            .where(ArkRole.name == SALESPERSON_ROLE)
        )
        members = or_(members, ArkUser.id.in_(salespeople))
    return select(ArkUser.id).where(
        ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None), members
    )


def require_account(db, user, account_uid, *, for_ai=False, owner_only=False):
    uid = user_id(user)
    try:
        live_actor(db, uid, "client_desk:read", "client_desk:write")
    except PermissionError as exc:
        raise HTTPException(403, "无私海助理操作权限") from exc
    account = (
        db.query(WhatsAppAccount)
        .filter(WhatsAppAccount.account_uid == account_uid)
        .populate_existing()
        .first()
    )
    if account is None or (owner_only and account.ark_user_id != uid):
        raise HTTPException(404, "会话不存在或不可访问")
    if account_uid not in {
        r[0] for r in readable_accounts(db, uid, crm=True, ai=for_ai).all()
    }:
        raise HTTPException(404, "会话不存在或不可访问")
    require_body(db, account, uid, crm=True, purpose="client_desk")
    return account


def dependencies_valid(db, user, company_id, dependencies, *, source=None):
    if not dependencies:
        return False
    from app.client_desk.sources import build_customer_sources

    current = source if source is not None else build_customer_sources(
        db, user, company_id, for_ai=True, realtime=False
    )
    expected = dict(dependencies)
    feed = expected.pop("alibaba_feed", None)
    if current.get("ai_source_dependencies", current["source_dependencies"]) != expected:
        return False
    if feed is not None:
        from app.alibaba_feed.business_service import dependencies_valid as feed_valid

        return feed_valid(db, user, company_id, feed)
    return True


def require_enabled(db, user, write=False):
    from app.core.config import get_settings

    settings = get_settings()
    uid = user_id(user)
    if not settings.CLIENT_DESK_ENABLED or (
        not settings.CLIENT_DESK_SALESPERSON_ACCESS_ENABLED and not enrolled(settings, uid)
    ):
        raise HTTPException(403, "私海助理尚未对当前用户开启")
    try:
        actor = live_actor(db, uid, "client_desk:write" if write else "client_desk:read")
    except PermissionError as exc:
        raise HTTPException(403, "无私海助理操作权限") from exc
    if not enrolled(settings, uid, actor["roles"]):
        raise HTTPException(403, "私海助理尚未对当前用户开启")
    return actor
