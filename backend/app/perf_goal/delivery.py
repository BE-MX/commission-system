"""投递台账状态机：pending→sending→sent/failed/uncertain，仿战报海报投递。

- 工作通知优先；未启用或未绑定 dingtalk_id 降级为群 webhook @（channel=webhook_at 即降级标记）。
- failed 由 09:05/09:15 补发 job 重试（attempts<3）；uncertain 绝不自动重发，需人工核对。
- 错误信息不落异常原文（可能含 webhook 凭据），只落确定性中文描述。
"""
import asyncio
import logging
from contextlib import contextmanager
from threading import Lock

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import beijing_now
from app.dingtalk.webhook import DingTalkWebhookError, WebhookSender
from app.perf_goal.dingtalk_worknotice import (PerfWorknoticeClient, WorknoticeError,
                                               build_client, worknotice_configured)
from app.perf_goal.models import PerfReport, PerfReportDelivery

logger = logging.getLogger(__name__)
_LOCAL_LOCK = Lock()
MAX_ATTEMPTS = 3


@contextmanager
def push_lock(db: Session):
    engine = db.get_bind()
    if engine.dialect.name != "mysql":
        acquired = _LOCAL_LOCK.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                _LOCAL_LOCK.release()
        return
    with engine.connect() as connection:
        name = "ark_perf_report_push"
        acquired = connection.execute(text("SELECT GET_LOCK(:name,0)"), {"name": name}).scalar() == 1
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": name})


def persist(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Perf report delivery ledger commit failed")
        print("Perf report delivery ledger commit failed", flush=True)
        raise RuntimeError("投递记录保存失败，已停止本次发送") from None


def choose_channel(config: dict, recipient: dict, settings=None) -> tuple[str, str, bool]:
    """(channel, destination, degraded)：degraded=True 表示工作通知不可用降级为 webhook @。"""
    settings = settings or get_settings()
    mode = config.get("delivery_channel_mode") or "worknotice_first"
    dingtalk_id = (recipient.get("dingtalk_id") or "").strip()
    if mode == "worknotice_first" and worknotice_configured(settings) and dingtalk_id:
        return "worknotice", dingtalk_id, False
    destination = recipient.get("phone") or recipient.get("name") or str(recipient.get("ark_user_id"))
    return "webhook_at", destination, mode != "webhook_only"


def ensure_delivery(db: Session, report: PerfReport, recipient: dict, config: dict) -> PerfReportDelivery:
    row = (db.query(PerfReportDelivery)
           .filter(PerfReportDelivery.report_id == report.id)
           .order_by(PerfReportDelivery.id).first())
    if row is not None:
        return row
    channel, destination, _degraded = choose_channel(config, recipient)
    row = PerfReportDelivery(report_id=report.id, channel=channel, destination=destination,
                             status="pending", attempts=0)
    db.add(row)
    persist(db)
    db.refresh(row)
    return row


def _title(report: PerfReport, scope_name: str) -> str:
    return f"{scope_name}·绩效报告 {report.slot.isoformat()}"


def _send(row: PerfReportDelivery, report: PerfReport, recipient: dict, title: str,
          worknotice_client: PerfWorknoticeClient | None,
          webhook_sender: WebhookSender | None) -> None:
    if row.channel == "worknotice":
        client = worknotice_client or build_client()
        client.send_markdown([row.destination], title, report.content_md or "")
        return
    sender = webhook_sender
    if sender is None:
        settings = get_settings()
        sender = WebhookSender(settings.PERF_REPORT_WEBHOOK_URL, settings.PERF_REPORT_WEBHOOK_SECRET)
    at_mobiles = [row.destination] if row.destination.isdigit() and len(row.destination) == 11 else []
    mention = "" if at_mobiles else f"@{recipient.get('name', '')} "
    asyncio.run(sender.send_markdown(title, f"{mention}\n\n{report.content_md or ''}",
                                     at_mobiles=at_mobiles))


def deliver_report(db: Session, report: PerfReport, recipient: dict, scope_name: str,
                   worknotice_client: PerfWorknoticeClient | None = None,
                   webhook_sender: WebhookSender | None = None) -> PerfReportDelivery | None:
    """Deliver one report's ledger row; never raises on send failure."""
    from app.perf_goal.config_store import load_config
    config = load_config(db)
    row = ensure_delivery(db, report, recipient, config)
    if row.status == "sending":
        row.status = "uncertain"
        row.last_error = "上次发送中断；请人工核对后手工补发，系统不会自动重发"
        persist(db)
        return row
    if row.status in ("sent", "uncertain") or row.attempts >= MAX_ATTEMPTS:
        return row
    title = _title(report, scope_name)
    row.status = "sending"
    row.attempts += 1
    row.last_error = None
    persist(db)
    try:
        _send(row, report, recipient, title, worknotice_client, webhook_sender)
    except Exception as exc:
        definite = (isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))
                    or (isinstance(exc, (WorknoticeError, DingTalkWebhookError)) and not exc.delivery_uncertain)
                    or isinstance(exc, RuntimeError) and not isinstance(exc, (WorknoticeError, DingTalkWebhookError)))
        row.status = "failed" if definite else "uncertain"
        row.last_error = ("发送失败，将在下一补发窗口重试" if definite
                          else "送达结果不确定，请人工核对；不会自动重发")
        logger.warning("Perf report send %s: report=%s channel=%s type=%s",
                       row.status, report.id, row.channel, type(exc).__name__)
        print(f"Perf report send {row.status}: report={report.id} channel={row.channel} "
              f"type={type(exc).__name__}", flush=True)
        persist(db)
        return row
    row.status = "sent"
    row.sent_at = beijing_now()
    persist(db)
    return row


def slot_counts(db: Session, slots: int = 6) -> list[dict]:
    """最近若干触发日的台账汇总：total/sent/failed/degraded。"""
    rows = (db.query(PerfReport).order_by(PerfReport.slot.desc(), PerfReport.id.desc())
            .limit(slots * 60).all())
    grouped: dict = {}
    for report in rows:
        grouped.setdefault(report.slot, []).append(report)
    result = []
    for slot in sorted(grouped, reverse=True)[:slots]:
        reports = grouped[slot]
        report_ids = [r.id for r in reports]
        deliveries = (db.query(PerfReportDelivery)
                      .filter(PerfReportDelivery.report_id.in_(report_ids or [-1])).all())
        result.append({
            "slot": slot.isoformat(),
            "total": len(reports),
            "sent": sum(1 for d in deliveries if d.status == "sent"),
            "failed": sum(1 for d in deliveries if d.status in ("failed", "uncertain")),
            "degraded": sum(1 for d in deliveries if d.channel == "webhook_at"),
        })
    return result
