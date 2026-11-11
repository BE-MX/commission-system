"""统一收录管线：Web、钉钉与候选选择共用持久任务。"""

from __future__ import annotations

from datetime import timedelta
import logging
from urllib.parse import urlsplit
import uuid

from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.time import beijing_now
from app.project_radar.analysis import analyze_target
from app.project_radar.dingtalk_sender import deliver_pending_outbox, enqueue_message
from app.project_radar.fetcher import RadarFetcher
from app.project_radar.models import (
    RadarDialog, RadarIngestJob, RadarSubscription, RadarTarget,
)
from app.project_radar.resolve import resolve_candidates
from app.project_radar.scan import initialize_target
from app.project_radar.service import serialize_subscription, subscribe
from app.project_radar.urls import parse_input

logger = logging.getLogger("commission.project_radar.ingest")


def create_job(db: Session, user_id: int, raw_input: str, *, channel="web", request_key=None, dingtalk_id=None):
    key = request_key or f"{channel}:{uuid.uuid4().hex}"
    existing = db.query(RadarIngestJob).filter(RadarIngestJob.request_key == key).one_or_none()
    if existing:
        return existing
    job = RadarIngestJob(
        request_key=key[:191], user_id=user_id, channel=channel, raw_input=raw_input,
        status="queued", candidates=[], result={}, dingtalk_id=dingtalk_id,
        created_at=beijing_now(), updated_at=beijing_now(),
    )
    db.add(job)
    db.flush()
    return job


def job_dict(job: RadarIngestJob) -> dict:
    return {
        "id": job.id, "status": job.status, "candidates": job.candidates or [],
        "result": job.result or {}, "error": job.error, "retry_count": job.retry_count,
        "created_at": job.created_at.isoformat(sep=" ", timespec="minutes") if job.created_at else None,
    }


def _set_dialog(db: Session, user_id: int, kind: str, *, job_id=None, target_id=None, payload=None, minutes=30):
    dialog = db.query(RadarDialog).filter(RadarDialog.user_id == user_id).one_or_none()
    now = beijing_now()
    if dialog is None:
        dialog = RadarDialog(user_id=user_id, kind=kind, payload={}, expires_at=now + timedelta(minutes=minutes), created_at=now)
        db.add(dialog)
    dialog.kind = kind
    dialog.job_id = job_id
    dialog.target_id = target_id
    dialog.payload = payload or {}
    dialog.expires_at = now + timedelta(minutes=minutes)
    return dialog


def _clear_dialog(db: Session, user_id: int):
    dialog = db.query(RadarDialog).filter(RadarDialog.user_id == user_id).one_or_none()
    if dialog:
        db.delete(dialog)


def _is_clue(url: str) -> bool:
    parsed = urlsplit(url if "://" in url else "https://" + url)
    host = (parsed.hostname or "").lower()
    if host in {"x.com", "twitter.com", "mp.weixin.qq.com"}:
        return True
    return host != "github.com" and bool(parsed.path.strip("/"))


def _ingest_direct(db: Session, job: RadarIngestJob, url: str, parsed: dict, *, source_url=None, fetcher=None):
    subscription = subscribe(
        db, job.user_id, url, channel=job.channel, raw_text=job.raw_input,
        source_url=source_url, tags=parsed["tags"], note=parsed["note"], ingest_job_id=job.id,
    )
    target = db.get(RadarTarget, subscription.target_id)
    if target.last_scanned_at is None and target.kind != "article":
        try:
            fetched = (fetcher or RadarFetcher()).read_target(target)
            initialize_target(db, target, fetched, analyzer=lambda session, row, text: analyze_target(
                session, row, text, user_id=job.user_id,
            ))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Project radar initial read failed target=%s (%s)", target.id, type(exc).__name__)
            print(f"Project radar initial read failed target={target.id} ({type(exc).__name__})", flush=True)
            target.read_state = "limited"
            target.consecutive_failures = 1
            target.last_error = "暂时无法读取正文；可补发项目说明或稍后重试"
            target.last_scanned_at = beijing_now()
    return subscription


def _ingest_article(db: Session, job: RadarIngestJob, url: str, clue: dict, parsed: dict):
    subscription = subscribe(
        db, job.user_id, url, channel=job.channel, raw_text=job.raw_input,
        tags=parsed["tags"], note=parsed["note"], ingest_job_id=job.id,
    )
    target = db.get(RadarTarget, subscription.target_id)
    target.kind = "article"
    target.item_type = "article"
    target.title = str(clue.get("title") or target.title)[:255]
    target.one_liner = (clue.get("text") or "文章已收藏，可补发其中项目链接开始追踪")[:80]
    target.description = (clue.get("text") or "")[:500000]
    target.scan_enabled = False
    target.read_state = "ok"
    target.last_scanned_at = beijing_now()
    return subscription


def _enqueue_result(db: Session, job: RadarIngestJob, items: list[dict], errors: list[str]):
    if job.channel != "dingtalk":
        return
    if items:
        duplicate = all(item["duplicate"] for item in items)
        title = "已在你的雷达里" if duplicate and len(items) == 1 else f"已收录 {len(items)} 项"
        lines = []
        for index, item in enumerate(items, 1):
            lines.append(f"{index}. {item['title']} · {item.get('version') or '无版本'}")
            lines.append(item.get("one_liner") or "待补充")
            if item.get("read_state") != "ok":
                lines.append("读取受限，30 分钟内可直接回复一句话说明。")
        if errors:
            lines.extend(f"失败：{error}" for error in errors)
        lines.append("回复「静默 编号」调整推送，或打开详情查看。")
        enqueue_message(db, job.user_id, f"ingest-result:{job.id}", {
            "title": title, "text": "\n".join(lines), "subscription_id": items[0]["subscription_id"],
        })
    else:
        enqueue_message(db, job.user_id, f"ingest-result:{job.id}", {
            "title": "方舟雷达收录失败", "text": "\n".join(errors) or "没有识别到可收录的链接",
        })


def process_job(db: Session, job: RadarIngestJob, *, fetcher=None, resolver=resolve_candidates):
    claimed = db.execute(sa_update(RadarIngestJob).where(
        RadarIngestJob.id == job.id,
        RadarIngestJob.status.in_(["queued", "failed", "partial"]),
    ).values(
        status="reading", retry_count=RadarIngestJob.retry_count + 1,
        error=None, updated_at=beijing_now(),
    )).rowcount
    db.commit()
    if claimed != 1:
        db.refresh(job)
        return job
    db.refresh(job)
    parsed = parse_input(job.raw_input)
    items, errors, choices = [], [], []
    choice_source = None
    if not parsed["urls"]:
        errors.append("没有识别到链接，请发送 HTTP/HTTPS 地址")
    for raw_url in parsed["urls"]:
        try:
            if _is_clue(raw_url):
                clue = (fetcher or RadarFetcher()).read_clue(raw_url)
                candidates = resolver(db, raw_url, clue, user_id=job.user_id)
                confirmed = [candidate for candidate in candidates if candidate.get("confirmed") and candidate.get("url")]
                if len(confirmed) > 1:
                    for candidate in candidates:
                        if candidate not in choices:
                            choices.append(candidate)
                    choice_source = raw_url
                    continue
                if len(confirmed) == 1:
                    subscription = _ingest_direct(db, job, confirmed[0]["url"], parsed, source_url=raw_url, fetcher=fetcher)
                else:
                    subscription = _ingest_article(db, job, raw_url, clue, parsed)
            else:
                subscription = _ingest_direct(db, job, raw_url, parsed, fetcher=fetcher)
            serialized = serialize_subscription(db, subscription)
            items.append({
                "subscription_id": subscription.id, "duplicate": len(serialized["sources"]) > 1,
                **serialized,
            })
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning("Project radar ingest URL failed job=%s (%s)", job.id, type(exc).__name__)
            print(f"Project radar ingest URL failed job={job.id} ({type(exc).__name__})", flush=True)
            errors.append(f"{raw_url}：{str(exc)[:200]}")
    job = db.get(RadarIngestJob, job.id)
    if choices:
        job.status = "awaiting_choice"
        job.candidates = choices
        job.result = {"items": items, "message": "回复数字选择项目，例如 1 3；回复全部选择全部确认项"}
        _set_dialog(db, job.user_id, "choose", job_id=job.id, payload={"source_url": choice_source})
    else:
        job.status = "completed" if items and not errors else ("partial" if items else "failed")
        job.candidates = []
        job.result = {"items": items, "errors": errors}
        job.error = "\n".join(errors)[:1000] or None
        if items:
            limited = next((item for item in items if item.get("read_state") != "ok"), None)
            if limited:
                _set_dialog(db, job.user_id, "supplement", target_id=limited["target_id"], payload={"subscription_id": limited["subscription_id"]})
            else:
                _set_dialog(db, job.user_id, "card", payload={"subscription_ids": [item["subscription_id"] for item in items]}, minutes=1440)
    job.updated_at = beijing_now()
    if choices:
        if job.channel == "dingtalk":
            lines = ["这篇文章提到多个项目，回复数字收录（如 1 3），或回复全部："]
            for index, candidate in enumerate(choices, 1):
                suffix = "（已校验）" if candidate.get("confirmed") else "（未确认，不可收录）"
                lines.append(f"{index}. {candidate['title']}{suffix}")
            enqueue_message(db, job.user_id, f"ingest-choice:{job.id}", {"title": "请选择项目", "text": "\n".join(lines)})
    else:
        _enqueue_result(db, job, items, errors)
    db.commit()
    return job


def select_candidates(db: Session, user_id: int, selection: str, *, job_id=None, fetcher=None):
    dialog = db.query(RadarDialog).filter(RadarDialog.user_id == user_id, RadarDialog.kind == "choose").one_or_none()
    if dialog is None or (job_id and dialog.job_id != job_id):
        return {"ok": False, "message": "当前没有待选择的项目"}
    if dialog.expires_at < beijing_now():
        db.delete(dialog)
        db.commit()
        return {"ok": False, "message": "选择上下文已失效，请重新发送文章链接"}
    job = db.get(RadarIngestJob, dialog.job_id)
    candidates = job.candidates or []
    if selection.strip() == "全部":
        indices = [index for index, candidate in enumerate(candidates, 1) if candidate.get("confirmed") and candidate.get("url")]
    else:
        try:
            indices = list(dict.fromkeys(int(value) for value in selection.split()))
        except ValueError:
            return {"ok": False, "message": "请回复数字，例如 1 3，或回复全部"}
    if not indices or any(index < 1 or index > len(candidates) for index in indices):
        return {"ok": False, "message": "选择编号超出范围"}
    parsed = parse_input(job.raw_input)
    items = []
    for index in indices:
        candidate = candidates[index - 1]
        if not candidate.get("confirmed") or not candidate.get("url"):
            return {"ok": False, "message": f"第 {index} 项尚未确认，不能自动收录"}
        subscription = _ingest_direct(db, job, candidate["url"], parsed, source_url=(dialog.payload or {}).get("source_url"), fetcher=fetcher)
        items.append({"subscription_id": subscription.id, "duplicate": False, **serialize_subscription(db, subscription)})
    job.status = "completed"
    job.result = {"items": items, "errors": []}
    job.updated_at = beijing_now()
    _clear_dialog(db, user_id)
    _set_dialog(db, user_id, "card", payload={"subscription_ids": [item["subscription_id"] for item in items]}, minutes=1440)
    _enqueue_result(db, job, items, [])
    db.commit()
    return {"ok": True, "items": items, "message": f"已收录 {len(items)} 项"}


def supplement_target(db: Session, user_id: int, text: str):
    dialog = db.query(RadarDialog).filter(RadarDialog.user_id == user_id, RadarDialog.kind == "supplement").one_or_none()
    if dialog is None:
        return {"ok": False, "message": "当前没有待补充的项目"}
    if dialog.expires_at < beijing_now():
        db.delete(dialog)
        db.commit()
        return {"ok": False, "message": "补充上下文已失效"}
    target = db.get(RadarTarget, dialog.target_id)
    target.description = "\n".join(filter(None, [target.description or "", "用户补充：" + text.strip()]))[:500000]
    analyze_target(db, target, target.description, user_id=user_id)
    target.read_state = "ok"
    target.last_error = None
    subscription = db.query(RadarSubscription).filter_by(user_id=user_id, target_id=target.id).first()
    subscription.remark = "\n".join(filter(None, [subscription.remark or "", text.strip()]))
    _clear_dialog(db, user_id)
    _set_dialog(db, user_id, "card", payload={"subscription_ids": [subscription.id]}, minutes=1440)
    enqueue_message(db, user_id, f"supplement:{dialog.id}:{beijing_now().timestamp()}", {
        "title": "补充已保存", "text": f"{target.title}\n{target.one_liner}", "subscription_id": subscription.id,
    })
    db.commit()
    return {"ok": True, "message": "已补充并重新分析", "subscription_id": subscription.id}


def run_job_async(job_id: int):
    with SessionLocal() as db:
        job = db.get(RadarIngestJob, job_id)
        if job is None:
            return
        try:
            process_job(db, job)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning("Project radar async job failed id=%s (%s)", job.id, type(exc).__name__)
            print(f"Project radar async job failed id={job.id} ({type(exc).__name__})", flush=True)
            job = db.get(RadarIngestJob, job_id)
            job.status = "failed"
            job.error = "收录任务失败，将由调度器自动重试"
            job.updated_at = beijing_now()
            db.commit()
            return
        if job.channel == "dingtalk":
            try:
                deliver_pending_outbox(db)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Project radar result delivery failed id=%s (%s)", job.id, type(exc).__name__)
                print(f"Project radar result delivery failed id={job.id} ({type(exc).__name__})", flush=True)


def retry_ingest_jobs():
    with SessionLocal() as db:
        threshold = beijing_now() - timedelta(minutes=10)
        jobs = db.query(RadarIngestJob).filter(
            RadarIngestJob.retry_count < 5,
            ((RadarIngestJob.status.in_(["queued", "failed", "partial"])) |
             ((RadarIngestJob.status == "reading") & (RadarIngestJob.updated_at < threshold))),
        ).order_by(RadarIngestJob.created_at).limit(20).all()
        for job in jobs:
            job.status = "failed"
            db.commit()
            try:
                process_job(db, job)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                logger.warning("Project radar scheduled retry failed id=%s (%s)", job.id, type(exc).__name__)
                print(f"Project radar scheduled retry failed id={job.id} ({type(exc).__name__})", flush=True)
        if jobs:
            deliver_pending_outbox(db)
        return len(jobs)


def reanalyze_subscription_async(user_id: int, subscription_id: int):
    with SessionLocal() as db:
        subscription = db.query(RadarSubscription).filter_by(
            id=subscription_id, user_id=user_id, removed_at=None,
        ).one_or_none()
        if subscription is None:
            return
        target = db.get(RadarTarget, subscription.target_id)
        try:
            fetched = RadarFetcher().read_target(target)
            initialize_target(db, target, fetched, analyzer=lambda session, row, text: analyze_target(
                session, row, text, user_id=user_id,
            ))
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning("Project radar reanalyze failed subscription=%s (%s)", subscription_id, type(exc).__name__)
            print(f"Project radar reanalyze failed subscription={subscription_id} ({type(exc).__name__})", flush=True)
