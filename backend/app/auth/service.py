"""Auth 业务逻辑"""

from datetime import datetime, timedelta

from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from app.auth.models import ArkUser, ArkLoginLog, ArkRefreshToken
from app.auth.utils import (
    verify_password, create_access_token, generate_refresh_token,
    hash_token, hash_password,
)
from app.core.config import get_settings

settings = get_settings()


def get_user_by_username(db: Session, username: str) -> ArkUser | None:
    """通过用户名查找用户（含 roles + permissions eager load）"""
    return db.query(ArkUser).filter(
        ArkUser.username == username,
        ArkUser.deleted_at.is_(None),
    ).first()


def get_user_roles(user: ArkUser) -> list[str]:
    return [r.name for r in user.roles]


def get_user_permissions(user: ArkUser) -> list[str]:
    """获取用户所有角色下的去重权限列表"""
    perms = set()
    for role in user.roles:
        for perm in role.permissions:
            perms.add(perm.code)
    return sorted(perms)


def check_account_lockout(db: Session, username: str) -> None:
    """30 分钟内连续失败 5 次则锁定"""
    cutoff = datetime.utcnow() - timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
    fail_count = db.query(func.count()).filter(
        ArkLoginLog.username == username,
        ArkLoginLog.status == "failed",
        ArkLoginLog.created_at >= cutoff,
    ).scalar()
    if fail_count >= settings.LOGIN_MAX_FAIL:
        raise AccountLockedException(
            f"账号已锁定，{settings.LOGIN_LOCK_MINUTES}分钟内失败次数过多，请稍后再试"
        )


def record_login_log(
    db: Session,
    username: str,
    status: str,
    ip: str,
    user_agent: str = "",
    user_id: int | None = None,
    fail_reason: str | None = None,
):
    log = ArkLoginLog(
        user_id=user_id,
        username=username,
        ip_address=ip,
        user_agent=user_agent[:500] if user_agent else "",
        status=status,
        fail_reason=fail_reason,
    )
    db.add(log)
    db.commit()


def authenticate_user(
    db: Session,
    username: str,
    password: str,
    ip: str,
    user_agent: str = "",
) -> tuple:
    """
    验证用户，返回 (access_token, refresh_token_plain, user_info_dict)
    失败抛异常
    """
    # 锁定检查
    check_account_lockout(db, username)

    user = get_user_by_username(db, username)

    if not user:
        record_login_log(db, username, "failed", ip, user_agent, fail_reason="用户不存在")
        raise InvalidCredentialsException("用户名或密码错误")

    if not user.is_active:
        record_login_log(db, username, "failed", ip, user_agent, user.id, "账号已禁用")
        raise AccountDisabledException("账号已被禁用，请联系管理员")

    if not verify_password(password, user.password_hash):
        record_login_log(db, username, "failed", ip, user_agent, user.id, "密码错误")
        raise InvalidCredentialsException("用户名或密码错误")

    # 认证成功
    roles = get_user_roles(user)
    permissions = get_user_permissions(user)

    # 生成 Access Token
    at_payload = {
        "sub": str(user.id),
        "username": user.username,
        "roles": roles,
        "permissions": permissions,
        "must_change_password": user.must_change_password,
    }
    access_token = create_access_token(at_payload)

    # 生成 Refresh Token
    rt_plain, rt_hash = generate_refresh_token()
    rt_record = ArkRefreshToken(
        token_hash=rt_hash,
        user_id=user.id,
        device_info=user_agent[:255] if user_agent else "",
        ip_address=ip,
        expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(rt_record)

    # 更新最后登录
    user.last_login_at = datetime.utcnow()
    user.last_login_ip = ip

    # 记录成功日志
    record_login_log(db, username, "success", ip, user_agent, user.id)
    db.commit()

    user_info = {
        "id": user.id,
        "username": user.username,
        "real_name": user.real_name,
        "roles": roles,
        "permissions": permissions,
        "must_change_password": bool(user.must_change_password),
    }

    return access_token, rt_plain, user_info


def init_admin_password(db: Session):
    """启动时检查 admin 密码是否为占位符，若是则生成真实 hash"""
    user = db.query(ArkUser).filter(ArkUser.username == "admin").first()
    if user and (user.password_hash == "__PENDING_HASH__" or not user.password_hash.startswith("$2")):
        import bcrypt as _bcrypt
        hashed = _bcrypt.hashpw(b"Admin@leisa2026", _bcrypt.gensalt(rounds=12)).decode("utf-8")
        user.password_hash = hashed
        db.commit()


def seed_role_permissions(db: Session):
    """启动时确保角色管理相关权限存在（幂等）"""
    from app.auth.models import ArkPermission, ArkRole, ArkRolePermission

    seeds = [
        ("role:read", "system", "read", "查看角色列表"),
        ("role:write", "system", "write", "创建/编辑角色"),
        ("role:delete", "system", "delete", "删除角色"),
    ]
    for code, module, action, label in seeds:
        existing = db.query(ArkPermission).filter(ArkPermission.code == code).first()
        if not existing:
            db.add(ArkPermission(code=code, module=module, action=action, label=label))
    db.flush()

    # 给 admin 角色分配这些权限
    admin_role = db.query(ArkRole).filter(ArkRole.name == "admin").first()
    if admin_role:
        for code, _, _, _ in seeds:
            perm = db.query(ArkPermission).filter(ArkPermission.code == code).first()
            if perm:
                link = db.query(ArkRolePermission).filter(
                    ArkRolePermission.role_id == admin_role.id,
                    ArkRolePermission.permission_id == perm.id,
                ).first()
                if not link:
                    db.add(ArkRolePermission(role_id=admin_role.id, permission_id=perm.id))
    db.commit()


# ── 异常类 ────────────────────────────────────────────
class InvalidCredentialsException(Exception):
    pass


class AccountLockedException(Exception):
    pass


class AccountDisabledException(Exception):
    pass
