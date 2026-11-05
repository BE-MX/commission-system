"""Live source access and dependency validation, independent of legacy CRM rights."""

from fastapi import HTTPException
from app.whatsapp.access import live_actor, readable_accounts, require_body
from app.whatsapp.models import WhatsAppAccount
from app.client_desk.private_scope import user_id


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


def dependencies_valid(db, user, company_id, dependencies):
    if not dependencies:
        return False
    from app.client_desk.sources import build_customer_sources

    current = build_customer_sources(db, user, company_id, for_ai=True, realtime=False)
    expected = dict(dependencies)
    feed = expected.pop("alibaba_feed", None)
    if current["source_dependencies"] != expected:
        return False
    if feed is not None:
        from app.alibaba_feed.business_service import dependencies_valid as feed_valid

        return feed_valid(db, user, company_id, feed)
    return True


def require_enabled(db, user, write=False):
    from app.core.config import get_settings

    settings = get_settings()
    uid = user_id(user)
    if (
        not settings.CLIENT_DESK_ENABLED
        or uid not in settings.CLIENT_DESK_PILOT_USER_IDS
    ):
        raise HTTPException(403, "私海助理尚未对当前用户开启")
    try:
        return live_actor(db, uid, "client_desk:write" if write else "client_desk:read")
    except PermissionError as exc:
        raise HTTPException(403, "无私海助理操作权限") from exc
