"""公共依赖 — get_db 官方定义在 app.core.database，此处仅 re-export 保持旧 import 路径兼容（治理 B-4）。"""

from app.core.database import get_db

__all__ = ["get_db"]
