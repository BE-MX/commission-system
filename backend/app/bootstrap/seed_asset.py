"""素材管理标签维度种子 (幂等)"""

import logging

from app.core.database import SessionLocal

logger = logging.getLogger("commission")


def seed_asset_dimensions() -> None:
    """启动时初始化素材标签维度种子 (幂等,失败不阻塞启动)"""
    try:
        from app.asset.tag_service import seed_default_dimensions
        with SessionLocal() as db:
            seed_default_dimensions(db)
            logger.info("Asset tag dimensions seeded")
    except Exception as e:
        logger.warning(f"Seed asset dimensions skipped: {e}")
