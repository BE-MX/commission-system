"""FastAPI 应用入口"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, TimeoutError as DBTimeoutError

from app.core.config import get_settings
from app.core.database import engine
from app.bootstrap import (
    check_database_connection, load_business_rules,
    seed_admin_and_permissions, auto_init_ai_presets,
    seed_asset_dimensions,
    mount_uploads, mount_frontend,
)
from app.routers import register_routers
from app.schedulers import start_scheduler, shutdown_scheduler

logger = logging.getLogger("commission")
settings = get_settings()

# 全局 APScheduler 实例 (SCHEDULER_ENABLED=false 时为 None)
_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- 启动 ---
    check_database_connection()
    load_business_rules()
    seed_admin_and_permissions()
    seed_asset_dimensions()

    global _scheduler
    _scheduler = start_scheduler()

    auto_init_ai_presets()

    yield
    # --- 关闭 ---
    shutdown_scheduler(_scheduler)
    engine.dispose()


app = FastAPI(
    title="LeShine Ark Platform",
    description="莱莎方舟平台 API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 全局异常处理
@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=400,
        content={"code": 400, "message": str(exc), "data": None},
    )


@app.exception_handler(OperationalError)
@app.exception_handler(DBTimeoutError)
async def db_error_handler(request: Request, exc):
    """数据库连接异常 — 返回具体原因，便于前端提示"""
    logger.error(f"Database error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": "数据库连接失败，请稍后重试", "data": None},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": "服务器内部错误", "data": None},
    )


# 静态文件 & 路由
mount_uploads(app)
register_routers(app)


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


# 生产模式: 托管前端 dist (开发模式下 dist 不存在,该调用直接返回)
mount_frontend(app)
