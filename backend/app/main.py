"""FastAPI 应用入口"""

import logging
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, TimeoutError as DBTimeoutError

from app.core.config import get_settings
from app.core.database import engine
from app.core.storage.cos import ObjectMissing, StorageError
from app.bootstrap import (
    check_database_connection, load_business_rules, initialize_portal_outbound,
    seed_admin_and_permissions, auto_init_ai_presets,
    seed_asset_dimensions, seed_salary_rules, seed_agent_runtime_profiles,
    seed_whatsapp_translation_glossary,
    mount_uploads, mount_frontend,
    check_pdf_export_resources, check_expo_watermark,
)
from app.routers import register_routers
from app.whatsapp_translation.errors import register_whatsapp_translation_error_handler
from app.mail_outreach.errors import register_mail_outreach_error_handler
from app.customer.pcw_errors import register_pcw_error_handler
from app.portal.errors import register_portal_error_handler
from app.mcp.server import mount_mcp, mcp_session_lifespan
from app.schedulers import start_scheduler, shutdown_scheduler

logger = logging.getLogger("commission")
settings = get_settings()

# 全局 APScheduler 实例 (SCHEDULER_ENABLED=false 时为 None)
_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Register acquired resources immediately and preserve every cleanup error.
    # ExitStack continues unwinding, but implicit exception contexts can lose
    # earlier failures across independent callbacks and SDK task groups.
    cleanup_errors: list[BaseException] = []
    def cleanup(callback, *args):
        try:
            callback(*args)
        except BaseException as error:
            cleanup_errors.append(error)

    try:
        async with AsyncExitStack() as resources:
            resources.callback(cleanup, engine.dispose)
            await resources.enter_async_context(mcp_session_lifespan())
            check_pdf_export_resources()
            check_expo_watermark()
            check_database_connection()
            outbound_mode = initialize_portal_outbound()
            load_business_rules()
            seed_admin_and_permissions()
            seed_asset_dimensions()
            seed_salary_rules()
            seed_agent_runtime_profiles()
            seed_whatsapp_translation_glossary()

            global _scheduler
            scheduler = start_scheduler(outbound_mode=outbound_mode)
            _scheduler = scheduler
            def stop_owned_scheduler():
                global _scheduler
                try:
                    shutdown_scheduler(scheduler)
                finally:
                    if _scheduler is scheduler:
                        _scheduler = None
            resources.callback(cleanup, stop_owned_scheduler)

            auto_init_ai_presets()
            from app.pm.bootstrap import init_pm_module
            init_pm_module()
            from app.core.storage.worker import start_worker, stop_worker
            storage_worker = start_worker()
            resources.callback(cleanup, stop_worker, storage_worker)
            yield
    except BaseException as error:
        if cleanup_errors:
            raise BaseExceptionGroup(
                "Application lifecycle and cleanup failures", [error, *cleanup_errors],
            ) from None
        raise
    else:
        if cleanup_errors:
            raise BaseExceptionGroup("Application cleanup failures", cleanup_errors)


app = FastAPI(
    title="LeShine Ark Platform",
    description="莱莎方舟平台 API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys([*settings.CORS_ALLOW_ORIGINS, settings.WHATSAPP_TRANSLATION_EXTENSION_ORIGIN])),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


register_whatsapp_translation_error_handler(app)
register_mail_outreach_error_handler(app)
register_pcw_error_handler(app)
register_portal_error_handler(app)

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


@app.exception_handler(StorageError)
async def storage_error_handler(request: Request, exc: StorageError):
    status_code = 404 if isinstance(exc, ObjectMissing) else 503
    return JSONResponse(status_code=status_code,
        content={"code": status_code, "message": "文件不存在" if status_code == 404 else "云存储暂时不可用，请稍后重试", "data": None},
        headers={"Cache-Control": "private, no-store", "Retry-After": "10"})


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
mount_mcp(app)


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
