"""方舟洞见 — 定时任务"""

import logging
from datetime import date

from app.core.database import SessionLocal

logger = logging.getLogger("insight.scheduler")


async def generate_industry_daily():
    """定时生成行业情报日报。"""
    db = SessionLocal()
    try:
        from app.insight.service import generate_industry_daily_report

        report = generate_industry_daily_report(db, report_date=date.today())
        logger.info("industry_daily report generated: id=%s date=%s", report.id, report.report_date)
    except Exception:
        logger.exception("industry_daily report generation failed")
    finally:
        db.close()


async def generate_ai_tools():
    """定时生成 AI 工具速递。"""
    db = SessionLocal()
    try:
        from app.insight.service import generate_ai_tools_report

        report = generate_ai_tools_report(db, report_date=date.today())
        logger.info("ai_tools report generated: id=%s date=%s", report.id, report.report_date)
    except Exception:
        logger.exception("ai_tools report generation failed")
    finally:
        db.close()
