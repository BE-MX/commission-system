"""Durable frozen snapshots and independent, conservative delivery for each poster."""
import asyncio
from contextlib import contextmanager
from datetime import timedelta
from hashlib import sha256
import logging
from threading import Lock

import httpx
from sqlalchemy import or_, text

from app.battle_report.models import BattleReport, BattleReportDelivery, BattleReportMember
from app.battle_report.poster_images import image_url, store_image
from app.battle_report.poster_renderer import render_posters
from app.battle_report.poster_service import build_snapshot, push_ready
from app.core.config import get_settings
from app.core.time import beijing_now, to_beijing_naive
from app.dingtalk.webhook import DingTalkWebhookError, WebhookSender

logger = logging.getLogger(__name__)
_LOCAL_LOCK = Lock()


def due_slot(now):
    now = to_beijing_naive(now)
    if now.hour == 13 and now.minute in (0, 5, 15):
        return "13:00"
    if now.hour == 17 and now.minute in (0, 5, 15):
        return "17:00"
    return None


def eligible(report, now):
    return bool(report and report.poster_push_enabled and report.status == "published"
                and report.visibility == "activity" and report.start_date <= now.date() <= report.end_date)


@contextmanager
def delivery_lock(db, report_id):
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
        name = f"ark_battle_poster_{report_id}"
        acquired = connection.execute(text("SELECT GET_LOCK(:name,0)"), {"name": name}).scalar() == 1
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": name})


def persist(db):
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Battle poster delivery ledger commit failed")
        print("Battle poster delivery ledger commit failed", flush=True)
        raise RuntimeError("海报投递记录保存失败，已停止本次发送") from None


def set_status(db, delivery, kind, status, error=None):
    states = {key: dict(value) for key, value in delivery.deliveries.items()}
    states[kind] = {**states[kind], "status": status, "error": error,
                    "updated_at": beijing_now().isoformat()}
    if status == "sending":
        states[kind]["attempts"] = states[kind].get("attempts", 0) + 1
    delivery.deliveries = states
    persist(db)


def send_slot(db, report_id, now=None, sender=None):
    """Sync scheduler worker; the HTTP sender remains async. Never called by preview."""
    now = to_beijing_naive(now or beijing_now())
    slot = due_slot(now)
    if not slot or not push_ready():
        return {"status": "skipped"}
    with delivery_lock(db, report_id) as acquired:
        if not acquired:
            return {"status": "busy"}
        db.expire_all()
        report = db.get(BattleReport, report_id)
        if not eligible(report, now):
            return {"status": "skipped"}
        settings = get_settings()
        destination = sha256(settings.BATTLE_REPORT_WEBHOOK_URL.encode()).hexdigest()
        delivery = db.query(BattleReportDelivery).filter_by(report_id=report_id, report_date=now.date(), slot=slot).first()
        if delivery is None:
            members = db.query(BattleReportMember).filter_by(report_id=report_id).order_by(BattleReportMember.id).all()
            delivery = BattleReportDelivery(report_id=report_id, report_date=now.date(), slot=slot,
                snapshot=build_snapshot(db, report, members, now), destination_hash=destination,
                deliveries={k: {"status": "pending", "attempts": 0} for k in ("team", "personal")},
                created_at=now, updated_at=now)
            db.add(delivery)
            persist(db)  # Freeze both posters before any rendering or external send.
        if delivery.destination_hash != destination:
            return {"status": "blocked", "reason": "目标群配置已变更，本时段停止重试"}
        pending = []
        for kind, state in delivery.deliveries.items():
            if state["status"] == "sending":
                set_status(db, delivery, kind, "uncertain", "上次发送中断；请人工核对群消息，系统不会自动重发")
            elif state["status"] in ("pending", "failed") and state.get("attempts", 0) < 3:
                pending.append(kind)
        if pending:
            # Render both from the frozen snapshot before the first outgoing message.
            try:
                for kind, data in render_posters(delivery.snapshot, tuple(pending)).items():
                    store_image(delivery.id, kind, data)
            except Exception as exc:
                from app.battle_report.poster_images import PosterBuildError
                if isinstance(exc, ModuleNotFoundError):
                    detail = f"missing module {getattr(exc, 'name', '?')}"
                elif isinstance(exc, PosterBuildError):
                    detail = str(exc)[:120]
                else:
                    detail = type(exc).__name__
                logger.warning("Battle poster render failed: report=%s type=%s detail=%s",
                               report_id, type(exc).__name__, detail)
                print(f"Battle poster render failed: report={report_id} type={type(exc).__name__} detail={detail}", flush=True)
                for kind in pending:
                    set_status(db, delivery, kind, "failed",
                               f"海报生成失败（{detail}），请检查浏览器/依赖运行环境；本时段稍后重试")
                return {"status": "finished", "deliveries": delivery.deliveries}
        notifier = sender or WebhookSender(settings.BATTLE_REPORT_WEBHOOK_URL, settings.BATTLE_REPORT_WEBHOOK_SECRET)
        for kind in pending:
            # expire_all alone keeps MySQL REPEATABLE READ's old transaction snapshot.
            # There are no uncommitted writes here. End it before rereading authorization.
            db.rollback()
            if not eligible(db.get(BattleReport, report_id), to_beijing_naive(beijing_now())):
                break
            set_status(db, delivery, kind, "sending")
            label = "团队" if kind == "team" else "个人"
            # No user-controlled markdown; report name is already safely rendered into PNG.
            title = f"九月百团冲刺·{label}目标完成榜"
            content = f"### {title}\n\n{delivery.report_date} {slot}（北京时间）\n\n![{label}海报]({image_url(delivery, kind)})\n\n[查看完整海报]({image_url(delivery, kind)})"
            try:
                result = asyncio.run(notifier.send_markdown(title, content))
                if result.get("errcode") != 0:
                    raise RuntimeError("Unexpected sender response")
            except Exception as exc:
                definite = isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)) or (isinstance(exc, DingTalkWebhookError) and not exc.delivery_uncertain)
                status = "failed" if definite else "uncertain"
                message = "发送失败，将在本时段重试" if definite else "送达结果不确定，请人工核对群消息；不会自动重发"
                # Never retain/log exception text: network errors may contain webhook credentials.
                logger.warning("Battle poster send %s: report=%s kind=%s type=%s", status, report_id, kind, type(exc).__name__)
                print(f"Battle poster send {status}: report={report_id} kind={kind} type={type(exc).__name__}", flush=True)
                set_status(db, delivery, kind, status, message)
            else:
                # If this commit fails, durable 'sending' becomes uncertain on the next run.
                set_status(db, delivery, kind, "sent")
        return {"status": "finished", "deliveries": delivery.deliveries}


def recover_interrupted(db, now=None):
    """Recover old slots too, including interruption during the final scheduled retry."""
    cutoff = to_beijing_naive(now or beijing_now()) - timedelta(minutes=10)
    candidates = db.query(BattleReportDelivery.id, BattleReportDelivery.report_id).filter(
        BattleReportDelivery.updated_at < cutoff,
        or_(BattleReportDelivery.deliveries["team"]["status"].as_string() == "sending",
            BattleReportDelivery.deliveries["personal"]["status"].as_string() == "sending")).all()
    db.rollback()
    recovered = 0
    for delivery_id, report_id in candidates:
        with delivery_lock(db, report_id) as acquired:
            if not acquired:
                continue  # Never label an active sender as interrupted.
            db.rollback()
            row = db.get(BattleReportDelivery, delivery_id)
            if row is None or row.updated_at >= cutoff:
                continue
            for kind, state in list(row.deliveries.items()):
                if state["status"] == "sending":
                    set_status(db, row, kind, "uncertain", "上次发送中断，请人工核对群消息；不会自动重发")
                    recovered += 1
    return recovered
