"""固定程序检测变化，AI 只解读已确认的更新。"""

from __future__ import annotations

import base64
from difflib import SequenceMatcher
import hashlib
import logging
import zlib

from sqlalchemy.orm import Session

from app.core.time import beijing_now, beijing_today
from app.project_radar.analysis import classify_update
from app.project_radar.classify import rule_level
from app.project_radar.fetcher import RadarFetcher
from app.project_radar.models import (
    RadarScanRun, RadarSnapshot, RadarSubscription, RadarTarget,
    RadarTrackedPage, RadarUpdate,
)

logger = logging.getLogger("commission.project_radar.scan")


def compress_text(text: str) -> str:
    return base64.b64encode(zlib.compress((text or "").encode("utf-8"), level=9)).decode("ascii")


def decompress_text(value: str) -> str:
    return zlib.decompress(base64.b64decode(value)).decode("utf-8")


def text_change_ratio(before: str, after: str) -> float:
    if before == after:
        return 0.0
    if not before or not after:
        return 1.0
    return 1.0 - SequenceMatcher(None, before, after, autojunk=False).ratio()


def _create_update(db: Session, target, *, event_key, level, from_version=None, to_version=None,
                   notes="", raw_ref=None, classifier=classify_update):
    existing = db.query(RadarUpdate).filter(
        RadarUpdate.target_id == target.id, RadarUpdate.event_key == event_key,
    ).one_or_none()
    if existing:
        return None
    interpretation = classifier(
        db, from_version=from_version, to_version=to_version,
        release_notes=notes, level=level, ark_modules=target.ark_modules,
    ) if level in {"key", "normal"} else {
        "level": "noise", "reason": "规则：非有效更新", "summary": [], "ark_impact": "",
    }
    update = RadarUpdate(
        target_id=target.id, event_key=event_key, detected_at=beijing_now(),
        rule_level=level, ai_level=interpretation["level"], ai_reason=interpretation.get("reason"),
        from_version=from_version, to_version=to_version,
        summary=interpretation.get("summary") or [], ark_impact=interpretation.get("ark_impact") or "",
        raw_ref=raw_ref or {}, created_at=beijing_now(),
    )
    db.add(update)
    db.flush()
    if (update.ai_level or update.rule_level) in {"key", "normal"}:
        for subscription in db.query(RadarSubscription).filter(
            RadarSubscription.target_id == target.id, RadarSubscription.removed_at.is_(None),
        ).all():
            subscription.unread_update_id = update.id
        target.last_update_summary = update.summary
    return update


def apply_repo_result(db: Session, target, result, *, classifier=classify_update):
    now = beijing_now()
    target.last_scanned_at = now
    if result.get("deleted"):
        update = _create_update(
            db, target, event_key="repository-deleted", level="key",
            notes="仓库已删除或不再公开访问", raw_ref={"url": target.canonical_url}, classifier=classifier,
        )
        target.read_state = "limited"
        target.last_error = "仓库已删除或不再公开访问"
        return update

    facts = result.get("facts") or {}
    previous_version = target.version
    was_archived = bool(target.archived)
    for field in ("title", "stars", "license", "language", "version", "last_updated_at"):
        if field in facts and (facts[field] is not None or field == "version"):
            setattr(target, field, facts[field])
    target.archived = bool(facts.get("archived", target.archived))
    target.repo_etag = result.get("repo_etag") or target.repo_etag
    target.release_etag = result.get("release_etag") or target.release_etag
    target.read_state = "ok"
    target.consecutive_failures = 0
    target.last_error = None
    if result.get("unchanged") and not target.archived:
        return None

    latest = result.get("latest_release")
    update = None
    if latest:
        version = latest.get("tag_name")
        if version and version != previous_version:
            notes = latest.get("body") or ""
            level = rule_level(previous_version, version, notes)
            update = _create_update(
                db, target, event_key=f"release:{latest.get('id') or version}", level=level,
                from_version=previous_version, to_version=version, notes=notes,
                raw_ref={"url": latest.get("html_url") or target.canonical_url,
                         "published_at": latest.get("published_at"), "source": "github_release",
                         "release_notes": notes[:20000]},
                classifier=classifier,
            )
    elif target.version and target.version != previous_version:
        level = rule_level(previous_version, target.version)
        update = _create_update(
            db, target, event_key=f"tag:{target.version}", level=level,
            from_version=previous_version, to_version=target.version,
            raw_ref={"url": f"{target.canonical_url}/releases/tag/{target.version}", "source": "github_tag"},
            classifier=classifier,
        )
    if target.archived and not was_archived:
        update = _create_update(
            db, target, event_key="repository-archived", level="key",
            from_version=previous_version, to_version=target.version,
            notes="仓库已归档", raw_ref={"url": target.canonical_url}, classifier=classifier,
        ) or update
    return update


def initialize_target(db: Session, target, fetched, *, analyzer=None):
    facts = fetched.get("facts") or {}
    if target.kind == "repo":
        for field in ("title", "stars", "license", "language", "version", "last_updated_at"):
            if facts.get(field) is not None:
                setattr(target, field, facts[field])
        target.archived = bool(facts.get("archived", False))
        target.repo_etag = fetched.get("repo_etag")
        target.release_etag = fetched.get("release_etag")
    else:
        target.title = fetched.get("title") or target.title
        pages = fetched.get("tracked_pages") or []
        if pages:
            known_hashes = {url_hash for (url_hash,) in db.query(RadarTrackedPage.url_hash).filter_by(target_id=target.id)}
            for page in pages:
                url = page["url"]
                url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
                if url_hash in known_hashes:
                    continue
                db.add(RadarTrackedPage(target_id=target.id, url=url, url_hash=url_hash, page_kind=page["page_kind"]))
                known_hashes.add(url_hash)
        if not target.last_updated_at:
            target.last_updated_at = beijing_now()
    target.read_state = "ok" if (fetched.get("text") or target.kind == "repo") else "limited"
    target.consecutive_failures = 0 if target.read_state == "ok" else 1
    target.last_error = None if target.read_state == "ok" else "只读取到页面标题，正文读取受限"
    target.last_scanned_at = beijing_now()
    if target.one_liner in {"", "待补充"}:
        fallback = facts.get("description_source") if target.kind == "repo" else fetched.get("text")
        if fallback:
            target.one_liner = " ".join(fallback.split())[:40]
    if analyzer and fetched.get("text"):
        analyzer(db, target, fetched["text"])
    db.flush()


def _record_page_snapshot(db: Session, target, page, text: str, etag=None):
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    previous = db.query(RadarSnapshot).filter(
        RadarSnapshot.tracked_page_id == page.id,
    ).order_by(RadarSnapshot.captured_at.desc(), RadarSnapshot.id.desc()).first()
    db.add(RadarSnapshot(
        target_id=target.id, tracked_page_id=page.id, captured_at=beijing_now(),
        clean_text_compressed=compress_text(text), text_hash=digest, etag=etag,
        raw_ref={"url": page.url},
    ))
    old = db.query(RadarSnapshot).filter(
        RadarSnapshot.tracked_page_id == page.id,
    ).order_by(RadarSnapshot.captured_at.desc(), RadarSnapshot.id.desc()).offset(5).all()
    for snapshot in old:
        db.delete(snapshot)
    return previous, digest


def scan_website_target(db: Session, target, *, fetcher: RadarFetcher, classifier=classify_update):
    updates = []
    pages = db.query(RadarTrackedPage).filter(
        RadarTrackedPage.target_id == target.id, RadarTrackedPage.enabled.is_(True),
    ).all()
    if not pages:
        fetcher.read_website(target.canonical_url)
    for page in pages:
        result = fetcher.read_page(page.url, etag=page.etag)
        page.etag = result.get("etag") or page.etag
        if result.get("unchanged"):
            continue
        text = result.get("text") or ""
        previous, digest = _record_page_snapshot(db, target, page, text, page.etag)
        if previous is None:
            continue
        before = decompress_text(previous.clean_text_compressed or "")
        ratio = text_change_ratio(before, text)
        if ratio < 0.08 or previous.text_hash == digest:
            continue
        update = _create_update(
            db, target, event_key=f"page:{page.id}:{digest}", level="normal",
            notes=f"旧正文：\n{before[-20000:]}\n\n新正文：\n{text[:30000:]}",
            raw_ref={"url": page.url, "page_kind": page.page_kind, "change_ratio": round(ratio, 4)},
            classifier=classifier,
        )
        if update:
            updates.append(update)
    target.last_scanned_at = beijing_now()
    target.last_updated_at = updates[-1].detected_at if updates else target.last_updated_at
    target.read_state = "ok"
    target.consecutive_failures = 0
    target.last_error = None
    return updates


def scan_target(db: Session, target, *, fetcher: RadarFetcher, classifier=classify_update):
    if target.kind == "repo":
        result = fetcher.read_repo(target, include_content=False)
        return apply_repo_result(db, target, result, classifier=classifier)
    return scan_website_target(db, target, fetcher=fetcher, classifier=classifier)


def scan_all(db: Session, *, fetcher: RadarFetcher | None = None, classifier=classify_update):
    fetcher = fetcher or RadarFetcher()
    today = beijing_today()
    run = db.query(RadarScanRun).filter(RadarScanRun.scan_date == today).one_or_none()
    if run is None:
        run = RadarScanRun(scan_date=today, started_at=beijing_now())
        db.add(run)
    run.status = "running"
    run.error = None
    run.finished_at = None
    targets = db.query(RadarTarget).join(RadarSubscription).filter(
        RadarTarget.scan_enabled.is_(True), RadarTarget.scan_mode == "program",
        RadarSubscription.removed_at.is_(None), RadarSubscription.status != "dropped",
    ).distinct().all()
    run.total_count = len(targets)
    run.success_count = 0
    run.failed_count = 0
    db.commit()
    for target in targets:
        try:
            with db.begin_nested():
                scan_target(db, target, fetcher=fetcher, classifier=classifier)
            db.commit()
            run.success_count += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning("Project radar target scan failed target=%s (%s)", target.id, type(exc).__name__)
            print(f"Project radar target scan failed target={target.id} ({type(exc).__name__})", flush=True)
            failed_target = db.get(RadarTarget, target.id)
            failed_target.consecutive_failures += 1
            failed_target.read_state = "limited" if failed_target.consecutive_failures < 3 else "failed"
            failed_target.last_error = "读取失败，将在下次扫描重试"[:500]
            failed_target.last_scanned_at = beijing_now()
            run.failed_count += 1
        db.commit()
    run.status = "success" if run.failed_count == 0 else ("failed" if run.success_count == 0 and run.total_count else "partial")
    run.finished_at = beijing_now()
    db.commit()
    return run
