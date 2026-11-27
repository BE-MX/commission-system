"""B track background work: sync threads, enqueue daily runs, drain the queue, weekly review.

Scheduling only decides *when*. Authority is re-checked before every model call,
after it returns, and again under the thread's row lock before any write.
"""

import logging
import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.ai.service import chat
from app.ai.text_snapshot import prepare_text_chat
from app.alibaba_feed.business_service import require_actor, unlinked_lead_item
from app.alibaba_feed.errors import FeedError
from app.alibaba_feed.models import (
    AlibabaFeedItem, AlibabaFeedLink, AlibabaFeedMessage, AlibabaFeedPilot, AlibabaFeedSource,
)
from app.alibaba_feed.normalization import safe_messages
from app.alibaba_feed.pilot_service import active_pilot
from app.client_desk import private_scope
from app.client_desk.models import ClientDeskUnlinkedReview, ClientDeskUnlinkedRun, ClientDeskUnlinkedThread
from app.core.config import get_settings
from app.core.time import beijing_now, beijing_today

from . import core, wa

logger = logging.getLogger("commission.client_desk.unlinked")

CHANNEL = "alibaba_tm"
LEASE = timedelta(seconds=180)
MAX_OUTPUT_TOKENS = 1200
MAX_WEEKLY_OUTPUT_TOKENS = 3000
CALL_TIMEOUT_SEC = 85
ACTIVE_STATES = ("active", "prospect")
MANUAL_RUNS_PER_DAY = 2
WEEKLY_ATTEMPTS_PER_WEEK = 2


# ---------- authority ----------

def _pilot_scope(db, action="read"):
    pilot = active_pilot(db)
    if pilot is None:
        return None
    try:
        return require_actor(db, pilot.user_id, action, unlinked=True)
    except HTTPException:
        return None


def lock_source(db, source_id):
    return db.query(AlibabaFeedSource).filter_by(id=source_id).populate_existing().with_for_update().first()


def _current_deps(db, source_id):
    source = db.query(AlibabaFeedSource).filter_by(id=source_id).first()
    if source is None:
        return None
    pilot_version = db.query(AlibabaFeedPilot.version).filter_by(id=1).with_for_update(read=True).scalar()
    return {"pilot_version": pilot_version, "mapping_version": source.mapping_version,
            "collection_generation": source.collection_generation,
            "consent_version": source.consent_version}


def authorized_item(db, uid, source_id, thread):
    """Return the live feed item if the thread may still be shown or written; otherwise None.

    Covers consent, owner binding, the current snapshot, no customer link, and
    that the mapping, generation and consent versions the thread was built under
    are still current.
    """
    if thread.item_id is None:
        return None
    try:
        _, item = unlinked_lead_item(db, uid, source_id, thread.item_id)
    except (HTTPException, FeedError):
        return None
    deps = thread.source_dependencies or {}
    if deps != _current_deps(db, source_id):
        return None
    return item


def tm_enabled():
    cfg = get_settings()
    return bool(cfg.CLIENT_DESK_UNLINKED_ENABLED and cfg.CLIENT_DESK_UNLINKED_TM_ENABLED)


def thread_source(db, uid, thread, source_id, action="read"):
    """Channel-neutral authority check: the live source handle for a thread, or None."""
    if thread.channel == wa.CHANNEL:
        return wa.authorized_conversation(db, uid, thread, action)
    if source_id is None or not tm_enabled():
        return None
    return authorized_item(db, uid, source_id, thread)


def run_evidence_current(db, thread, handle, run):
    if thread.channel == wa.CHANNEL:
        return wa.evidence_current(db, thread, run, handle)
    return evidence_current(db, thread, handle, run)


# ---------- thread sync ----------

def _direction(dir_value):
    return {"buyer": "inbound", "seller": "outbound"}.get(dir_value, "unknown")


def _inbound_watermark(db, item, messages):
    """Return (seen_pair, last_direction, last_at) for one record.

    Stable v1.1 records use the (source_order, message_revision) of the newest
    inbound message. Legacy v1 records have no ordered identity, so the inbound
    count stands in as the order, with revision 0.
    """
    inbound = [m for m in messages if m.get("dir") == "buyer"]
    last = messages[-1] if messages else None
    last_direction = _direction(last.get("dir")) if last else "unknown"
    if item.schema_version == "ark_alibaba_feed_v1.1" and item.conversation_id:
        ids = [m.get("message_id") for m in inbound if m.get("message_id")]
        if not ids:
            return None, last_direction, item.observed_at
        rows = (db.query(AlibabaFeedMessage)
                .filter(AlibabaFeedMessage.source_account_uid == item.source_account_uid,
                        AlibabaFeedMessage.collection_generation == item.collection_generation,
                        AlibabaFeedMessage.conversation_id == item.conversation_id,
                        AlibabaFeedMessage.message_id.in_(ids),
                        AlibabaFeedMessage.deleted_at.is_(None))
                .all())
        if not rows:
            return None, last_direction, item.observed_at
        newest = max(rows, key=lambda r: ((r.source_order or 0), r.message_revision))
        return [int(newest.source_order or 0), int(newest.message_revision)], last_direction, item.observed_at
    if not inbound:
        return None, last_direction, item.observed_at
    return [len(inbound), 0], last_direction, item.observed_at


def _messages_digest(messages):
    return core.digest([
        [m.get(key) for key in ("message_id", "message_revision", "_original_position", "dir", "at", "text")]
        for m in messages
    ])


def _evidence_dependencies(thread, messages):
    return {
        **(thread.source_dependencies or {}),
        "messages_digest": _messages_digest(messages),
        "message_count": len(messages),
    }


def _saved_evidence_current(thread, run, messages):
    dependencies = run.source_dependencies or {}
    count = dependencies.get("message_count")
    # Appending messages leaves earlier evidence valid. Editing, deleting or
    # shifting a referenced message changes its recorded evidence.
    return type(count) is int and 0 <= count <= len(messages) and (
        dependencies == _evidence_dependencies(thread, messages[:count])
    )


def evidence_current(db, thread, item, run):
    return _saved_evidence_current(thread, run, safe_messages(db, item))


def matchable_companies(db, user):
    try:
        return private_scope.list_private_companies(db, user)
    except HTTPException as exc:
        if isinstance(exc.detail, dict) and exc.detail.get("code") == "OKKI_BINDING_REQUIRED":
            return []
        raise


def _thread_key(item):
    return core.thread_key(item.record_type, item.inquiry_id, item.conversation_id, item.schema_version)


def _latest_succeeded(db, thread_id):
    return (db.query(ClientDeskUnlinkedRun)
            .filter(ClientDeskUnlinkedRun.thread_id == thread_id,
                    ClientDeskUnlinkedRun.status.in_(("succeeded", "skipped_non_lead")))
            .order_by(ClientDeskUnlinkedRun.id.desc()).first())


def wipe_run_content(run, status):
    run.status = status
    run.one_line_summary = None
    run.missing_or_next_action = None
    run.breakthrough_angle = None
    run.draft_message = None
    run.extracted_clues = None
    run.cites = None
    run.lease_token = None


def sync_threads(db, uid, source_id):
    """Refresh each eligible TM record into its thread row. Returns the number of threads touched."""
    source = lock_source(db, source_id)
    if source is None or source.consent_state != "authorized" or not source.crm_shared:
        return 0
    deps = _current_deps(db, source_id)
    _release_links(db, uid, source)
    db.flush()
    items = (db.query(AlibabaFeedItem.id)
             .filter(AlibabaFeedItem.source_account_uid == source.source_account_uid,
                     AlibabaFeedItem.is_current.is_(True))
             .order_by(AlibabaFeedItem.id).all())
    touched = 0
    threads = {}
    for (item_id,) in items:
        try:
            _, item = unlinked_lead_item(db, uid, source_id, item_id)
        except (HTTPException, FeedError):
            continue
        messages = safe_messages(db, item)
        seen, last_direction, last_at = _inbound_watermark(db, item, messages)
        key = _thread_key(item)
        thread = threads.get(key)
        if thread is None:
            thread = (db.query(ClientDeskUnlinkedThread)
                      .filter_by(user_id=uid, channel=CHANNEL, source_account_uid=source.source_account_uid,
                                 thread_key=key)
                      .populate_existing().with_for_update().first())
        if thread is None:
            thread = ClientDeskUnlinkedThread(user_id=uid, channel=CHANNEL,
                                              source_account_uid=source.source_account_uid,
                                              thread_key=key, status="active")
            db.add(thread)
            db.flush()
        threads[key] = thread
        if thread.status == "linked":
            continue
        # Several current records can share one conversation; the watermark never moves backwards.
        if core.as_pair(thread.seen_watermark) and core.as_pair(seen) is not None \
                and core.as_pair(seen) < core.as_pair(thread.seen_watermark) \
                and thread.item_id != item.id:
            previous_item = db.get(AlibabaFeedItem, thread.item_id)
            if (previous_item is not None and previous_item.is_current
                    and previous_item.collection_generation == item.collection_generation):
                continue
        if thread.status == "ignored":
            # Keep a current source pointer so an explicit restore can be authorised.
            thread.item_id = item.id
            thread.source_dependencies = deps
            thread.seen_watermark = seen
            continue
        # Content that changed under an analysed run (revocation, edit) invalidates that run.
        old_dependencies = thread.source_dependencies
        thread.source_dependencies = deps
        latest = _latest_succeeded(db, thread.id)
        if latest is not None and not _saved_evidence_current(thread, latest, messages):
            wipe_run_content(latest, "stale")
            latest.error_code = "content_changed"
        if old_dependencies and old_dependencies.get("collection_generation") != deps["collection_generation"]:
            thread.handled_at = None
            thread.done_watermark = None
        elif old_dependencies and old_dependencies != deps and thread.handled_at is None:
            thread.done_watermark = None
        buyer = item.snapshot.get("buyer") or {}
        thread.item_id = item.id
        thread.display_name = str(buyer.get("name") or "")[:160] or None
        thread.country_code = str(buyer.get("country") or "")[:8] or None
        thread.last_message_at = last_at
        thread.last_direction = last_direction
        thread.seen_watermark = seen
        touched += 1
    db.flush()
    return touched


def _reset_linked_thread(thread):
    thread.status = "active"
    thread.linked_company_id = None
    thread.done_watermark = None
    thread.handled_at = None


def release_deleted_link(db, link):
    """Release the B-track thread in the same transaction as the TM unlink."""
    thread = (db.query(ClientDeskUnlinkedThread)
              .filter_by(user_id=link.user_id, channel=CHANNEL, source_account_uid=link.source_account_uid,
                         item_id=link.item_id, linked_company_id=link.company_id, status="linked")
              .populate_existing().with_for_update().first())
    if thread is not None:
        _reset_linked_thread(thread)


def _release_links(db, uid, source):
    """A thread bound to a customer returns to the B track when the link is removed."""
    for thread in (db.query(ClientDeskUnlinkedThread)
                   .filter(ClientDeskUnlinkedThread.user_id == uid,
                           ClientDeskUnlinkedThread.channel == CHANNEL,
                           ClientDeskUnlinkedThread.source_account_uid == source.source_account_uid,
                           ClientDeskUnlinkedThread.status == "linked")
                   .populate_existing().with_for_update().all()):
        item = db.query(AlibabaFeedItem).filter_by(id=thread.item_id).first() if thread.item_id else None
        if item is None:
            continue
        live = (db.query(AlibabaFeedLink.id)
                .filter_by(user_id=uid, source_account_uid=item.source_account_uid,
                           collection_generation=item.collection_generation,
                           record_type=item.record_type, inquiry_id=item.inquiry_id, deleted_at=None)
                .with_for_update(read=True).first())
        if live is None or item.collection_generation != source.collection_generation:
            _reset_linked_thread(thread)


# ---------- queue ----------

def _pending(thread):
    return core.has_newer_inbound(thread.seen_watermark, thread.done_watermark)


def enqueue_daily(db, uid, source_id, *, quota, day=None, channel=CHANNEL):
    """Queue one daily run per pending, still-authorized thread, up to the rep's daily quota per channel."""
    day = day or beijing_today()
    used = (db.query(func.count(ClientDeskUnlinkedRun.id))
            .join(ClientDeskUnlinkedThread, ClientDeskUnlinkedThread.id == ClientDeskUnlinkedRun.thread_id)
            .filter(ClientDeskUnlinkedRun.user_id == uid, ClientDeskUnlinkedRun.biz_date == day,
                    ClientDeskUnlinkedRun.trigger_type == "daily",
                    ClientDeskUnlinkedThread.channel == channel).scalar() or 0)
    room = max(0, quota - used)
    if room == 0:
        return 0
    threads = (db.query(ClientDeskUnlinkedThread)
               .filter(ClientDeskUnlinkedThread.user_id == uid,
                       ClientDeskUnlinkedThread.channel == channel,
                       ClientDeskUnlinkedThread.status.in_(ACTIVE_STATES),
                       ClientDeskUnlinkedThread.seen_watermark.isnot(None))
               .all())
    pending = [t for t in threads if _pending(t)]
    # Customer messages we have not answered come first, then the most recent.
    pending.sort(key=lambda t: (t.last_direction == "inbound", t.last_message_at or datetime.min), reverse=True)
    queued = 0
    for thread in pending:
        if queued >= room:
            break
        if thread_source(db, uid, thread, source_id) is None:
            continue  # unauthorised threads never spend the quota
        if (db.query(ClientDeskUnlinkedRun.id)
                .filter_by(thread_id=thread.id, biz_date=day, trigger_type="daily", run_seq=0).first()):
            continue
        db.add(_new_run(thread, uid, day, "daily", 0))
        queued += 1
    db.flush()
    return queued


def _new_run(thread, uid, day, trigger, run_seq):
    return ClientDeskUnlinkedRun(
        thread_id=thread.id, user_id=uid, biz_date=day, trigger_type=trigger, run_seq=run_seq,
        status="queued", attempts=0, watermark=thread.seen_watermark,
        protocol_version=core.PROTOCOL_VERSION, needs_review=False,
    )


def enqueue_manual(db, uid, thread, *, per_day_limit=MANUAL_RUNS_PER_DAY):
    """Queue an explicit re-run for one thread, at most `per_day_limit` per thread per day."""
    day = beijing_today()
    used = (db.query(func.count(ClientDeskUnlinkedRun.id))
            .filter(ClientDeskUnlinkedRun.thread_id == thread.id, ClientDeskUnlinkedRun.biz_date == day,
                    ClientDeskUnlinkedRun.trigger_type == "manual").scalar() or 0)
    if used >= per_day_limit:
        raise HTTPException(429, "今日手动分析次数已用完")
    run = _new_run(thread, uid, day, "manual", used + 1)
    db.add(run)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "分析请求已存在，请稍后刷新") from exc
    return run


def _recover_expired(db, now):
    stale = (db.query(ClientDeskUnlinkedRun)
             .filter(ClientDeskUnlinkedRun.status == "running",
                     ClientDeskUnlinkedRun.lease_expires_at < now).all())
    for run in stale:
        # The provider may have answered; never retry automatically.
        run.status = "ambiguous"
        run.error_code = "lease_expired"
        run.lease_token = None
    if stale:
        db.commit()


def _claim(db, now, limit):
    rows = (db.query(ClientDeskUnlinkedRun.id)
            .filter(ClientDeskUnlinkedRun.status == "queued")
            .order_by(ClientDeskUnlinkedRun.id).limit(limit).all())
    claimed = []
    for (run_id,) in rows:
        token = secrets.token_hex(16)
        updated = (db.query(ClientDeskUnlinkedRun)
                   .filter(ClientDeskUnlinkedRun.id == run_id, ClientDeskUnlinkedRun.status == "queued")
                   .update({"status": "running", "lease_token": token, "lease_expires_at": now + LEASE,
                            "call_started_at": now, "attempts": ClientDeskUnlinkedRun.attempts + 1},
                           synchronize_session=False))
        if updated:
            claimed.append((run_id, token))
    db.commit()
    return claimed


def drain_queue(session_factory, limit=10):
    """Process queued runs. Each run is independent; one failure never stops the batch."""
    if not (tm_enabled() or wa.enabled()):
        return 0
    with session_factory() as db:
        now = beijing_now()
        _recover_expired(db, now)
        claimed = _claim(db, now, limit)
    for run_id, token in claimed:
        with session_factory() as db:
            try:
                analyze_run(db, run_id, token)
            except Exception as exc:  # noqa: BLE001 - recorded on the run, not raised
                db.rollback()
                logger.warning("Unlinked run %s failed: %s", run_id, type(exc).__name__)
                print(f"[CLIENT_DESK_UNLINKED] run {run_id} failed: {type(exc).__name__}", flush=True)
                _fail(db, run_id, token, "internal_error")
    return len(claimed)


def _fail(db, run_id, token, code):
    run = db.query(ClientDeskUnlinkedRun).filter_by(id=run_id, lease_token=token).first()
    if run is None:
        return
    run.status = "failed"
    run.error_code = code
    run.lease_token = None
    db.commit()


def _finish(db, run, token, status, code):
    fresh = (db.query(ClientDeskUnlinkedRun).filter_by(id=run.id, lease_token=token, status="running")
             .populate_existing().with_for_update().first())
    if fresh is None:
        db.rollback()
        return None
    fresh.status = status
    fresh.error_code = code
    fresh.lease_token = None
    db.commit()
    return fresh


# ---------- analysis ----------

def analyze_run(db, run_id, token):
    run = db.query(ClientDeskUnlinkedRun).filter_by(id=run_id, lease_token=token).first()
    if run is None:
        return None
    thread = db.query(ClientDeskUnlinkedThread).filter_by(id=run.thread_id).first()
    if thread is not None and thread.channel == wa.CHANNEL:
        return wa.analyze_run(db, run, token, thread)
    if not tm_enabled():
        return _finish(db, run, token, "skipped_gate", "not_eligible")
    action = "write" if run.trigger_type == "manual" else "read"
    scope = _pilot_scope(db, action)
    if thread is None or scope is None or thread.status not in ACTIVE_STATES or thread.item_id is None:
        return _finish(db, run, token, "skipped_gate", "not_eligible")
    uid, source_id = scope
    if uid != thread.user_id:
        return _finish(db, run, token, "skipped_gate", "owner_changed")
    item = authorized_item(db, uid, source_id, thread)
    if item is None:
        return _finish(db, run, token, "skipped_gate", "authority_revoked")

    raw_messages = safe_messages(db, item)
    if not raw_messages:
        return _finish(db, run, token, "skipped_gate", "no_message_evidence")
    seen_now, _, _ = _inbound_watermark(db, item, raw_messages)
    messages = [{"key": f"M-{m['_original_position'] + 1}", "dir": m.get("dir"),
                 "at": m.get("at"), "text": m.get("text")} for m in raw_messages]
    wire, refs = core.build_daily_pack(buyer=item.snapshot.get("buyer") or {}, messages=messages,
                                       biz_date=run.biz_date)
    prompt = core.protocol_text("unlinked_daily_v1.md") + "\n\n" + wire
    run.pack_hash = core.digest(prompt)
    run.watermark = seen_now or thread.seen_watermark
    run.source_dependencies = _evidence_dependencies(thread, raw_messages)

    cfg = get_settings()
    snapshot = prepare_text_chat(db, cfg.CLIENT_DESK_UNLINKED_PRESET_NAME, MAX_OUTPUT_TOKENS, deepseek_json=True)
    if snapshot.provider.id not in cfg.CLIENT_DESK_ALLOWED_PROVIDER_IDS or snapshot.preset.system_prompt:
        return _finish(db, run, token, "failed", "unapproved_preset")
    db.commit()
    try:
        response = chat(
            db,
            preset_name=cfg.CLIENT_DESK_UNLINKED_PRESET_NAME,
            messages=[{"role": "user", "content": prompt}],
            caller_module="client_desk_unlinked",
            caller_user_id=uid,
            snapshot_mode="metadata",
            timeout_sec=CALL_TIMEOUT_SEC,
            enforce_total_timeout=True,
            trusted_text_snapshot=snapshot,
        )
    except Exception as exc:  # noqa: BLE001 - outcome unknown; never auto-retry
        return _finish(db, run, token, "ambiguous", f"call_{type(exc).__name__}"[:64])

    if response.get("finish_reason") in ("length", "max_tokens"):
        return _finish(db, run, token, "failed", "truncated")
    try:
        result = core.validate_daily(response.get("content"), refs)
    except core.InvalidResult as exc:
        return _finish(db, run, token, "failed", exc.code)

    # Lock live pilot and actor first, in the same order as scan and user writes.
    if _pilot_scope(db, action) != (uid, source_id):
        return _finish(db, run, token, "discarded_stale", "authority_revoked")
    # Write-back: re-check the thread, the authority and the lease under lock.
    lock_source(db, source_id)
    thread = (db.query(ClientDeskUnlinkedThread).filter_by(id=run.thread_id)
              .populate_existing().with_for_update().first())
    if thread is None or thread.status not in ACTIVE_STATES:
        return _finish(db, run, token, "discarded_stale", "thread_changed")
    current_item = authorized_item(db, uid, source_id, thread)
    if current_item is None:
        return _finish(db, run, token, "discarded_stale", "authority_revoked")
    if not evidence_current(db, thread, current_item, run):
        return _finish(db, run, token, "discarded_stale", "content_changed")
    fresh = (db.query(ClientDeskUnlinkedRun).filter_by(id=run_id)
             .populate_existing().with_for_update().first())
    if fresh is None or fresh.lease_token != token or fresh.status != "running":
        # The lease was recovered or the run was wiped; that path owns the row now.
        db.rollback()
        return None
    apply_result(thread, run, result, response)
    db.commit()
    return run


def apply_result(thread, run, result, response):
    """Store a validated result on the run and advance the thread's processed watermark."""
    run.token_usage = {"input": response.get("tokens_prompt") or 0,
                       "output": response.get("tokens_completion") or 0}
    run.is_business_lead = result["is_business_lead"]
    run.intent_stage = result["intent_stage"]
    run.urgency = result["urgency"]
    run.one_line_summary = result["one_line_summary"]
    run.missing_or_next_action = result["missing_or_next_action"]
    run.breakthrough_angle = result["breakthrough_angle"]
    run.draft_message = result["draft_message"]
    run.extracted_clues = result["extracted_clues"]
    run.cites = result["cites"]
    run.needs_review = result["needs_review"]
    run.status = "succeeded" if result["is_business_lead"] else "skipped_non_lead"
    run.error_code = None
    run.lease_token = None
    # Only a watermark newer than what was processed advances the thread, so an
    # older queued run cannot undo a later 'handled' action.
    prior, mine = core.as_pair(thread.done_watermark), core.as_pair(run.watermark)
    if mine is not None and (prior is None or mine > prior):
        thread.done_watermark = list(mine)
        thread.handled_at = None  # new inbound content is news to the rep again


# ---------- weekly review ----------

def window_for_previous_week(today):
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(days=7), this_monday


def weekly_live_threads(db, uid, source_id, run_ids):
    live = set()
    for tid, run_id in run_ids.items():
        thread = (db.query(ClientDeskUnlinkedThread).filter_by(id=int(tid), user_id=uid)
                  .populate_existing().first())
        if thread is None or thread.status not in ACTIVE_STATES:
            continue
        item = thread_source(db, uid, thread, source_id)
        if item is None:
            continue
        run = (db.query(ClientDeskUnlinkedRun)
               .filter_by(id=run_id, thread_id=thread.id, user_id=uid, status="succeeded")
               .populate_existing().first())
        if run is not None and run_evidence_current(db, thread, item, run):
            live.add(tid)
    return live


def _weekly_scope_or_none(db, uid, action="read"):
    tm = _pilot_scope(db, action) if tm_enabled() else None
    source_id = tm[1] if tm is not None and tm[0] == uid else None
    wa_ok = wa.user_enabled(db, uid, action)
    return None if source_id is None and not wa_ok else (source_id, wa_ok)


def weekly_scope(db, uid, action="read"):
    """(TM source id or None, WhatsApp allowed) for one rep; 403 when neither channel is open."""
    scope = _weekly_scope_or_none(db, uid, action)
    if scope is None:
        raise HTTPException(403, "当前账号未开通未绑定线索")
    return scope


def generate_weekly(db, uid, *, today=None, action="read"):
    """Summarise the previous full Beijing week from daily summaries only (Reduce step)."""
    cfg = get_settings()
    today = today or beijing_today()
    scope = weekly_scope(db, uid, action)
    source_id = scope[0]
    if source_id is not None:
        lock_source(db, source_id)
    start, end = window_for_previous_week(today)

    review = (db.query(ClientDeskUnlinkedReview)
              .filter_by(user_id=uid, week_start_date=start).populate_existing().with_for_update().first())
    if review is None:
        review = ClientDeskUnlinkedReview(
            user_id=uid, week_start_date=start,
            window_start=datetime.combine(start, datetime.min.time()),
            window_end=datetime.combine(end, datetime.min.time()), status="running", attempts=0)
        db.add(review)
        db.flush()
    now = beijing_now()
    if review.lease_expires_at is not None and review.lease_expires_at > now:
        raise HTTPException(409, "本周梳理正在生成")
    if (review.attempts or 0) >= WEEKLY_ATTEMPTS_PER_WEEK:
        raise HTTPException(429, "本周梳理次数已用完")

    rows = (db.query(ClientDeskUnlinkedRun, ClientDeskUnlinkedThread)
            .join(ClientDeskUnlinkedThread, ClientDeskUnlinkedThread.id == ClientDeskUnlinkedRun.thread_id)
            .filter(ClientDeskUnlinkedRun.user_id == uid,
                    ClientDeskUnlinkedRun.status == "succeeded",
                    ClientDeskUnlinkedRun.biz_date >= start, ClientDeskUnlinkedRun.biz_date < end,
                    ClientDeskUnlinkedThread.status.in_(ACTIVE_STATES))
            .order_by(ClientDeskUnlinkedRun.id.desc()).all())
    latest = {}
    for run, thread in rows:
        latest.setdefault(thread.id, (run, thread))

    companies = matchable_companies(db, uid)
    run_ids, lines, company_by_thread = {}, [], {}
    budget = core.MAX_WEEKLY_CHARS - 2_000
    for run, thread in latest.values():
        if len(run_ids) >= core.MAX_WEEKLY_THREADS:
            break
        item = thread_source(db, uid, thread, source_id)
        if item is None or not run_evidence_current(db, thread, item, run):
            continue
        tid = str(thread.id)
        match = core.weak_match(thread.display_name, companies)
        block = (f"[thread {tid}] 买家：{core.escape_external(thread.display_name)} · 阶段：{run.intent_stage}"
                 f" · 紧急度：{run.urgency} · 候选公司：{match['company_id'] if match else '无'}\n"
                 f"  前情：{core.escape_external(run.one_line_summary)}\n"
                 f"  待办：{core.escape_external(run.missing_or_next_action)}\n"
                 f"  突破点：{core.escape_external(run.breakthrough_angle)}")
        if sum(len(x) for x in lines) + len(block) > budget:
            break  # the rest wait for the next run; never fail the whole week
        lines.append(block)
        run_ids[tid] = run.id
        company_by_thread[tid] = {match["company_id"]} if match else set()

    review.included_thread_ids = sorted(run_ids, key=int)
    review.source_dependencies = {"protocol": core.PROTOCOL_VERSION, "run_ids": run_ids}
    review.overview_md = None
    review.missed_tasks = review.breakthrough_leads = []
    review.likely_existing_customers = review.cleanup_candidates = []
    review.lease_token = None
    review.lease_expires_at = None
    if not run_ids:
        review.status = "succeeded"
        review.error_code = None
        review.overview_md = "本周没有需要梳理的未绑定线索。"
        db.commit()
        return review

    prompt = (core.protocol_text("unlinked_weekly_v1.md")
              + "\n\n<external_data>\n" + "\n".join(lines) + "\n</external_data>")
    snapshot = prepare_text_chat(db, cfg.CLIENT_DESK_UNLINKED_PRESET_NAME, MAX_WEEKLY_OUTPUT_TOKENS, deepseek_json=True)
    if snapshot.provider.id not in cfg.CLIENT_DESK_ALLOWED_PROVIDER_IDS or snapshot.preset.system_prompt:
        review.status = "failed"
        review.error_code = "unapproved_preset"
        db.commit()
        return review
    review.attempts = (review.attempts or 0) + 1
    review.status = "running"
    review_id, token = review.id, secrets.token_hex(16)
    review.lease_token = token
    review.lease_expires_at = now + LEASE
    db.commit()
    call_error = None
    try:
        response = chat(
            db,
            preset_name=cfg.CLIENT_DESK_UNLINKED_PRESET_NAME,
            messages=[{"role": "user", "content": prompt}],
            caller_module="client_desk_unlinked",
            caller_user_id=uid,
            snapshot_mode="metadata",
            timeout_sec=CALL_TIMEOUT_SEC,
            enforce_total_timeout=True,
            trusted_text_snapshot=snapshot,
        )
    except Exception as exc:  # noqa: BLE001
        call_error = f"call_{type(exc).__name__}"[:64]

    # Only the winner of the lease may publish. Preserve the original input set
    # for the overview decision even if an ignore action removed stored entries.
    scope_current = _weekly_scope_or_none(db, uid, action) == scope
    if scope_current and source_id is not None:
        lock_source(db, source_id)
    review = (db.query(ClientDeskUnlinkedReview).filter_by(id=review_id)
              .populate_existing().with_for_update().one())
    if review.lease_token != token:
        db.rollback()
        return review
    review.lease_token = None
    review.lease_expires_at = None
    live = weekly_live_threads(db, uid, source_id, run_ids) if scope_current else set()
    if not live:
        review.included_thread_ids = []
        review.source_dependencies = {"protocol": core.PROTOCOL_VERSION, "run_ids": {}}
        review.status = "discarded_stale"
        review.error_code = "evidence_changed" if scope_current else "authority_revoked"
        db.commit()
        return review
    if call_error or response.get("finish_reason") in ("length", "max_tokens"):
        review.status = "ambiguous" if call_error else "failed"
        review.error_code = call_error or "truncated"
        db.commit()
        return review
    review.token_usage = {"input": response.get("tokens_prompt") or 0,
                          "output": response.get("tokens_completion") or 0}
    try:
        result = core.validate_weekly(response.get("content"), live, {k: company_by_thread[k] for k in live})
    except core.InvalidResult as exc:
        review.status = "failed"
        review.error_code = exc.code
        db.commit()
        return review
    review.included_thread_ids = sorted(live, key=int)
    review.source_dependencies = {
        "protocol": core.PROTOCOL_VERSION, "run_ids": {tid: run_ids[tid] for tid in live},
    }
    review.overview_md = result["overview_md"] if live == run_ids.keys() else None
    review.missed_tasks = result["missed_tasks"]
    review.breakthrough_leads = result["breakthrough_leads"]
    review.likely_existing_customers = result["likely_existing_customers"]
    review.cleanup_candidates = result["cleanup_candidates"]
    review.status = "succeeded"
    review.error_code = None
    db.commit()
    return review


# ---------- scheduled entries ----------

def weekly_for_reps(session_factory, today=None):
    """One weekly review per rep with an open channel (TM pilot and WhatsApp holders). Returns {uid: status}."""
    uids = set(wa.owners(session_factory))
    if tm_enabled():
        with session_factory() as db:
            scope = _pilot_scope(db)
        if scope is not None:
            uids.add(scope[0])
    results = {}
    for uid in sorted(uids):
        with session_factory() as db:
            try:
                results[uid] = generate_weekly(db, uid, today=today).status
            except HTTPException as exc:
                db.rollback()
                results[uid] = f"skipped_{exc.status_code}"
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                logger.warning("Unlinked weekly failed: %s", type(exc).__name__)
                print(f"[CLIENT_DESK_UNLINKED] weekly failed: {type(exc).__name__}", flush=True)
                results[uid] = "internal_error"
    return results


def scan_for_pilot(session_factory, quota):
    if not tm_enabled():
        return 0
    with session_factory() as db:
        scope = _pilot_scope(db)
        if scope is None:
            return 0
        uid, source_id = scope
        try:
            sync_threads(db, uid, source_id)
            queued = enqueue_daily(db, uid, source_id, quota=quota)
            db.commit()
            return queued
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning("Unlinked scan failed: %s", type(exc).__name__)
            print(f"[CLIENT_DESK_UNLINKED] scan failed: {type(exc).__name__}", flush=True)
            return 0
