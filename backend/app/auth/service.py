"""Auth 业务逻辑"""

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.models import ArkUser, ArkLoginLog, ArkRefreshToken
from app.auth.utils import (
    verify_password, create_access_token, generate_refresh_token,
    hash_token,
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
        "avatar_url": user.avatar_url,
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
    """启动时确保全部权限存在（幂等），并给 admin 角色补齐"""
    from app.auth.models import ArkPermission, ArkRole, ArkRolePermission

    seeds = [
        # 人员管理
        ("employee:read",  "employee", "read",   "查看员工属性"),
        ("employee:write", "employee", "write",  "编辑员工属性"),
        # 客户管理
        ("customer:read",  "customer", "read",   "查看客户归属"),
        ("customer:write", "customer", "write",  "编辑客户归属"),
        # 提成管理
        ("commission:read",      "commission", "read",       "查看提成批次"),
        ("commission:write",     "commission", "write",      "管理提成批次"),
        ("commission:self_read", "commission", "self_read",  "查看本人提成"),
        ("payment:read",         "commission", "read",       "查看回款记录"),
        ("payment:write",        "commission", "write",      "同步回款"),
        # 物流跟踪
        ("tracking:read",         "tracking", "read",         "查看物流跟踪（仅本人）"),
        ("tracking:read_all",     "tracking", "read_all",     "查看全部运单"),
        ("tracking:write",        "tracking", "write",        "编辑物流记录"),
        ("tracking:daily_report", "tracking", "daily_report", "查看物流日报"),
        # 设计预约
        ("design:read",    "design", "read",     "查看设计预约"),
        ("design:write",   "design", "write",    "提交/编辑预约"),
        ("design:audit",   "design", "audit",    "审批设计预约"),
        ("design:manage",  "design", "manage",   "设计管理"),
        # 系统管理
        ("user:read",      "system", "read",     "查看用户/角色"),
        ("user:write",     "system", "write",    "创建/编辑用户"),
        ("user:delete",    "system", "delete",   "删除用户"),
        ("role:read",      "system", "read",     "查看角色列表"),
        ("role:write",     "system", "write",    "创建/编辑角色"),
        ("role:delete",    "system", "delete",   "删除角色"),
        # AI 接入
        ("ai:admin",       "ai",     "admin",    "AI 接入管理"),
        ("ai:invoke",      "ai",     "invoke",   "AI 调用权限"),
        # 方舟洞见
        ("insight:read",          "insight", "read",          "查看方舟洞见(行业日报/案例库/周会纪要)"),
        ("insight:internal_read", "insight", "internal_read", "查看内部经营报告 / AI 工具速递"),
        ("insight:write",         "insight", "write",         "上传案例 / 周会纪要"),
        ("insight:admin",         "insight", "admin",         "信源管理 / 重新生成报告"),
        # 备货管理
        ("stock:read",            "stock",   "read",          "查看销量备货一览 / 安全库存 / 日报"),
        ("stock:write",           "stock",   "write",         "设置安全库存 / AI 生成建议"),
        ("stock:admin",           "stock",   "admin",         "手动触发日报生成 / 调试推送"),
        # 生产订单管理
        ("production:read",       "production", "read",       "查看生产订单"),
        ("production:write",      "production", "write",      "创建/编辑生产订单 / 入库录入"),
        ("production:admin",      "production", "admin",      "删除生产订单 / 管理全部订单"),
        # 素材管理
        ("asset:read",            "asset",   "read",          "查看素材库 / 预览 / 下载 / 收藏"),
        ("asset:write",           "asset",   "write",         "上传素材 / 编辑标签 / 版本迭代"),
        ("asset:delete",          "asset",   "delete",        "删除素材"),
        ("asset:admin",           "asset",   "admin",         "标签维度管理 / 权限设置"),
        # 色彩管理
        ("color:read",            "color",   "read",          "查看色板数据库 / 色彩趋势"),
        ("color:write",           "color",   "write",         "编辑色号 / 混合色 / 生成色板图"),
        ("color:admin",           "color",   "admin",         "管理竞品监控 / 趋势数据源 / 色板图任务"),
        # 报表中心（jimureport 集成）
        ("report:read",           "report",  "read",          "查看报表 / 数据大屏"),
        ("report:design",         "report",  "design",        "进入报表设计器 / 编辑报表"),
        ("report:admin",          "report",  "admin",         "管理报表元数据 / 数据源"),
        # 数据概念治理
        ("governance:read",       "governance", "read",       "查看概念定义 / 图谱 / 变更历史"),
        ("governance:write",      "governance", "write",      "创建/编辑概念 / 提交审批 / 添加关联"),
        ("governance:admin",      "governance", "admin",      "审批/废弃/回滚/批量导入/删除关联"),
        # 客户机会台
        ("customer_opportunity:read",   "customer_opportunity", "read",   "查看客户机会（本人）"),
        ("customer_opportunity:write",  "customer_opportunity", "write",  "更新机会状态/添加反馈"),
        ("customer_opportunity:import", "customer_opportunity", "import", "ACCIO 导入询盘"),
        ("customer_opportunity:manage", "customer_opportunity", "manage", "管理全部机会/分配/管理未分配"),
        # 外部账号绑定
        ("external_binding:read",  "external_binding", "read",  "查看外部账号绑定"),
        ("external_binding:write", "external_binding", "write", "创建/删除绑定/管理候选"),
    ]
    for code, module, action, label in seeds:
        existing = db.query(ArkPermission).filter(ArkPermission.code == code).first()
        if not existing:
            db.add(ArkPermission(code=code, module=module, action=action, label=label))
    db.flush()

    # 给 admin 角色补齐所有权限
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


# ── Refresh Token ─────────────────────────────────────

def refresh_access_token(db: Session, refresh_token_plain: str) -> tuple:
    """
    用 refresh_token 换取新的 access_token。
    返回 (new_access_token, user_info_dict)。
    失败抛 InvalidCredentialsException。
    """
    token_hash = hash_token(refresh_token_plain)
    rt_record = (
        db.query(ArkRefreshToken)
        .filter(
            ArkRefreshToken.token_hash == token_hash,
            ArkRefreshToken.revoked_at.is_(None),
        )
        .first()
    )

    if not rt_record:
        raise InvalidCredentialsException("Refresh Token 无效")

    if rt_record.expires_at < datetime.utcnow():
        raise InvalidCredentialsException("Refresh Token 已过期")

    user = db.query(ArkUser).filter(
        ArkUser.id == rt_record.user_id,
        ArkUser.is_active.is_(True),
        ArkUser.deleted_at.is_(None),
    ).first()

    if not user:
        raise InvalidCredentialsException("用户不存在或已禁用")

    roles = get_user_roles(user)
    permissions = get_user_permissions(user)

    at_payload = {
        "sub": str(user.id),
        "username": user.username,
        "roles": roles,
        "permissions": permissions,
        "must_change_password": user.must_change_password,
    }
    access_token = create_access_token(at_payload)

    user_info = {
        "id": user.id,
        "username": user.username,
        "real_name": user.real_name,
        "avatar_url": user.avatar_url,
        "roles": roles,
        "permissions": permissions,
        "must_change_password": bool(user.must_change_password),
    }

    return access_token, user_info


def logout_user(db: Session, refresh_token_plain: str | None) -> None:
    """注销：标记 refresh_token 为已撤销。"""
    if not refresh_token_plain:
        return
    token_hash = hash_token(refresh_token_plain)
    rt_record = (
        db.query(ArkRefreshToken)
        .filter(ArkRefreshToken.token_hash == token_hash)
        .first()
    )
    if rt_record:
        rt_record.revoked_at = datetime.utcnow()
        db.commit()


# ── 异常类 ────────────────────────────────────────────
class InvalidCredentialsException(Exception):
    pass


class AccountLockedException(Exception):
    pass


class AccountDisabledException(Exception):
    pass
