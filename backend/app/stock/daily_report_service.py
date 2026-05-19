"""备货管理 — 安全库存日报 (写入 / 查询 / 推送标记 / 接收人列表)"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.stock.models import StockDailyReport


def upsert_daily_report(
    db: Session,
    report_date_value: date,
    shortage_skus: list[dict],
    warning_skus: list[dict],
    summary: dict,
) -> StockDailyReport:
    """写入或更新当日日报。"""
    existing = (
        db.query(StockDailyReport)
        .filter(StockDailyReport.report_date == report_date_value)
        .first()
    )
    if existing:
        existing.shortage_count = summary.get("shortage_count", 0)
        existing.warning_count = summary.get("warning_count", 0)
        existing.sufficient_count = summary.get("sufficient_count", 0)
        existing.shortage_skus = _serialize_skus(shortage_skus)
        existing.warning_skus = _serialize_skus(warning_skus)
        db.commit()
        return existing

    rec = StockDailyReport(
        report_date=report_date_value,
        shortage_count=summary.get("shortage_count", 0),
        warning_count=summary.get("warning_count", 0),
        sufficient_count=summary.get("sufficient_count", 0),
        shortage_skus=_serialize_skus(shortage_skus),
        warning_skus=_serialize_skus(warning_skus),
        dingtalk_sent=0,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def _serialize_skus(skus: list[dict]) -> list[dict]:
    """提取日报需要的字段精简存库"""
    keep = ["product_id", "product_name", "model", "enable_count",
            "safety_stock", "avg_daily_sales_30d", "suggested_qty"]
    return [{k: it.get(k) for k in keep if k in it} for it in skus]


def get_daily_report(db: Session, report_date_value: Optional[date] = None) -> Optional[dict]:
    """
    获取日报。report_date=None 时取最新一条。
    返回 dict 或 None。
    """
    q = db.query(StockDailyReport)
    if report_date_value:
        rec = q.filter(StockDailyReport.report_date == report_date_value).first()
    else:
        rec = q.order_by(StockDailyReport.report_date.desc()).first()

    if not rec:
        return None

    return {
        "id": rec.id,
        "report_date": rec.report_date.isoformat(),
        "shortage_count": rec.shortage_count,
        "warning_count": rec.warning_count,
        "sufficient_count": rec.sufficient_count,
        "shortage_skus": rec.shortage_skus or [],
        "warning_skus": rec.warning_skus or [],
        "dingtalk_sent": bool(rec.dingtalk_sent),
        "sent_at": rec.sent_at.isoformat() if rec.sent_at else None,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


def mark_daily_report_pushed(db: Session, report_date_value: date) -> None:
    """标记钉钉已推送"""
    rec = (
        db.query(StockDailyReport)
        .filter(StockDailyReport.report_date == report_date_value)
        .first()
    )
    if rec:
        rec.dingtalk_sent = 1
        rec.sent_at = datetime.utcnow()
        db.commit()


def get_stock_recipients(db: Session) -> list[str]:
    """
    返回需要接收库存日报的钉钉 user_id 列表。
    口径: 拥有 stock:read 或 stock:admin 权限的活跃用户(含 super_admin)。
    """
    sql = """
        SELECT DISTINCT u.dingtalk_id
        FROM ark_users u
        LEFT JOIN ark_user_roles ur ON ur.user_id = u.id
        LEFT JOIN ark_roles r       ON r.id = ur.role_id
        LEFT JOIN ark_role_permissions rp ON rp.role_id = r.id
        LEFT JOIN ark_permissions p ON p.id = rp.permission_id
        WHERE u.is_active = 1
          AND u.dingtalk_id IS NOT NULL
          AND u.dingtalk_id <> ''
          AND (
              r.name = 'super_admin'
              OR p.code IN ('stock:read', 'stock:admin')
          )
    """
    rows = db.execute(text(sql)).all()
    return [str(r[0]) for r in rows if r[0]]


# ── 钉钉推送 ────────────────────────────────────────────

MAX_INDIVIDUAL_ALERTS = 20
DAILY_REPORT_URL_TEMPLATE = "/stock/daily-report?date={date}"


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


def push_daily_report(
    db: Session,
    target_date: date,
    shortage_skus: list[dict],
    warning_skus: list[dict],
    summary: dict,
) -> None:
    """同步包装异步钉钉推送。在 scheduler 或 FastAPI 端点中调用。"""
    import asyncio
    import logging

    from app.dingtalk.work_notify import get_work_notifier
    from app.utils.shortlink import generate_short_link
    from app.core.config import get_settings

    logger = logging.getLogger("stock.daily_report")
    settings = get_settings()
    recipients = get_stock_recipients(db)
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
