"""User actions on B-track threads. Every action is scoped to the caller's own threads.

Two channels share these actions: TM (the Alibaba pilot) and WhatsApp (numbers whose
holder allowed the unlinked AI pass). Each action re-checks the thread's own channel.
"""

from datetime import date as Date
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException

from app.alibaba_feed import business_service as feed
from app.alibaba_feed.business_schemas import LinkCreate
from app.client_desk import link_service
from app.client_desk.models import ClientDeskUnlinkedReview, ClientDeskUnlinkedRun, ClientDeskUnlinkedThread
from app.client_desk.private_scope import user_id
from app.core.time import beijing_now

from . import core, wa, worker

CHANNEL = worker.CHANNEL
OPEN = ("active", "prospect")
CHANNEL_KEYS = {worker.CHANNEL: "tm", wa.CHANNEL: "whatsapp"}


def _require_enabled():
    if not (worker.tm_enabled() or wa.enabled()):
        raise HTTPException(503, "未绑定线索尚未启用")


def _pilot_for(db, user, action="read"):
    return feed.require_actor(db, user, action, unlinked=True)


def _scopes(db, user, action="read"):
    """Return (uid, TM source id or None, WhatsApp open) for the caller; raise when no channel is open."""
    _require_enabled()
    uid = user_id(user)
    source_id, tm_error = None, None
    if worker.tm_enabled():
        try:
            _, source_id = _pilot_for(db, user, action)
        except HTTPException as exc:
            tm_error = exc
    wa_ok = wa.user_enabled(db, uid, action)
    if source_id is None and not wa_ok:
        raise tm_error or HTTPException(403, "当前账号未开通未绑定线索")
    return uid, source_id, wa_ok


def _channels(source_id, wa_ok):
    return ([CHANNEL] if source_id is not None else []) + ([wa.CHANNEL] if wa_ok else [])


def _thread(db, uid, thread_id, *, lock=False, channels=(CHANNEL,)):
    query = (db.query(ClientDeskUnlinkedThread)
             .filter(ClientDeskUnlinkedThread.id == thread_id, ClientDeskUnlinkedThread.user_id == uid,
                     ClientDeskUnlinkedThread.channel.in_(channels)))
    if lock:
        query = query.populate_existing().with_for_update()
    row = query.first()
    if row is None:
        raise HTTPException(404, "线索不存在或已失效")
    return row


def _channel_of(db, uid, thread_id):
    row = db.query(ClientDeskUnlinkedThread.channel).filter_by(id=thread_id, user_id=uid).first()
    if row is None:
        raise HTTPException(404, "线索不存在或已失效")
    return row[0]


def _action_thread(db, user, thread_id, *, allow_link=()):
    uid, source_id, wa_ok = _scopes(db, user, "write")
    channel = _channel_of(db, uid, thread_id)
    if channel == wa.CHANNEL and wa_ok:
        thread = _thread(db, uid, thread_id, channels=(wa.CHANNEL,))
        # Same lock order as the worker: account, then thread, then conversation.
        wa.lock_account(db, thread.source_account_uid)
        thread = _thread(db, uid, thread_id, lock=True, channels=(wa.CHANNEL,))
        handle = wa.authorized_conversation(db, uid, thread, "write", lock=True, allow_link=allow_link)
    elif channel == CHANNEL and source_id is not None:
        worker.lock_source(db, source_id)
        thread = _thread(db, uid, thread_id, lock=True)
        handle = worker.authorized_item(db, uid, source_id, thread)
    else:
        raise HTTPException(404, "线索不存在或已失效")
    if handle is None:
        raise HTTPException(404, "线索不存在或已失效")
    return uid, thread, handle


def _latest_run(db, thread_id):
    return (db.query(ClientDeskUnlinkedRun)
            .filter(ClientDeskUnlinkedRun.thread_id == thread_id,
                    ClientDeskUnlinkedRun.status.in_(("succeeded", "skipped_non_lead", "stale", "discarded_stale")))
            .order_by(ClientDeskUnlinkedRun.id.desc()).first())


def _run_payload(run):
    if run is None:
        return None
    return {
        "id": run.id, "biz_date": run.biz_date.isoformat(), "status": run.status,
        "is_business_lead": run.is_business_lead, "intent_stage": run.intent_stage,
        "urgency": run.urgency, "one_line_summary": run.one_line_summary,
        "missing_or_next_action": run.missing_or_next_action,
        "breakthrough_angle": run.breakthrough_angle, "draft_message": run.draft_message,
        "needs_review": bool(run.needs_review), "cites": run.cites or [],
    }


def _payload(thread, *, match=None, run=None, analysis_stale=False, company_hint=None):
    return {
        "id": thread.id, "channel": CHANNEL_KEYS.get(thread.channel, thread.channel),
        "display_name": thread.display_name, "company_hint": company_hint, "status": thread.status,
        "last_message_at": thread.last_message_at.isoformat() if thread.last_message_at else None,
        "last_direction": thread.last_direction,
        "handled_at": thread.handled_at.isoformat() if thread.handled_at else None,
        "next_followup_date": thread.next_followup_date.isoformat() if thread.next_followup_date else None,
        "next_followup_remark": thread.next_followup_remark,
        "remark": thread.remark,
        "match": match,
        "run": _run_payload(run),
        "analysis_stale": analysis_stale,
        "local_timezone": None,
    }


def list_threads(db, user, view="active"):
    uid, source_id, wa_ok = _scopes(db, user)
    rows = (db.query(ClientDeskUnlinkedThread)
            .filter(ClientDeskUnlinkedThread.user_id == uid,
                    ClientDeskUnlinkedThread.channel.in_(_channels(source_id, wa_ok)))
            .all())
    if view == "prospect":
        items = [t for t in rows if t.status == "prospect"]
        items.sort(key=lambda t: (t.next_followup_date or Date.max))
    else:
        items = [t for t in rows if t.status == "active" and t.seen_watermark is not None
                 # Handled threads stay hidden until a new inbound message arrives.
                 and not (t.handled_at is not None and not core.has_newer_inbound(t.seen_watermark, t.done_watermark))]
        items.sort(key=lambda t: (t.last_direction == "inbound", t.last_message_at), reverse=True)
    out = []
    companies = None
    for thread in items:
        item = worker.thread_source(db, uid, thread, source_id)
        if item is None:
            continue
        run = _latest_run(db, thread.id)
        stale = run is not None and (
            run.status in ("stale", "discarded_stale") or not worker.run_evidence_current(db, thread, item, run)
        )
        if companies is None:
            companies = worker.matchable_companies(db, user)
        out.append(_payload(
            thread, match=core.weak_match(thread.display_name, companies),
            run=None if stale else run, analysis_stale=stale,
            company_hint=wa.masked_phone(item[1]) if thread.channel == wa.CHANNEL else None,
        ))
    return {"items": out, "total": len(out)}


def handled(db, user, thread_id):
    _, thread, _ = _action_thread(db, user, thread_id)
    if thread.status not in OPEN:
        raise HTTPException(409, "该线索当前不可处理")
    if thread.seen_watermark is not None:
        thread.done_watermark = thread.seen_watermark
    thread.handled_at = beijing_now()
    db.commit()
    return _payload(thread)


def ignore(db, user, thread_id):
    uid, thread, handle = _action_thread(db, user, thread_id)
    if thread.status == "linked":
        raise HTTPException(409, "已绑定客户的线索不能标为非客户")
    wipe_thread(db, uid, thread)
    if thread.channel == wa.CHANNEL:
        # Same record as 「不是客户」 on the unlinked-conversations page; save_link commits the whole change.
        _save_wa_link(db, user, handle, "ignored")
    else:
        db.commit()
    return _payload(thread)


def _save_wa_link(db, user, handle, link_type, company_id=None):
    account, conv = handle
    return link_service.save_link(db, user, SimpleNamespace(
        account_uid=account.account_uid, conversation_uid=conv.conversation_uid,
        company_id=company_id, link_type=link_type, expected_link_id=None,
    ))


def wipe_thread(db, uid, thread):
    """Mark a thread as not a customer and clear every stored output about it. Does not commit."""
    thread.status = "ignored"
    thread.display_name = None
    thread.country_code = None
    thread.next_followup_date = None
    thread.next_followup_remark = None
    thread.remark = None
    thread.handled_at = None
    thread.done_watermark = None
    # Every stored output about this thread is cleared, including in-flight runs.
    db.query(ClientDeskUnlinkedRun).filter(ClientDeskUnlinkedRun.thread_id == thread.id).update({
        "status": "wiped", "lease_token": None, "one_line_summary": None,
        "missing_or_next_action": None, "breakthrough_angle": None, "draft_message": None,
        "extracted_clues": None, "cites": None, "intent_stage": None, "urgency": None,
    }, synchronize_session=False)
    reviews = (db.query(ClientDeskUnlinkedReview).filter(ClientDeskUnlinkedReview.user_id == uid)
               .order_by(ClientDeskUnlinkedReview.id).populate_existing().with_for_update().all())
    for review in reviews:
        ids = [str(i) for i in (review.included_thread_ids or [])]
        if str(thread.id) not in ids:
            continue
        review.overview_md = None
        review.missed_tasks = _drop(review.missed_tasks, thread.id)
        review.breakthrough_leads = _drop(review.breakthrough_leads, thread.id)
        review.likely_existing_customers = _drop(review.likely_existing_customers, thread.id)
        review.cleanup_candidates = _drop(review.cleanup_candidates, thread.id)
        review.included_thread_ids = [i for i in review.included_thread_ids if str(i) != str(thread.id)]
        deps = review.source_dependencies or {}
        review.source_dependencies = {
            **deps, "run_ids": {
                tid: rid for tid, rid in (deps.get("run_ids") or {}).items() if tid != str(thread.id)
            },
        }


def _drop(items, thread_id):
    return [item for item in (items or []) if str(item.get("thread_id")) != str(thread_id)]


def restore(db, user, thread_id):
    """Undo 'not a customer'. Cleared analysis is not brought back; a new analysis is needed."""
    _, thread, item = _action_thread(db, user, thread_id, allow_link=("ignored",))
    if thread.status != "ignored":
        raise HTTPException(409, "该线索不是非客户状态")
    thread.status = "active"
    thread.done_watermark = None
    if thread.channel == wa.CHANNEL:
        account, conv = item
        thread.display_name = wa.display_name(conv)
        link = wa.active_link(db, account.account_uid, conv.conversation_uid)
        if link is not None and link.link_type == "ignored":
            link_service.delete_link(db, user, link.id)  # commits the restore too
            return _payload(thread)
    else:
        buyer = item.snapshot.get("buyer") or {}
        thread.display_name = str(buyer.get("name") or "")[:160] or None
        thread.country_code = str(buyer.get("country") or "")[:8] or None
    db.commit()
    return _payload(thread)


def set_prospect(db, user, thread_id, next_followup_date, next_followup_remark):
    _, thread, _ = _action_thread(db, user, thread_id)
    if thread.status not in OPEN:
        raise HTTPException(409, "该线索当前不可跟踪")
    remark = (next_followup_remark or "").strip()
    if not next_followup_date or not remark:
        raise HTTPException(422, "请同时填写下次跟进日期与跟进说明")
    thread.status = "prospect"
    thread.next_followup_date = next_followup_date
    thread.next_followup_remark = remark
    db.commit()
    return _payload(thread)


def bind(db, user, thread_id, company_id):
    """Explicit confirmation only. Delegates to the channel's link service, which re-checks scope."""
    uid, source_id, _ = _scopes(db, user, "write")
    if _channel_of(db, uid, thread_id) == wa.CHANNEL:
        return _bind_wa(db, user, thread_id, company_id)
    if source_id is None:
        raise HTTPException(404, "线索不存在或已失效")
    worker.lock_source(db, source_id)
    thread = _thread(db, uid, thread_id, lock=True)
    if thread.status == "linked" and thread.linked_company_id == int(company_id):
        link = feed.current_link_payload(db, user, uid, source_id, thread.item_id, company_id)
        return {**_payload(thread), "link": {**link, "replayed": True}}
    if thread.status not in OPEN or thread.item_id is None:
        raise HTTPException(409, "该线索当前不可绑定")
    if worker.authorized_item(db, uid, source_id, thread) is None:
        raise HTTPException(404, "线索不存在或已失效")
    created = feed.create_link(db, user, LinkCreate(
        item_id=thread.item_id, company_id=int(company_id),
        expected_mapping_version=thread.source_dependencies["mapping_version"],
        client_request_id=f"ul-{thread.id}-{uuid4().hex}",
    ), commit=False)
    thread.status = "linked"
    thread.linked_company_id = int(company_id)
    db.commit()
    return {**_payload(thread), "link": created}


def _bind_wa(db, user, thread_id, company_id):
    current = _thread(db, user_id(user), thread_id, channels=(wa.CHANNEL,))
    if current.status == "linked" and current.linked_company_id == int(company_id):
        link = wa.active_link(db, current.source_account_uid, current.thread_key)
        if link is not None and link.link_type == "linked" and link.company_id == int(company_id):
            return {**_payload(current), "link": {**link_service.link_dto(link), "replayed": True}}
    _, thread, handle = _action_thread(db, user, thread_id)
    if thread.status not in OPEN:
        raise HTTPException(409, "该线索当前不可绑定")
    thread.status = "linked"
    thread.linked_company_id = int(company_id)
    # save_link checks the company is in the caller's private sea, then commits both rows.
    link = _save_wa_link(db, user, handle, "linked", str(company_id))
    return {**_payload(thread), "link": link}


def request_analysis(db, user, thread_id):
    uid, thread, _ = _action_thread(db, user, thread_id)
    if thread.status not in OPEN:
        raise HTTPException(409, "该线索当前不可分析")
    run = worker.enqueue_manual(db, uid, thread)
    db.commit()
    return _run_payload(run) | {"status": run.status}


def list_reviews(db, user, limit=4):
    uid, source_id, _ = _scopes(db, user)
    rows = (db.query(ClientDeskUnlinkedReview)
            .filter(ClientDeskUnlinkedReview.user_id == uid)
            .order_by(ClientDeskUnlinkedReview.week_start_date.desc()).limit(limit).all())
    items = []
    for review in rows:
        live = worker.weekly_live_threads(
            db, uid, source_id, (review.source_dependencies or {}).get("run_ids", {}),
        )

        def keep(entries):
            return [e for e in (entries or []) if str(e.get("thread_id")) in live]

        items.append({
            "id": review.id, "week_start_date": review.week_start_date.isoformat(), "status": review.status,
            "overview_md": review.overview_md if set(map(str, review.included_thread_ids or [])) <= live else None,
            "missed_tasks": keep(review.missed_tasks),
            "breakthrough_leads": keep(review.breakthrough_leads),
            "likely_existing_customers": keep(review.likely_existing_customers),
            "cleanup_candidates": keep(review.cleanup_candidates),
        })
    return {"items": items}


def generate_review(db, user):
    uid, _, _ = _scopes(db, user, "write")
    review = worker.generate_weekly(db, uid, action="write")
    return {"id": review.id, "week_start_date": review.week_start_date.isoformat(), "status": review.status}
