"""项目雷达个人订阅与查询服务。"""

from __future__ import annotations

from datetime import timedelta
import hashlib
from urllib.parse import urlsplit

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.project_radar.models import (
    RadarSource, RadarSubscription, RadarTarget, RadarUpdate,
)
from app.project_radar.urls import canonicalize_url

_WATCH_BY_STATUS = {"trying": "key", "adopted": "adopted", "dropped": "silent"}
_LOCKED_FIELDS = {"title", "item_type", "one_liner", "description", "ark_modules"}


def _owned(db: Session, user_id: int, subscription_id: int) -> RadarSubscription:
    subscription = db.query(RadarSubscription).filter(
        RadarSubscription.id == subscription_id,
        RadarSubscription.user_id == user_id,
        RadarSubscription.removed_at.is_(None),
    ).one_or_none()
    if subscription is None:
        raise ValueError("项目不存在或不属于你")
    return subscription


def _sync_target_scan_state(db: Session, target_id: int) -> None:
    target = db.get(RadarTarget, target_id)
    if target is None:
        return
    active = db.query(RadarSubscription.id).filter(
        RadarSubscription.target_id == target_id,
        RadarSubscription.removed_at.is_(None),
        RadarSubscription.status != "dropped",
    ).first()
    target.scan_enabled = active is not None


def subscribe(
    db: Session,
    user_id: int,
    raw_url: str,
    *,
    channel: str = "web",
    raw_text: str = "",
    source_url: str | None = None,
    tags: list[str] | None = None,
    note: str = "",
    validator=None,
    ingest_job_id: int | None = None,
) -> RadarSubscription:
    canonical = canonicalize_url(raw_url)
    if validator is None:
        from app.mcp.public_web_tools import _validate_public_url
        validator = _validate_public_url
    try:
        validator(canonical)
    except (ValueError, TypeError) as exc:
        raise ValueError("该地址不允许访问") from exc

    url_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    target = db.query(RadarTarget).filter(RadarTarget.url_hash == url_hash).one_or_none()
    now = beijing_now()
    if target is None:
        parsed = urlsplit(canonical)
        kind = "repo" if parsed.hostname == "github.com" else "website"
        title = parsed.path.rstrip("/").split("/")[-1] if kind == "repo" else (parsed.hostname or canonical)
        target = RadarTarget(
            canonical_url=canonical, url_hash=url_hash, kind=kind, title=title,
            item_type="open_source" if kind == "repo" else "other",
            one_liner="待补充", ark_modules=[], last_update_summary=[], created_at=now, updated_at=now,
        )
        db.add(target)
        db.flush()

    subscription = db.query(RadarSubscription).filter(
        RadarSubscription.user_id == user_id,
        RadarSubscription.target_id == target.id,
    ).one_or_none()
    incoming_tags = list(dict.fromkeys((tags or []) + []))
    if subscription is None:
        subscription = RadarSubscription(
            user_id=user_id, target_id=target.id, tags=incoming_tags, remark=note or "",
            overrides={}, ai_suggestions={}, created_at=now, updated_at=now,
        )
        db.add(subscription)
        db.flush()
    else:
        restoring = subscription.removed_at is not None
        if restoring and subscription.removed_at < now - timedelta(days=30):
            subscription.status = "inbox"
            subscription.watch_level = "normal"
            subscription.remark = note or ""
            subscription.tags = incoming_tags
            subscription.overrides = {}
            subscription.ai_suggestions = {}
            subscription.unread_update_id = None
            subscription.last_pushed_at = None
            subscription.last_normal_pushed_at = None
            subscription.created_at = now
        else:
            if note:
                subscription.remark = note
            subscription.tags = list(dict.fromkeys([*(subscription.tags or []), *incoming_tags]))
        subscription.removed_at = None
        subscription.updated_at = now

    existing_source = None
    if ingest_job_id is not None:
        existing_source = db.query(RadarSource).filter_by(
            subscription_id=subscription.id, ingest_job_id=ingest_job_id,
            source_url=(source_url or raw_url)[:1024],
        ).first()
    if existing_source is None:
        db.add(RadarSource(
            subscription_id=subscription.id, ingest_job_id=ingest_job_id,
            source_url=(source_url or raw_url)[:1024],
            channel=channel, raw_text=raw_text or note, created_at=now,
        ))
    _sync_target_scan_state(db, target.id)
    db.flush()
    return subscription


def update_subscription(db: Session, user_id: int, subscription_id: int, data: dict) -> RadarSubscription:
    subscription = _owned(db, user_id, subscription_id)
    status = data.get("status")
    if status is not None:
        if status not in {"inbox", "trying", "adopted", "dropped"}:
            raise ValueError("无效的试用状态")
        subscription.status = status
        if "watch_level" not in data and status in _WATCH_BY_STATUS:
            subscription.watch_level = _WATCH_BY_STATUS[status]
    if "watch_level" in data:
        if data["watch_level"] not in {"key", "normal", "adopted", "silent"}:
            raise ValueError("无效的关注级别")
        subscription.watch_level = data["watch_level"]
    if "tags" in data:
        if not isinstance(data["tags"], list) or len(data["tags"]) > 30:
            raise ValueError("标签格式不正确")
        subscription.tags = list(dict.fromkeys(str(tag).strip()[:40] for tag in data["tags"] if str(tag).strip()))
    if "note" in data:
        subscription.remark = str(data["note"] or "")[:20000]
    if "overrides" in data:
        if not isinstance(data["overrides"], dict) or set(data["overrides"]) - _LOCKED_FIELDS:
            raise ValueError("存在不允许修改的字段")
        subscription.overrides = {**(subscription.overrides or {}), **data["overrides"]}
        subscription.ai_suggestions = {
            key: value for key, value in (subscription.ai_suggestions or {}).items()
            if key not in data["overrides"]
        }
    if data.get("clear_override"):
        field = data["clear_override"]
        if field not in _LOCKED_FIELDS:
            raise ValueError("无法解锁该字段")
        subscription.overrides = {k: v for k, v in (subscription.overrides or {}).items() if k != field}
    if data.get("accept_suggestion"):
        field = data["accept_suggestion"]
        suggestion = (subscription.ai_suggestions or {}).get(field)
        if field not in _LOCKED_FIELDS or suggestion is None:
            raise ValueError("没有可采纳的 AI 建议")
        subscription.overrides = {**(subscription.overrides or {}), field: suggestion}
        subscription.ai_suggestions = {k: v for k, v in (subscription.ai_suggestions or {}).items() if k != field}
    if data.get("mark_read"):
        subscription.unread_update_id = None
    subscription.updated_at = beijing_now()
    _sync_target_scan_state(db, subscription.target_id)
    db.flush()
    return subscription


def remove_subscription(db: Session, user_id: int, subscription_id: int) -> RadarSubscription:
    subscription = _owned(db, user_id, subscription_id)
    subscription.removed_at = beijing_now()
    subscription.updated_at = subscription.removed_at
    _sync_target_scan_state(db, subscription.target_id)
    db.flush()
    return subscription


def _dt(value):
    return value.isoformat(sep=" ", timespec="minutes") if value else None


def _update_dict(update: RadarUpdate | None):
    if update is None:
        return None
    return {
        "id": update.id, "detected_at": _dt(update.detected_at),
        "rule_level": update.rule_level, "ai_level": update.ai_level,
        "level": update.ai_level or update.rule_level, "ai_reason": update.ai_reason,
        "from_version": update.from_version, "to_version": update.to_version,
        "summary": update.summary or [], "ark_impact": update.ark_impact,
        "raw_ref": update.raw_ref or {},
    }


def serialize_subscription(db: Session, subscription: RadarSubscription) -> dict:
    target = db.get(RadarTarget, subscription.target_id)
    overrides = subscription.overrides or {}
    value = lambda field: overrides.get(field, getattr(target, field))
    sources = db.query(RadarSource).filter(
        RadarSource.subscription_id == subscription.id,
    ).order_by(RadarSource.created_at.desc(), RadarSource.id.desc()).limit(100).all()
    updates = db.query(RadarUpdate).filter(
        RadarUpdate.target_id == target.id,
    ).order_by(RadarUpdate.detected_at.desc(), RadarUpdate.id.desc()).limit(30).all()
    unread = db.get(RadarUpdate, subscription.unread_update_id) if subscription.unread_update_id else None
    host = urlsplit(target.canonical_url).hostname or ""
    return {
        "id": subscription.id, "target_id": target.id,
        "canonical_url": target.canonical_url, "host": host,
        "kind": target.kind, "title": value("title"), "item_type": value("item_type"),
        "one_liner": value("one_liner"), "description": value("description") or "",
        "ark_modules": value("ark_modules") or [], "version": target.version,
        "last_updated_at": _dt(target.last_updated_at),
        "last_update_summary": target.last_update_summary or [],
        "read_state": target.read_state, "last_error": target.last_error,
        "last_scanned_at": _dt(target.last_scanned_at), "scan_mode": target.scan_mode,
        "scan_enabled": target.scan_enabled, "stars": target.stars,
        "license": target.license, "language": target.language,
        "status": subscription.status, "watch_level": subscription.watch_level,
        "tags": subscription.tags or [], "note": subscription.remark or "",
        "locked_fields": list(overrides), "ai_suggestions": subscription.ai_suggestions or {},
        "unread": bool(unread), "unread_update": _update_dict(unread),
        "updates": [_update_dict(update) for update in updates],
        "sources": [{"id": source.id, "source_url": source.source_url, "channel": source.channel,
                     "raw_text": source.raw_text or "", "created_at": _dt(source.created_at)} for source in sources],
        "created_at": _dt(subscription.created_at), "updated_at": _dt(subscription.updated_at),
    }


def list_subscriptions(db: Session, user_id: int, *, view="all", keyword="", item_type="", module="", read_state="", page=1, page_size=50) -> dict:
    query = db.query(RadarSubscription).join(RadarTarget).filter(
        RadarSubscription.user_id == user_id,
        RadarSubscription.removed_at.is_(None),
    )
    if view == "updates":
        query = query.filter(RadarSubscription.unread_update_id.is_not(None))
    elif view in {"inbox", "trying", "adopted", "dropped"}:
        query = query.filter(RadarSubscription.status == view)
    if item_type:
        query = query.filter(or_(RadarTarget.item_type == item_type, RadarSubscription.overrides["item_type"].as_string() == item_type))
    if read_state:
        query = query.filter(RadarTarget.read_state == read_state)
    rows = query.order_by(RadarSubscription.updated_at.desc(), RadarSubscription.id.desc()).all()
    items = [serialize_subscription(db, row) for row in rows]
    if keyword:
        lowered = keyword.strip().lower()
        items = [item for item in items if lowered in " ".join([
            item["title"], item["one_liner"], item["note"], item["host"], *item["tags"],
        ]).lower()]
    if module:
        items = [item for item in items if any(entry.get("name") == module for entry in item["ark_modules"])]
    total = len(items)
    start = (page - 1) * page_size
    all_active = db.query(RadarSubscription).filter(
        RadarSubscription.user_id == user_id, RadarSubscription.removed_at.is_(None),
    ).all()
    counts = {
        "all": len(all_active),
        "updates": sum(row.unread_update_id is not None for row in all_active),
        **{status: sum(row.status == status for row in all_active) for status in ("inbox", "trying", "adopted", "dropped")},
    }
    return {"items": items[start:start + page_size], "total": total, "page": page, "page_size": page_size, "counts": counts}
