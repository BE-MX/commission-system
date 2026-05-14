"""FastAPI 应用入口"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, TimeoutError as DBTimeoutError

from app.core.database import engine
from app.core.database import SessionLocal
from app.core.rule_config import load_order_match_config
from app.api import (
    employee_router, supervisor_router, customer_router,
    payment_router, commission_router, report_router,
    tracking_router,
)
from app.design.router import router as design_router
from app.auth.router import router as auth_router
from app.auth.admin_router import router as admin_router
from app.dingtalk.router import router as dingtalk_router
from app.dingtalk.callback import router as dingtalk_callback_router
from app.api.short_link import router as short_link_router
from app.system.router import router as system_router
from app.ai.router import router as ai_router
from app.insight.router import router as insight_router

logger = logging.getLogger("commission")

# 全局 APScheduler 实例
_scheduler: AsyncIOScheduler | None = None

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

    # 初始化 admin 密码（如果为占位符）
    try:
        from app.auth.service import init_admin_password, seed_role_permissions
        with SessionLocal() as db:
            init_admin_password(db)
            seed_role_permissions(db)
    except Exception as e:
        logger.warning(f"Init admin password skipped: {e}")

    # 启动 APScheduler 定时任务
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

    from app.design.scheduler import check_today_shoot_reminders
    from app.services.tracking_daily_report import generate_daily_reports
    from app.services.staging_service import scan_staging

    async def _scan_staging_job():
        with SessionLocal() as db:
            await scan_staging(db)

    _scheduler.add_job(
        check_today_shoot_reminders,
        trigger="cron",
        hour=8, minute=30,
        id="design_shoot_reminder",
        replace_existing=True,
    )
    _scheduler.add_job(
        generate_daily_reports,
        trigger="cron",
        hour=8, minute=30,
        id="shipping_daily_report",
        replace_existing=True,
    )
    _scheduler.add_job(
        _scan_staging_job,
        trigger="interval",
        minutes=2,
        id="staging_scan",
        replace_existing=True,
    )

    from app.insight.scheduler import generate_industry_daily, generate_ai_tools

    _scheduler.add_job(
        generate_industry_daily,
        trigger="cron",
        hour=8, minute=30,
        id="insight_industry_daily",
        replace_existing=True,
    )
    _scheduler.add_job(
        generate_ai_tools,
        trigger="cron",
        hour=8, minute=35,
        id="insight_ai_tools",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("APScheduler started with %s jobs", len(_scheduler.get_jobs()))

    # 自动初始化 waybill_ocr AI preset（如需要）
    try:
        from app.ai.models import AiProvider, AiPreset
        with SessionLocal() as db:
            existing = (
                db.query(AiPreset)
                .filter(AiPreset.preset_name == "waybill_ocr", AiPreset.deleted_at.is_(None))
                .first()
            )
            if not existing:
                provider = (
                    db.query(AiProvider)
                    .filter(AiProvider.is_enabled.is_(True), AiProvider.deleted_at.is_(None))
                    .first()
                )
                if provider:
                    first_preset = (
                        db.query(AiPreset)
                        .filter(AiPreset.provider_id == provider.id, AiPreset.deleted_at.is_(None))
                        .first()
                    )
                    model = first_preset.model if first_preset else "gpt-4o"
                    preset = AiPreset(
                        preset_name="waybill_ocr",
                        provider_id=provider.id,
                        model=model,
                        system_prompt=(
                            "你是一个专业的国际物流运单信息提取助手。\n\n"
                            "你的任务是从用户上传的运单图片中提取关键物流字段。"
                            "图片可能来自手机拍摄，存在以下常见问题：光线不均匀、角度倾斜（最多30度）、"
                            "部分字段被手指或物品遮挡、图片模糊或噪点较多。请尽力识别，不确定时宁可返回 null，不要猜测。\n\n"
                            "【输出格式】\n"
                            '必须返回合法的 JSON，不得包含任何 Markdown 代码块标记、解释文字或其他内容。格式如下：\n'
                            '{\n  "waybill_no": "运单号字符串或 null",\n'
                            '  "carrier": "FedEx 或 DHL 或 UPS 或 未知",\n'
                            '  "recipient_name": "收件人姓名或 null",\n'
                            '  "recipient_country": "收件国家（中文名称）或 null",\n'
                            '  "ship_date": "YYYY-MM-DD 格式或 null"\n}\n\n'
                            "【字段提取规则】\n"
                            '1. waybill_no：提取图片上最显眼的条形码下方数字，或标注为"Tracking Number"/"Waybill No"/"运单号"的字符串。去除空格和连字符。\n'
                            '2. carrier：优先根据运单外观（FedEx紫橙色/DHL黄色/UPS深棕色）和Logo判断；无法判断时根据运单号格式辅助判断。\n'
                            '3. recipient_name：提取标注为"To:"/"Deliver To"/"收件人"/"Recipient"区域的人名。仅提取姓名，不含公司名。\n'
                            '4. recipient_country：提取收件地址中的国家，统一转换为中文名称（如"United States"→"美国"，"Germany"→"德国"）。\n'
                            '5. ship_date：提取标注为"Ship Date"/"Date"/"发件日期"的日期，格式统一为 YYYY-MM-DD。若只有月和日则补充当前年份。\n\n'
                            "【特殊情况处理】\n"
                            '- 若图片内容完全无法识别（非运单图片、全黑/全白），返回所有字段均为 null，并额外添加字段 "error": "非运单图片或图片质量过低"\n'
                            '- 若运单号识别到多个候选，选择最长且格式最规范的一个\n'
                            '- 不要返回条形码本身，只返回数字/字母字符串'
                        ),
                        parameters={"temperature": 0.1, "max_tokens": 512},
                        description="运单图片 OCR 识别",
                        is_enabled=True,
                    )
                    db.add(preset)
                    db.commit()
                    logger.info("Auto-created waybill_ocr preset with provider=%s model=%s", provider.name, model)
                else:
                    logger.warning("No active AI provider found, waybill_ocr preset not auto-created")
    except Exception as e:
        logger.warning("Auto-init waybill_ocr preset skipped: %s", e)

    # 自动初始化行业日报 AI 整理 preset
    try:
        from app.ai.models import AiProvider as _AP, AiPreset as _APr
        with SessionLocal() as db:
            existing = (
                db.query(_APr)
                .filter(_APr.preset_name == "insight_daily_organize", _APr.deleted_at.is_(None))
                .first()
            )
            if not existing:
                # 优先选 MIMO，其次第一个可用 provider
                provider = (
                    db.query(_AP)
                    .filter(_AP.is_enabled.is_(True), _AP.deleted_at.is_(None), _AP.name == "MIMO")
                    .first()
                ) or (
                    db.query(_AP)
                    .filter(_AP.is_enabled.is_(True), _AP.deleted_at.is_(None))
                    .first()
                )
                if provider:
                    first_preset = (
                        db.query(_APr)
                        .filter(_APr.provider_id == provider.id, _APr.deleted_at.is_(None))
                        .first()
                    )
                    model = first_preset.model if first_preset else "gpt-4o"
                    preset = _APr(
                        preset_name="insight_daily_organize",
                        provider_id=provider.id,
                        model=model,
                        system_prompt=(
                            "你是发制品行业的市场情报分析师。"
                            "用户会提供一组从外部信源抓取的行业新闻/趋势/竞品动态原始条目。\n\n"
                            "请将这些条目整理为以下 JSON 对象（只输出 JSON，不要其他文字）：\n\n"
                            '{\n'
                            '  "quick_overview": ["条目1要点（20字以内）", ...],\n'
                            '  "color_style_trends": "一段话总结今日发色/发型相关趋势（100字以内，无则空串）",\n'
                            '  "trend_keywords": ["关键词1", "关键词2"],\n'
                            '  "amazon_hot": [{"rank": 1, "name": "商品名", "change": "NEW/+2/-1", "reason": "简析"}],\n'
                            '  "competitor_updates": [{"source": "信源名", "summary": "摘要（60字）", "url": "链接"}],\n'
                            '  "supply_chain": "一段话总结供应链/原材料动态（80字以内，无则空串）"\n'
                            '}\n\n'
                            "规则：\n"
                            "- 与发制品无关的条目直接忽略\n"
                            "- 没有数据的板块返回空数组或空字符串\n"
                            "- amazon_hot 的 change 用 +/-数字 或 NEW 表示\n"
                            "- 不要编造信息"
                        ),
                        parameters={"temperature": 0.3, "max_tokens": 8192},
                        description="行业情报日报：AI 整理信源数据为 5 个板块",
                        is_enabled=True,
                    )
                    db.add(preset)
                    db.commit()
                    logger.info("Auto-created insight_daily_organize preset with provider=%s model=%s", provider.name, model)
                else:
                    logger.warning("No active AI provider found, insight_daily_organize preset not auto-created")
    except Exception as e:
        logger.warning("Auto-init insight_daily_organize preset skipped: %s", e)

    yield
    # --- 关闭 ---
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler shutdown")
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
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:8000"],
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


# 静态文件：上传的头像
UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
if UPLOADS_DIR.is_dir():
    app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

# 注册路由
app.include_router(auth_router, prefix="/api/auth", tags=["认证"])
app.include_router(admin_router, prefix="/api/auth", tags=["用户角色管理"])
app.include_router(employee_router, prefix="/api/v1/employee", tags=["员工属性"])
app.include_router(supervisor_router, prefix="/api/v1/supervisor", tags=["主管关系"])
app.include_router(customer_router, prefix="/api/v1/customer", tags=["客户归属"])
app.include_router(payment_router, prefix="/api/v1/payment", tags=["回款同步"])
app.include_router(commission_router, prefix="/api/v1/commission", tags=["提成计算"])
app.include_router(report_router, prefix="/api/v1/report", tags=["报表导出"])
app.include_router(tracking_router, prefix="/api/v1/tracking", tags=["物流跟踪"])
app.include_router(design_router, prefix="/api/design", tags=["设计预约"])
app.include_router(dingtalk_router, prefix="/api/dingtalk", tags=["钉钉集成"])
app.include_router(dingtalk_callback_router, prefix="/api", tags=["钉钉回调"])
app.include_router(short_link_router, tags=["短链接"])
app.include_router(system_router, prefix="/api/system", tags=["系统字典"])
app.include_router(ai_router, prefix="/api/ai", tags=["AI 接入"])
app.include_router(insight_router, prefix="/api/insight", tags=["方舟洞见"])


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
        if full_path.startswith("api/"):
            return JSONResponse(
                status_code=404,
                content={"code": 404, "message": "API not found", "data": None},
            )
        file = FRONTEND_DIST / full_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")

    logger.info(f"Serving frontend from {FRONTEND_DIST}")
