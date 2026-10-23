"""Live source ACL shared by WhatsApp API, workers and the customer domain."""
from sqlalchemy import and_, or_, select, literal
from sqlalchemy.orm import Session

from app.auth.models import ArkUser, ArkRole, ArkUserRole, ArkPermission, ArkRolePermission
from app.auth.service import get_live_user_authorization
from app.whatsapp.models import WhatsAppAccount, WhatsAppBodyGrant


def live_actor(db: Session, user_id: int, *permissions: str, fresh: bool = False) -> dict:
    query = db.query(ArkUser).filter(
        ArkUser.id == int(user_id), ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None),
    ).populate_existing()
    # Shared locks: current committed rows, blocked only by concurrent writers. Exclusive locks on
    # role/permission rows shared by every employee serialized unrelated sync batches and callbacks.
    user = (query.with_for_update(read=True) if fresh else query).first()
    if user is None:
        raise PermissionError("员工已停用或不存在")
    if fresh:
        # MySQL locking reads observe current rows instead of an earlier
        # REPEATABLE READ snapshot. Used only at a commit/execution boundary.
        roles = [row[0] for row in db.query(ArkRole.name).join(ArkUserRole, ArkUserRole.role_id == ArkRole.id).filter(ArkUserRole.user_id == user.id).with_for_update(read=True).all()]
        codes = [row[0] for row in db.query(ArkPermission.code).join(ArkRolePermission, ArkRolePermission.permission_id == ArkPermission.id).join(ArkUserRole, ArkUserRole.role_id == ArkRolePermission.role_id).filter(ArkUserRole.user_id == user.id).with_for_update(read=True).all()]
    else:
        roles, codes = get_live_user_authorization(db, user.id)
    if permissions and 'super_admin' not in roles and not set(permissions).intersection(codes):
        raise PermissionError("当前权限不允许此操作")
    return {'sub': str(user.id), 'roles': roles, 'permissions': codes}


def is_manager(actor: dict) -> bool:
    return 'super_admin' in actor['roles'] or 'whatsapp:admin' in actor['permissions']


def owner_enabled(db: Session, account: WhatsAppAccount, *, fresh: bool = False) -> bool:
    try:
        live_actor(db, account.ark_user_id, 'whatsapp:write', fresh=fresh)
    except PermissionError:
        return False
    return account.consent_state == 'active' and account.status not in {
        'paused', 'blocked', 'revoking', 'revoked', 'revoke_pending', 'expired',
    }


def require_body(db: Session, account: WhatsAppAccount, user_id: int, *, crm: bool = False, fresh: bool = False) -> dict:
    actor = live_actor(db, user_id, *(('customer:read', 'customer:read_all', 'customer:admin', 'customer:write') if crm else ('whatsapp:read',)), fresh=fresh)
    owner_query = db.query(ArkUser.id).filter(
        ArkUser.id == account.ark_user_id, ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None),
    )
    owner = (owner_query.with_for_update(read=True) if fresh else owner_query).first()
    if owner is None or account.status in {'revoked', 'revoking', 'revoke_pending', 'paused', 'blocked'}:
        raise PermissionError("账号正文访问已停止")
    # Retained legacy history remains owner-readable; collection still requires
    # a new explicit consent. This exception never grants another employee access.
    legacy_owner = account.provider == 'whatsapp-web.js' and account.consent_state == 'pending'
    if account.consent_state != 'active' and not (legacy_owner and account.ark_user_id == int(user_id)):
        raise PermissionError("账号尚未授权正文访问")
    if crm and not account.crm_shared:
        raise PermissionError("账号尚未授权客户域共享")
    if account.ark_user_id != int(user_id):
        grant_query = db.query(WhatsAppBodyGrant.id).filter(
            WhatsAppBodyGrant.account_uid == account.account_uid,
            WhatsAppBodyGrant.user_id == int(user_id),
            WhatsAppBodyGrant.consent_version == account.consent_version,
        )
        grant = (grant_query.with_for_update() if fresh else grant_query).first()
        if grant is None:
            raise PermissionError("无该账号的正文范围授权")
    return actor


def authorization_snapshot(db: Session, account_uid: str) -> dict:
    # Shared lock: concurrent sync batches also hold a shared lock on this row, so the
    # connector's 5 s callback no longer queues behind a whole batch apply.
    account = db.query(WhatsAppAccount).filter_by(account_uid=account_uid).populate_existing().with_for_update(read=True).first()
    if account is None:
        return {'allowed': False}
    allowed = owner_enabled(db, account, fresh=True)
    # Worker polling makes deactivation sticky: reactivation is an explicit
    # owner action. A read during an ordinary DB outage never changes consent.
    if not allowed and account.consent_state == 'active':
        account = db.query(WhatsAppAccount).filter_by(account_uid=account_uid).populate_existing().with_for_update().first()
        allowed = owner_enabled(db, account, fresh=True)
    if not allowed and account.consent_state == 'active':
        account.consent_state = 'paused'
        account.consent_version += 1
        account.status = 'paused'
        db.commit()
    return {
        'allowed': allowed, 'ark_user_id': account.ark_user_id,
        'provider': account.provider, 'session_generation': account.session_generation,
        'consent_version': account.consent_version, 'crm_shared': account.crm_shared,
    }


def readable_accounts(db: Session, actor_user_id: int, *, crm: bool = False, ai: bool = False):
    """SQL scope for list/evidence queries; metadata admin rights never enter it."""
    grants = select(WhatsAppBodyGrant.account_uid).where(
        WhatsAppBodyGrant.user_id == actor_user_id,
        WhatsAppBodyGrant.consent_version == WhatsAppAccount.consent_version,
    ).correlate(WhatsAppAccount)
    active_users = select(ArkUser.id).where(ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None))
    query = db.query(WhatsAppAccount.account_uid).filter(
        literal(actor_user_id).in_(active_users),
        WhatsAppAccount.ark_user_id.in_(active_users),
        WhatsAppAccount.status.notin_(('revoked', 'revoking', 'revoke_pending', 'paused', 'blocked')),
        or_(WhatsAppAccount.ark_user_id == actor_user_id, WhatsAppAccount.account_uid.in_(grants)),
    )
    if crm:
        query = query.filter(WhatsAppAccount.consent_state == 'active', WhatsAppAccount.crm_shared.is_(True))
    else:
        query = query.filter(or_(WhatsAppAccount.consent_state == 'active', and_(
            WhatsAppAccount.provider == 'whatsapp-web.js', WhatsAppAccount.consent_state == 'pending',
            WhatsAppAccount.ark_user_id == actor_user_id,
        )))
    if ai:
        query = query.filter(WhatsAppAccount.ai_egress_allowed.is_(True))
    return query
