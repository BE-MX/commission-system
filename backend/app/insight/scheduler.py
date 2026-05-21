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


async def generate_intelligence_overview():
    """定时生成行业情报速览 — 遍历启用的 schedule_rules 执行。"""
    db = SessionLocal()
    try:
        from app.insight.schedule_service import list_rules, update_last_run
        from app.insight.intelligence_service import generate_intelligence_report
        from app.insight.schemas import IntelligenceReportGenerate

        rules = list_rules(db, is_active=True)
        for rule in rules:
            try:
                config = rule.config_json or {}
                gen_config = IntelligenceReportGenerate(
                    report_title=config.get("report_title"),
                    date_range_start=config.get("date_range_start", date.today()),
                    date_range_end=config.get("date_range_end", date.today()),
                    mode=config.get("mode", "rule_based"),
                    min_credibility_score=config.get("min_credibility_score", 3),
                    source_types=config.get("source_types"),
                    item_types=config.get("item_types"),
                    include_featured_only=config.get("include_featured_only", False),
                    max_items_total=config.get("max_items_total", 30),
                    competitor_filter=config.get("competitor_filter"),
                    content_focus=config.get("content_focus"),
                    output_language=config.get("output_language", "zh-CN"),
                    report_depth=config.get("report_depth", "standard"),
                )
                report = generate_intelligence_report(db, gen_config)
                update_last_run(db, rule.id)
                logger.info("intelligence_overview generated: id=%s rule=%s", report.id, rule.rule_name)
            except Exception:
                logger.exception("intelligence_overview failed for rule id=%s", rule.id)
    except Exception:
        logger.exception("intelligence_overview batch generation failed")
    finally:
        db.close()
