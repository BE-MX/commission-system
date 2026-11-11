"""项目雷达早报组装与个人投递幂等。"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.time import beijing_now, beijing_today
from app.project_radar.classify import should_push
from app.project_radar.models import (
    RadarDelivery, RadarDialog, RadarDigest, RadarOutbox, RadarScanRun,
    RadarSubscription, RadarTarget, RadarUpdate, RadarUserSetting,
)


def _setting(db: Session, user_id: int) -> RadarUserSetting:
    setting = db.get(RadarUserSetting, user_id)
    if setting is None:
        setting = RadarUserSetting(user_id=user_id)
        db.add(setting)
        db.flush()
    return setting


def _pending_updates(db: Session, subscription: RadarSubscription):
    delivered = db.query(RadarDelivery.update_id).filter(RadarDelivery.subscription_id == subscription.id)
    return db.query(RadarUpdate).filter(
        RadarUpdate.target_id == subscription.target_id,
        RadarUpdate.detected_at >= subscription.created_at - timedelta(days=1),
        ~RadarUpdate.id.in_(delivered),
    ).order_by(RadarUpdate.detected_at, RadarUpdate.id).all()


def _item(db: Session, subscription, update, number):
    target = db.get(RadarTarget, subscription.target_id)
    level = update.ai_level or update.rule_level
    label = "关键" if level == "key" else "更新"
    version = ""
    if update.to_version:
        version = f" {update.from_version} → {update.to_version}" if update.from_version else f" {update.to_version}"
    lines = [f"{number}. 【{label}】{target.title}{version}"]
    lines.extend(f"· {summary}" for summary in (update.summary or [])[:3])
    if update.ark_impact:
        lines.append(f"→ {update.ark_impact}")
    return "\n".join(lines), {"subscription_id": subscription.id, "update_id": update.id, "level": level}


def prepare_digest(db: Session, user_id: int, *, digest_date=None) -> RadarDigest | None:
    digest_date = digest_date or beijing_today()
    existing = db.query(RadarDigest).filter_by(user_id=user_id, digest_date=digest_date).one_or_none()
    if existing:
        return existing
    setting = _setting(db, user_id)
    subscriptions = db.query(RadarSubscription).filter(
        RadarSubscription.user_id == user_id, RadarSubscription.removed_at.is_(None),
    ).order_by(RadarSubscription.id).all()
    blocks, items = [], []
    for subscription in subscriptions:
        for update in _pending_updates(db, subscription):
            level = update.ai_level or update.rule_level
            days = None
            if subscription.last_normal_pushed_at:
                days = (beijing_now() - subscription.last_normal_pushed_at).days
            notes = (update.raw_ref or {}).get("release_notes") or "\n".join(update.summary or [])
            if not should_push(subscription.watch_level, level, notes, days_since_normal_push=days):
                continue
            block, item = _item(db, subscription, update, len(items) + 1)
            blocks.append(block)
            items.append(item)

    scan = db.query(RadarScanRun).filter(RadarScanRun.scan_date == digest_date).one_or_none()
    attention = db.query(RadarTarget).join(RadarSubscription).filter(
        RadarSubscription.user_id == user_id, RadarSubscription.removed_at.is_(None),
        RadarTarget.consecutive_failures >= 3,
    ).distinct().all()
    sleepy = []
    if setting.sleepy_reminder and digest_date.weekday() == 0:
        threshold = beijing_now() - timedelta(days=14)
        sleepy = db.query(RadarSubscription).join(RadarTarget).filter(
            RadarSubscription.user_id == user_id, RadarSubscription.removed_at.is_(None),
            RadarSubscription.status == "inbox", RadarSubscription.created_at <= threshold,
        ).order_by(RadarSubscription.created_at).limit(3).all()

    heartbeat = False
    if not items:
        last_sent = db.query(RadarDigest).filter(
            RadarDigest.user_id == user_id, RadarDigest.status == "sent",
            RadarDigest.digest_date < digest_date,
        ).order_by(RadarDigest.digest_date.desc()).first()
        oldest = min((row.created_at for row in subscriptions), default=None)
        heartbeat = bool(
            (last_sent and (digest_date - last_sent.digest_date).days >= 7)
            or (not last_sent and oldest and oldest <= beijing_now() - timedelta(days=7))
        )
        if not setting.send_empty and not heartbeat and not attention:
            return None

    title = f"方舟雷达 · {digest_date.month}月{digest_date.day}日早报"
    lines = [title]
    if heartbeat:
        lines.append(f"雷达运行正常，已扫描 {scan.success_count if scan else 0} 项；连续 7 天无更新推送。")
    elif items:
        key_count = sum(item["level"] == "key" for item in items)
        lines.append(f"{len(items)} 项有更新，其中 {key_count} 项需要关注")
        lines.extend(["", *blocks])
    else:
        lines.append("今日没有值得推送的更新。")
    if attention:
        lines.extend(["", "【需要处理】"] + [f"· {target.title} 连续 {target.consecutive_failures} 天读取失败" for target in attention])
    if sleepy:
        lines.extend(["", "【本周沉睡】"] + [f"· {db.get(RadarTarget, row.target_id).title}，收录超过 14 天仍待看" for row in sleepy])
    if scan:
        lines.extend(["", f"扫描 {scan.success_count}/{scan.total_count} 完成"])
    lines.append("回复「静默 编号」可停止推送某项 · 打开项目雷达 ›")
    digest = RadarDigest(
        user_id=user_id, digest_date=digest_date, item_count=len(items),
        status="pending", content="\n".join(lines), created_at=beijing_now(),
    )
    db.add(digest)
    db.flush()
    db.add(RadarOutbox(
        user_id=user_id, dedup_key=f"digest:{user_id}:{digest_date.isoformat()}", kind="digest",
        payload={"digest_id": digest.id, "items": items}, created_at=beijing_now(),
    ))
    db.flush()
    return digest


def prepare_due_digests(db: Session):
    created = []
    users = db.query(RadarSubscription.user_id).filter(RadarSubscription.removed_at.is_(None)).distinct().all()
    current = beijing_now().strftime("%H:%M")
    for (user_id,) in users:
        setting = _setting(db, user_id)
        if setting.digest_time > current:
            continue
        digest = prepare_digest(db, user_id)
        if digest and digest.status == "pending":
            created.append(digest)
    db.commit()
    return created


def complete_digest_delivery(db: Session, outbox: RadarOutbox):
    digest = db.get(RadarDigest, outbox.payload["digest_id"])
    digest.status = "sent"
    digest.dingtalk_ref = str(outbox.payload.get("dingtalk_ref") or "")[:256] or None
    now = beijing_now()
    for item in outbox.payload.get("items") or []:
        exists = db.query(RadarDelivery).filter_by(
            subscription_id=item["subscription_id"], update_id=item["update_id"],
        ).first()
        if not exists:
            db.add(RadarDelivery(
                subscription_id=item["subscription_id"], update_id=item["update_id"],
                digest_id=digest.id, delivered_at=now,
            ))
        subscription = db.get(RadarSubscription, item["subscription_id"])
        subscription.last_pushed_at = now
        if item["level"] == "normal":
            subscription.last_normal_pushed_at = now
    ids = [item["subscription_id"] for item in outbox.payload.get("items") or []]
    if ids:
        dialog = db.query(RadarDialog).filter_by(user_id=outbox.user_id).one_or_none()
        if dialog is None:
            dialog = RadarDialog(user_id=outbox.user_id, kind="card", payload={}, expires_at=now + timedelta(days=1), created_at=now)
            db.add(dialog)
        dialog.kind = "card"
        dialog.payload = {"subscription_ids": ids}
        dialog.expires_at = now + timedelta(days=1)
    db.flush()
