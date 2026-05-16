"""启动期数据库探活与业务规则加载"""

import logging

from sqlalchemy import text

from app.core.database import engine
from app.core.rule_config import load_order_match_config

logger = logging.getLogger("commission")


def check_database_connection() -> None:
    """启动时探活数据库连接,失败抛异常阻止应用启动"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection OK")
    except Exception as e:
        logger.error(f"Database connection FAILED: {e}")
        raise


def load_business_rules() -> None:
    """加载订单匹配规则配置"""
    try:
        cfg = load_order_match_config()
        logger.info(f"Order match rules loaded: table={cfg['table']}")
    except Exception as e:
        logger.error(f"Failed to load order match rules: {e}")
        raise
