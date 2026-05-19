"""应用启动期的初始化任务 (DB 探活 / 规则加载 / 数据种子 / 静态文件挂载)"""

from app.bootstrap.database import check_database_connection, load_business_rules
from app.bootstrap.seed_auth import seed_admin_and_permissions
from app.bootstrap.seed_ai import auto_init_ai_presets
from app.bootstrap.seed_asset import seed_asset_dimensions
from app.bootstrap.static_files import mount_uploads, mount_frontend

__all__ = [
    "check_database_connection",
    "load_business_rules",
    "seed_admin_and_permissions",
    "auto_init_ai_presets",
    "seed_asset_dimensions",
    "mount_uploads",
    "mount_frontend",
]
