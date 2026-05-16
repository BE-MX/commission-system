"""admin 账号占位密码初始化 + 角色权限种子 (幂等)"""

import logging

from app.core.database import SessionLocal

logger = logging.getLogger("commission")


def seed_admin_and_permissions() -> None:
    """启动时初始化 admin 密码与权限 seed (幂等,失败不阻塞启动)"""
    try:
        from app.auth.service import init_admin_password, seed_role_permissions
        with SessionLocal() as db:
            init_admin_password(db)
            seed_role_permissions(db)
    except Exception as e:
        logger.warning(f"Init admin password skipped: {e}")
