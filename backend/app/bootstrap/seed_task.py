"""任务中心启动种子：默认模块（幂等）+ 导航清单同步（仅 TASK_MODULE_SYNC_ENABLED 环境）。失败不阻塞启动。"""
import logging

from app.bootstrap.static_files import FRONTEND_DIST
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.task import module_service

logger = logging.getLogger("commission")


def seed_task_modules() -> None:
    try:
        with SessionLocal() as db:
            module_service.seed_default_modules(db)
            if get_settings().TASK_MODULE_SYNC_ENABLED:
                manifest = module_service.load_manifest(FRONTEND_DIST / "nav-manifest.json")
                if manifest is None:
                    print("[task] nav-manifest.json missing, module registry kept", flush=True)
                else:
                    result = module_service.sync_nav_manifest(db, manifest)
                    print(f"[task] nav modules synced: {result}", flush=True)
            db.commit()
    except Exception as exc:
        logger.warning("task module seed skipped: %s", exc)
        print(f"[task] module seed skipped: {exc}", flush=True)
