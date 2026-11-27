"""WhatsApp channel of the B track: unlinked one-to-one chats on explicitly authorised numbers.

WhatsApp numbers can carry private chats, so the gate is narrower than TM:
only the number's own holder, only accounts whose holder switched on
`unlinked_ai_allowed` (on top of consent, CRM sharing and AI egress), no
groups, no self/platform chats, no colleague numbers, and nothing that already
has a link in the private-sea desk (linked, imported or ignored).
Authority is re-checked before the model call and again under lock before
any write, exactly like the TM path.
"""

import logging
import re
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func

from app.ai.service import chat
from app.ai.text_snapshot import prepare_text_chat
from app.client_desk.access import require_enabled
from app.client_desk.link_service import _personal_jid, non_customer_reason
from app.client_desk.models import ClientDeskUnlinkedRun, ClientDeskUnlinkedThread, ClientDeskWaLink
from app.core.config import get_settings
from app.core.time import beijing_today
from app.whatsapp.access import require_body
from app.whatsapp.models import WhatsAppAccount, WhatsAppConversation, WhatsAppMessage

from . import core

logger = logging.getLogger("commission.client_desk.unlinked")

CHANNEL = "whatsapp"
MESSAGE_WINDOW = 60
RECENT_DAYS = 1  # yesterday and today (Beijing); older chats are never scanned
_STOPPED = ("revoked", "revoking", "revoke_pending", "paused", "blocked", "expired", "reconnect_required")
_INBOUND = ("in", "inbound")


def enabled():
    cfg = get_settings()
    return bool(cfg.CLIENT_DESK_UNLINKED_ENABLED and cfg.CLIENT_DESK_UNLINKED_WA_ENABLED)


def _message_time():
    return func.coalesce(WhatsAppMessage.sent_at, WhatsAppMessage.received_at)


def account_deps(account):
    return {"account_uid": account.account_uid, "consent_version": account.consent_version,
            "session_generation": account.session_generation}


def _flags_on(account):
    return bool(account.unlinked_ai_allowed and account.consent_state == "active" and account.crm_shared
                and account.ai_egress_allowed and account.status not in _STOPPED)


def owner_allowed(db, account, action="read", *, fresh=False):
    """The holder must be enrolled in the private-sea desk and still able to read this number's bodies."""
    uid = account.ark_user_id
    try:
        require_enabled(db, uid, write=action == "write")
        require_body(db, account, uid, crm=True, purpose="client_desk", fresh=fresh)
    except (HTTPException, PermissionError):
        return False
    return True


def lock_account(db, account_uid, *, shared=False):
    """Exclusive for user actions and result write-back; shared for the scan, so message ingest is not stalled."""
    return (db.query(WhatsAppAccount).filter_by(account_uid=account_uid)
            .populate_existing().with_for_update(read=shared).first())


def live_account(db, uid, account_uid, action="read", *, lock=False):
    account = lock_account(db, account_uid) if lock else (
        db.query(WhatsAppAccount).filter_by(account_uid=account_uid).populate_existing().first())
    if account is None or account.ark_user_id != uid or not _flags_on(account):
        return None
    return account if owner_allowed(db, account, action, fresh=lock) else None


def eligible_accounts(db, uid=None, action="read"):
    query = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.unlinked_ai_allowed.is_(True), WhatsAppAccount.consent_state == "active",
        WhatsAppAccount.crm_shared.is_(True), WhatsAppAccount.ai_egress_allowed.is_(True),
        WhatsAppAccount.status.notin_(_STOPPED))
    if uid is not None:
        query = query.filter(WhatsAppAccount.ark_user_id == uid)
    return [a for a in query.order_by(WhatsAppAccount.id).all() if owner_allowed(db, a, action)]


def user_enabled(db, uid, action="read"):
    return enabled() and bool(eligible_accounts(db, uid, action))


def _digits(value):
    return re.sub(r"\D", "", str(value or ""))


def _identity(account):
    payload = account.raw_payload if isinstance(account.raw_payload, dict) else {}
    identity = payload.get("self_identity")
    return identity if isinstance(identity, dict) else {}


def _identity_verified(account):
    """The connector reported this session's own PN/LID; without it a self chat cannot be told apart."""
    identity = _identity(account)
    return (account.provider == "baileys" and account.status != "reconnect_required"
            and bool(identity.get("pn_jid") or identity.get("lid_jid"))
            and str(identity.get("session_generation")) == str(account.session_generation))


def internal_numbers(db):
    """Every number and LID bound to the platform is a colleague, never a lead."""
    found = set()
    for phone, payload in db.query(WhatsAppAccount.phone_number, WhatsAppAccount.raw_payload).all():
        if len(d := _digits(phone)) >= 6:
            found.add(d)
        identity = payload.get("self_identity") if isinstance(payload, dict) else None
        for key in ("pn_jid", "lid_jid"):
            jid = _personal_jid(identity.get(key)) if isinstance(identity, dict) else None
            if jid:
                found.add(jid)
                if jid.endswith("@s.whatsapp.net"):
                    found.add(jid.split("@", 1)[0])
    return found


def excluded(conv, account, internal):
    """Fail closed: groups, self/platform chats, colleagues, and every chat of an unverifiable session."""
    if conv.is_group or not _identity_verified(account) or non_customer_reason(conv, account):
        return True
    jid = _personal_jid(conv.chat_id)
    if jid is None:
        return True
    identity = _identity(account)
    if jid in {_personal_jid(identity.get("pn_jid")), _personal_jid(identity.get("lid_jid"))}:
        return True
    keys = {jid, _digits(conv.contact_phone)}
    if jid.endswith("@s.whatsapp.net"):
        keys.add(jid.split("@", 1)[0])
    return bool((keys - {""}) & internal)


def active_link(db, account_uid, conversation_uid, *, lock=False):
    query = db.query(ClientDeskWaLink).filter_by(
        account_uid=account_uid, conversation_uid=conversation_uid, deleted_at=None)
    if lock:
        query = query.with_for_update()
    return query.first()


def authorized_conversation(db, uid, thread, action="read", *, lock=False, allow_link=()):
    """Return (account, conversation) while the thread may still be shown or written; else None."""
    if thread.channel != CHANNEL or not enabled():
        return None
    account = live_account(db, uid, thread.source_account_uid, action, lock=lock)
    if account is None:
        return None
    query = db.query(WhatsAppConversation).filter_by(
        account_uid=account.account_uid, conversation_uid=thread.thread_key, is_group=False)
    conv = (query.populate_existing().with_for_update() if lock else query).first()
    if conv is None or excluded(conv, account, internal_numbers(db)):
        return None
    link = active_link(db, account.account_uid, conv.conversation_uid, lock=lock)
    if link is not None and link.link_type not in allow_link:
        return None
    return account, conv


def display_name(conv):
    return (conv.contact_name or "")[:160] or masked_phone(conv)


def masked_phone(conv):
    digits = _digits(conv.contact_phone)
    return f"+{digits[:3]}****{digits[-4:]}" if len(digits) >= 8 else None


def load_messages(db, account_uid, conversation_uid, *, lock=False):
    """Newest MESSAGE_WINDOW live messages, oldest first."""
    query = (db.query(WhatsAppMessage)
             .filter(WhatsAppMessage.account_uid == account_uid,
                     WhatsAppMessage.conversation_uid == conversation_uid,
                     WhatsAppMessage.deleted_at.is_(None), _message_time().isnot(None))
             .order_by(_message_time().desc(), WhatsAppMessage.id.desc())
             .limit(MESSAGE_WINDOW).populate_existing())
    rows = (query.with_for_update(read=True) if lock else query).all()
    return list(reversed(rows))


def _text(row):
    return row.content_text or row.content_preview or f"[非文本消息:{row.content_type}]"


def watermark(rows):
    inbound = [r for r in rows if r.direction in _INBOUND]
    if not inbound:
        return None
    newest = max(inbound, key=lambda r: r.id)
    return [int(newest.id), int(newest.source_revision or 0)]


def evidence(account, rows):
    return {"account": account_deps(account),
            "messages": [[int(r.id), int(r.source_revision or 0)] for r in rows]}


def evidence_current(db, thread, run, account, *, lock=False):
    """The analysed messages still exist unchanged and the grant they were read under is current.

    A consent change keeps the thread visible but makes this output stale.
    """
    deps = run.source_dependencies or {}
    if deps.get("account") != account_deps(account):
        return False
    saved = deps.get("messages")
    if not isinstance(saved, list) or not saved:
        return False
    ids = [pair[0] for pair in saved]
    query = (db.query(WhatsAppMessage.id, WhatsAppMessage.source_revision)
             .filter(WhatsAppMessage.account_uid == thread.source_account_uid,
                     WhatsAppMessage.conversation_uid == thread.thread_key,
                     WhatsAppMessage.id.in_(ids), WhatsAppMessage.deleted_at.is_(None)))
    rows = (query.with_for_update(read=True) if lock else query).all()
    current = {r.id: int(r.source_revision or 0) for r in rows}
    return all(current.get(mid) == rev for mid, rev in saved)


# ---------- sync ----------

def _thread_row(db, uid, account_uid, key):
    return (db.query(ClientDeskUnlinkedThread)
            .filter_by(user_id=uid, channel=CHANNEL, source_account_uid=account_uid, thread_key=key)
            .populate_existing().with_for_update().first())


def _reconcile_links(db, account):
    """Mirror desk links made elsewhere: linked threads leave the track, removed links bring them back."""
    from .service import wipe_thread

    uid = account.ark_user_id
    for thread in (db.query(ClientDeskUnlinkedThread)
                   .filter_by(user_id=uid, channel=CHANNEL, source_account_uid=account.account_uid)
                   .populate_existing().with_for_update().all()):
        link = active_link(db, account.account_uid, thread.thread_key)
        kind = link.link_type if link else None
        if kind in ("linked", "imported") and thread.status != "linked":
            thread.status = "linked"
            thread.linked_company_id = link.company_id
        elif kind == "ignored" and thread.status != "ignored":
            wipe_thread(db, uid, thread)
        elif kind is None and thread.status in ("linked", "ignored"):
            thread.status = "active"
            thread.linked_company_id = None
            thread.done_watermark = None
            thread.handled_at = None
            conv = (db.query(WhatsAppConversation)
                    .filter_by(account_uid=account.account_uid, conversation_uid=thread.thread_key).first())
            if conv is not None:
                thread.display_name = display_name(conv)


def _link_threads(db, account_uid, conversation_uid):
    return (db.query(ClientDeskUnlinkedThread)
            .filter_by(channel=CHANNEL, source_account_uid=account_uid, thread_key=conversation_uid)
            .order_by(ClientDeskUnlinkedThread.id).populate_existing().with_for_update().all())


def lock_link_targets(db, account_uid, conversation_uid):
    """Take the account, then the B-track thread rows, before a desk link write locks the conversation."""
    lock_account(db, account_uid)
    _link_threads(db, account_uid, conversation_uid)


def apply_link(db, account_uid, conversation_uid, link_type, company_id=None):
    """Called in the same transaction as any desk link write, so marking not-a-customer clears AI output at once."""
    from .service import wipe_thread

    for thread in _link_threads(db, account_uid, conversation_uid):
        if link_type == "ignored" and thread.status != "ignored":
            wipe_thread(db, thread.user_id, thread)
        elif link_type in ("linked", "imported") and thread.status != "linked":
            thread.status = "linked"
            thread.linked_company_id = int(company_id) if company_id else None


def sync_account(db, account, *, day=None):
    """Refresh every recently active, eligible chat of one account. Returns the number of threads touched."""
    day = day or beijing_today()
    account = lock_account(db, account.account_uid, shared=True)
    if account is None or not _flags_on(account) or not owner_allowed(db, account):
        return 0
    uid = account.ark_user_id
    _reconcile_links(db, account)
    since = datetime.combine(day - timedelta(days=RECENT_DAYS), datetime.min.time())
    recent = [uid_ for (uid_,) in (
        db.query(WhatsAppMessage.conversation_uid)
        .filter(WhatsAppMessage.account_uid == account.account_uid,
                WhatsAppMessage.direction.in_(_INBOUND), WhatsAppMessage.deleted_at.is_(None),
                WhatsAppMessage.conversation_uid.isnot(None), _message_time() >= since)
        .distinct().all())]
    if not recent:
        db.flush()
        return 0
    internal = internal_numbers(db)
    deps = {"account": account_deps(account)}
    touched = 0
    convs = (db.query(WhatsAppConversation)
             .filter(WhatsAppConversation.account_uid == account.account_uid,
                     WhatsAppConversation.conversation_uid.in_(recent),
                     WhatsAppConversation.is_group.is_(False))
             .order_by(WhatsAppConversation.id).all())
    for conv in convs:
        if excluded(conv, account, internal) or active_link(db, account.account_uid, conv.conversation_uid):
            continue
        rows = load_messages(db, account.account_uid, conv.conversation_uid)
        seen = watermark(rows)
        if seen is None:
            continue
        thread = _thread_row(db, uid, account.account_uid, conv.conversation_uid)
        if thread is None:
            thread = ClientDeskUnlinkedThread(user_id=uid, channel=CHANNEL, source_account_uid=account.account_uid,
                                              thread_key=conv.conversation_uid, status="active")
            db.add(thread)
            db.flush()
        if thread.status in ("linked", "ignored"):
            continue
        thread.source_dependencies = deps
        from .worker import _latest_succeeded, wipe_run_content

        latest = _latest_succeeded(db, thread.id)
        if latest is not None and not evidence_current(db, thread, latest, account):
            wipe_run_content(latest, "stale")
            latest.error_code = "content_changed"
        last = rows[-1]
        newest_in = max((r for r in rows if r.direction in _INBOUND), key=lambda r: r.id)
        thread.item_id = conv.id
        thread.display_name = display_name(conv)
        thread.last_message_at = newest_in.sent_at or newest_in.received_at  # shown as 「最后入站」
        thread.last_direction = "inbound" if last.direction in _INBOUND else "outbound"
        thread.seen_watermark = seen
        touched += 1
    db.flush()
    return touched


def scan(session_factory, quota):
    """Scheduled entry: sync and enqueue every eligible account. One account never stops another."""
    if not enabled():
        return 0
    from .worker import enqueue_daily

    with session_factory() as db:
        accounts = [(a.account_uid, a.ark_user_id) for a in eligible_accounts(db)]
    queued = 0
    for account_uid, uid in accounts:
        with session_factory() as db:
            try:
                account = db.query(WhatsAppAccount).filter_by(account_uid=account_uid).first()
                if account is None:
                    continue
                sync_account(db, account)
                queued += enqueue_daily(db, uid, None, quota=quota, channel=CHANNEL)
                db.commit()
            except Exception as exc:  # noqa: BLE001 - recorded, next account continues
                db.rollback()
                logger.warning("Unlinked WhatsApp scan failed for one account: %s", type(exc).__name__)
                print(f"[CLIENT_DESK_UNLINKED] whatsapp scan failed: {type(exc).__name__}", flush=True)
    return queued


def owners(session_factory):
    if not enabled():
        return []
    with session_factory() as db:
        return sorted({a.ark_user_id for a in eligible_accounts(db)})


# ---------- analysis ----------

def analyze_run(db, run, token, thread):
    from .worker import ACTIVE_STATES as OPEN, CALL_TIMEOUT_SEC, MAX_OUTPUT_TOKENS, _finish

    action = "write" if run.trigger_type == "manual" else "read"
    if not enabled() or thread.status not in OPEN:
        return _finish(db, run, token, "skipped_gate", "not_eligible")
    uid = thread.user_id
    handle = authorized_conversation(db, uid, thread, action)
    if handle is None:
        return _finish(db, run, token, "skipped_gate", "authority_revoked")
    account, conv = handle
    rows = load_messages(db, account.account_uid, conv.conversation_uid)
    if not rows:
        return _finish(db, run, token, "skipped_gate", "no_message_evidence")
    messages = [{"key": f"M-{i + 1}", "dir": "buyer" if r.direction in _INBOUND else "seller",
                 "at": (r.sent_at or r.received_at).strftime("%Y-%m-%d %H:%M"), "text": _text(r)}
                for i, r in enumerate(rows)]
    wire, refs = core.build_daily_pack(buyer={"name": display_name(conv)}, messages=messages,
                                       biz_date=run.biz_date)
    packed = [rows[int(key[2:]) - 1] for key in refs]
    prompt = core.protocol_text("unlinked_daily_v1.md") + "\n\n" + wire
    run.pack_hash = core.digest(prompt)
    run.watermark = watermark(rows) or thread.seen_watermark
    run.source_dependencies = evidence(account, packed)

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
        logger.warning("Unlinked WhatsApp run %s model call failed: %s", run.id, type(exc).__name__)
        print(f"[CLIENT_DESK_UNLINKED] whatsapp run {run.id} model call failed: {type(exc).__name__}", flush=True)
        return _finish(db, run, token, "ambiguous", f"call_{type(exc).__name__}"[:64])

    if response.get("finish_reason") in ("length", "max_tokens"):
        return _finish(db, run, token, "failed", "truncated")
    try:
        result = core.validate_daily(response.get("content"), refs)
    except core.InvalidResult as exc:
        return _finish(db, run, token, "failed", exc.code)

    # Write-back: lock the account first, then the thread, then re-check everything.
    if lock_account(db, thread.source_account_uid) is None:
        return _finish(db, run, token, "discarded_stale", "authority_revoked")
    thread = (db.query(ClientDeskUnlinkedThread).filter_by(id=run.thread_id)
              .populate_existing().with_for_update().first())
    if thread is None or thread.status not in OPEN:
        return _finish(db, run, token, "discarded_stale", "thread_changed")
    current = authorized_conversation(db, uid, thread, action, lock=True)
    if current is None:
        return _finish(db, run, token, "discarded_stale", "authority_revoked")
    if not evidence_current(db, thread, run, current[0], lock=True):
        return _finish(db, run, token, "discarded_stale", "content_changed")
    fresh = (db.query(ClientDeskUnlinkedRun).filter_by(id=run.id)
             .populate_existing().with_for_update().first())
    if fresh is None or fresh.lease_token != token or fresh.status != "running":
        db.rollback()
        return None
    from .worker import apply_result

    apply_result(thread, fresh, result, response)
    db.commit()
    return fresh
