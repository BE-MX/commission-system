"""FastAPI 应用入口"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.core.database import engine
from app.core.rule_config import load_order_match_config

logger = logging.getLogger("commission")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- 启动 ---
    # 测试数据库连接
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection OK")
    except Exception as e:
        logger.error(f"Database connection FAILED: {e}")
        raise

    # 加载订单匹配规则
    try:
        cfg = load_order_match_config()
        logger.info(f"Order match rules loaded: table={cfg['table']}")
    except Exception as e:
        logger.error(f"Failed to load order match rules: {e}")
        raise

    yield
    # --- 关闭 ---
    engine.dispose()


app = FastAPI(
    title="Commission Management System",
    description="提成管理与计算系统 API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health_check():
    """健康检查"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {e}"

    return {
        "status": "ok",
        "database": db_status,
    }
