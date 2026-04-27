"""FastAPI 应用入口"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.core.database import engine
from app.core.rule_config import load_order_match_config
from app.api import (
    employee_router, supervisor_router, customer_router,
    payment_router, commission_router, report_router,
    tracking_router,
)

logger = logging.getLogger("commission")

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


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
    title="LeShine Ark Platform",
    description="莱莎方舟平台 API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": "服务器内部错误", "data": None},
    )


# 注册路由
app.include_router(employee_router, prefix="/api/v1/employee", tags=["员工属性"])
app.include_router(supervisor_router, prefix="/api/v1/supervisor", tags=["主管关系"])
app.include_router(customer_router, prefix="/api/v1/customer", tags=["客户归属"])
app.include_router(payment_router, prefix="/api/v1/payment", tags=["回款同步"])
app.include_router(commission_router, prefix="/api/v1/commission", tags=["提成计算"])
app.include_router(report_router, prefix="/api/v1/report", tags=["报表导出"])
app.include_router(tracking_router, prefix="/api/v1/tracking", tags=["物流跟踪"])


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


# ---------- 生产模式：托管前端 ----------
if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """所有非 /api、/health、/assets 的请求 fallback 到 index.html（SPA 路由）"""
        file = FRONTEND_DIST / full_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")

    logger.info(f"Serving frontend from {FRONTEND_DIST}")
