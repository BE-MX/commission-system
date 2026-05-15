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
from app.stock.models import StockDailyReport

logger = logging.getLogger("stock.scheduler")

MAX_INDIVIDUAL_ALERTS = 20
DAILY_REPORT_URL_TEMPLATE = "/stock/daily-report?date={date}"


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
            _push_dingtalk_sync(db, target_date, shortage_skus, warning_skus, summary)
            service.mark_daily_report_pushed(db, target_date)
        except Exception as e:
            logger.error("钉钉推送失败 date=%s err=%s", target_date, e, exc_info=True)

    return rec


def _push_dingtalk_sync(
    db: Session,
    target_date: date,
    shortage_skus: list[dict],
    warning_skus: list[dict],
    summary: dict,
) -> None:
    """同步包装异步钉钉推送(在 scheduler 的事件循环中调用)"""
    import asyncio
    from app.dingtalk.work_notify import get_work_notifier
    from app.utils.shortlink import generate_short_link
    from app.core.config import get_settings

    settings = get_settings()
    recipients = service.get_stock_recipients(db)
    if not recipients:
        logger.warning("没有符合条件的钉钉接收人,跳过推送")
        return

    # 生成短链(指向日报页)
    base = settings.SHORT_LINK_BASE_URL.rstrip("/")
    full_url = f"{base}{DAILY_REPORT_URL_TEMPLATE.format(date=target_date.isoformat())}"
    short_link = generate_short_link(full_url)

    notifier = get_work_notifier()

    # 摘要消息
    summary_md = _build_summary_markdown(target_date, shortage_skus, warning_skus, summary, short_link)
    # 紧缺预警
    alert_messages = _build_shortage_alerts(shortage_skus, short_link)

    async def _send_all():
        # 摘要
        await notifier.send_to_users(recipients, "📦 库存安全日报", summary_md)
        # 逐条/合并预警
        for title, body in alert_messages:
            await notifier.send_to_users(recipients, title, body)

    # 在当前事件循环中执行
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_send_all())
    except RuntimeError:
        # 不在事件循环里, 自己跑一个
        asyncio.run(_send_all())


def _build_summary_markdown(
    target_date: date,
    shortage_skus: list[dict],
    warning_skus: list[dict],
    summary: dict,
    short_link: str,
) -> str:
    """构造日报摘要 Markdown"""
    def line(s):
        return f"- {s.get('product_name','')} {s.get('model','') or ''} · 可用 {int(s.get('enable_count',0))} 件"

    shortage_lines = "\n".join(line(s) for s in shortage_skus[:10]) or "（无）"
    warning_lines = "\n".join(line(s) for s in warning_skus[:10]) or "（无）"
    more_shortage = f"\n... 共 {len(shortage_skus)} 个" if len(shortage_skus) > 10 else ""
    more_warning = f"\n... 共 {len(warning_skus)} 个" if len(warning_skus) > 10 else ""

    return (
        f"## 📦 莱莎方舟 · 库存安全日报 {target_date}\n\n"
        f"**🔴 紧缺（{summary['shortage_count']} 个 SKU）**\n"
        f"{shortage_lines}{more_shortage}\n\n"
        f"**🟡 预警（{summary['warning_count']} 个 SKU）**\n"
        f"{warning_lines}{more_warning}\n\n"
        f"**🟢 充足：{summary['sufficient_count']} 个 SKU**\n\n"
        f"[查看完整日报]({short_link})"
    )


def _build_shortage_alerts(
    shortage_skus: list[dict],
    short_link: str,
) -> list[tuple[str, str]]:
    """构造逐条/合并预警消息列表"""
    if not shortage_skus:
        return []

    if len(shortage_skus) > MAX_INDIVIDUAL_ALERTS:
        title = "⚠️ 库存预警汇总"
        body = (
            f"### ⚠️ 库存预警汇总\n\n"
            f"共 **{len(shortage_skus)} 个 SKU** 低于安全库存,数量较多已合并推送。\n\n"
            f"[查看详细日报]({short_link})"
        )
        return [(title, body)]

    msgs = []
    for s in shortage_skus:
        title = f"⚠️ 库存预警 · {s.get('product_name','')}"
        body = (
            f"### ⚠️ 库存预警\n\n"
            f"**{s.get('product_name','')}** {s.get('model','') or ''}\n\n"
            f"- 当前可用库存: **{int(s.get('enable_count',0))}** 件\n"
            f"- 安全库存阈值: {int(s.get('safety_stock',0))} 件\n"
            f"- 近 30 天日均销量: {s.get('avg_daily_sales_30d',0)} 件/天\n"
            f"- 建议备货量: **{int(s.get('suggested_qty',0))}** 件\n\n"
            f"[查看完整日报]({short_link})"
        )
        msgs.append((title, body))
    return msgs


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
