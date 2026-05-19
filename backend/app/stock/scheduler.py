"""备货管理 — 定时任务 + 日报生成

每日 08:30 触发:
1. 查询全量库存状态
2. 写入 ark_stock_daily_reports(同日已有则更新)
3. 推送钉钉日报摘要(给所有有 stock:read/admin 权限的用户)
4. 紧缺 SKU 逐条预警(超过 20 条合并为汇总)
5. 标记 dingtalk_sent
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.stock import service
from app.stock.daily_report_service import push_daily_report
from app.stock.models import StockDailyReport

logger = logging.getLogger("stock.scheduler")


def _split_skus(items: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """按 status 拆分,并算 summary"""
    shortage = [i for i in items if i["status"] == "shortage"]
    warning = [i for i in items if i["status"] == "warning"]
    sufficient = [i for i in items if i["status"] in ("sufficient", "unset")]
    summary = {
        "shortage_count": len(shortage),
        "warning_count": len(warning),
        "sufficient_count": len(sufficient),
    }
    return shortage, warning, summary


def generate_stock_daily_report_sync(
    db: Session,
    target_date: Optional[date] = None,
    push_dingtalk: bool = True,
) -> StockDailyReport:
    """
    同步入口: 生成日报并(可选)推送钉钉。
    异步 scheduler 入口会把这个跑在线程池里。
    """
    target_date = target_date or date.today()
    logger.info("开始生成库存日报 date=%s push_dingtalk=%s", target_date, push_dingtalk)

    # 1. 查全量状态
    all_items = service.query_all_sku_status(db)
    shortage_skus, warning_skus, summary = _split_skus(all_items)

    # 2. 写库
    rec = service.upsert_daily_report(
        db=db,
        report_date_value=target_date,
        shortage_skus=shortage_skus,
        warning_skus=warning_skus,
        summary=summary,
    )

    logger.info(
        "日报写入完成 date=%s shortage=%d warning=%d sufficient=%d",
        target_date, summary["shortage_count"], summary["warning_count"], summary["sufficient_count"],
    )

    # 3. 推送钉钉
    if push_dingtalk:
        try:
            push_daily_report(db, target_date, shortage_skus, warning_skus, summary)
            service.mark_daily_report_pushed(db, target_date)
        except Exception as e:
            logger.error("钉钉推送失败 date=%s err=%s", target_date, e, exc_info=True)

    return rec


# ── APScheduler 异步入口 ────────────────────────────────
async def generate_stock_daily_report() -> None:
    """APScheduler 调用入口(每天 08:30)"""
    import anyio

    def _run():
        with SessionLocal() as db:
            generate_stock_daily_report_sync(db=db, target_date=date.today(), push_dingtalk=True)

    # 在线程池里跑(同步 SQLAlchemy)
    try:
        await anyio.to_thread.run_sync(_run)
    except Exception as e:
        logger.error("库存日报定时任务失败: %s", e, exc_info=True)
