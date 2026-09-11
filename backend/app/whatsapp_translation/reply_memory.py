"""Owner/device scoped inquiry observations and optimistic, idempotent acceptance.

Generation never persists notes. The extension accepts a still-current result in
a separate request. No source chat identifier, complete transcript or draft is
stored. Quotes are bounded, masked excerpts of observed messages only.
"""

import re
import logging
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

from app.auth.models import ArkUser
from app.core.config import get_settings
from app.core.time import beijing_now
from app.whatsapp_translation.models import ReplyInquiry, ReplyRequestRecord
from app.whatsapp_translation.reply_memory_schemas import MemoryCommand
from app.whatsapp_translation.reply_state import error, live_actor
from app.whatsapp_translation.auth import require_supported_extension
from app.whatsapp_translation.errors import WhatsAppTranslationError


MAX_ENTRIES = 80
MAX_INQUIRIES = 100
CONTACT = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\w)(?:\+\d[\d ()-]{7,}\d|\d{10,15})(?!\w)")


def clean_text(value: str) -> str:
    return CONTACT.sub("[contact]", value)


def available():
    settings = get_settings()
    if not settings.WHATSAPP_REPLY_ENABLED or not settings.WHATSAPP_REPLY_MEMORY_ENABLED:
        raise error("reply_memory_disabled", 503)
    return settings


def _owned(db, identity, conversation_id):
    return db.query(ReplyInquiry).filter(
        ReplyInquiry.id == str(conversation_id), ReplyInquiry.user_id == identity.user_id,
        ReplyInquiry.device_id == identity.device_id, ReplyInquiry.expires_at > beijing_now(),
    )


def get_inquiry(db, identity, conversation_id):
    row = _owned(db, identity, conversation_id).first()
    if row is None:
        raise error("reply_memory_not_found", 404)
    return row


def describe(row, *, details=True):
    return {
        "id": row.id, "label": row.label, "revision": row.revision,
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
        "expires_at": row.expires_at.isoformat(),
        "entries": deepcopy(row.entries) if details else [],
    }


def load_for_generation(db, identity, request):
    if request.memory_conversation_id is None:
        return {"entries": [], "instance_id": None}
    available()
    row = get_inquiry(db, identity, request.memory_conversation_id)
    if row.revision != request.memory_revision:
        raise error("reply_memory_conflict")
    entries = deepcopy(row.entries)
    for entry in entries:
        entry["summary"] = effective_summary(entry)
    return {"entries": entries, "instance_id": row.instance_id}


def recheck_revision(db, identity, request, instance_id=None):
    if request.memory_conversation_id is not None:
        if load_for_generation(db, identity, request)["instance_id"] != instance_id:
            raise error("reply_memory_conflict")


def effective_summary(entry):
    return entry["human_note"] if entry["status"] == "human_confirmed" and entry.get("human_note") else entry["summary"]


def build_update(plan, request, prior):
    """Copy unchanged evidence; only current-message evidence can change an entry."""
    entries = deepcopy(prior)
    by_id = {entry["id"]: entry for entry in entries}
    changed = set()
    now = beijing_now().isoformat()
    for change in plan.memory_changes:
        if change.message_index >= len(request.messages):
            raise error("reply_invalid_evidence", 502)
        message = request.messages[change.message_index]
        if change.quote not in message.text:
            raise error("reply_invalid_evidence", 502)
        expected_role = {"need": "customer", "request": "customer", "question": "salesperson", "commitment": "salesperson"}[change.kind]
        if change.status not in {"answered", "cancelled"} and message.role != expected_role:
            raise error("reply_invalid_evidence", 502)
        previous = by_id.get(str(change.replaces)) if change.replaces else None
        if change.replaces and (previous is None or previous["kind"] != change.kind or previous["id"] in changed):
            raise error("reply_invalid_evidence", 502)
        # Human corrections remain authoritative until a person revises them.
        # Surface contradictory new evidence as a separate observation instead.
        if previous and previous.get("human_note"):
            raise error("reply_memory_human_override", 502)
        source = {"request_id": str(request.request_id), "message_index": change.message_index,
                  "role": message.role, "quote": clean_text(change.quote), "observed_at": now}
        entry = {
            "id": previous["id"] if previous else str(uuid4()), "kind": change.kind,
            "status": change.status, "summary": clean_text(change.summary),
            "evidence": ([*previous["evidence"][-2:], source] if previous else [source]),
            "updated_at": now, "human_note": "",
        }
        if previous:
            entries[entries.index(previous)] = entry
            changed.add(previous["id"])
        elif not any(item["kind"] == entry["kind"] and item["status"] == entry["status"]
                     and item["summary"] == entry["summary"] for item in entries):
            entries.append(entry)
    if len(entries) > MAX_ENTRIES:
        raise error("reply_memory_full", 409)
    return entries


def handoff_summary(entries, plan):
    """Derived from observations, never invented tool status or CRM assignments."""
    active = [item for item in entries if item["status"] != "cancelled"]
    return {
        "needs": [effective_summary(item) for item in active if item["kind"] == "need"],
        "open_requests": [effective_summary(item) for item in active if item["kind"] == "request" and item["status"] in {"open", "pending"}],
        "commitments": [{"summary": item["summary"], "status": item["status"]} for item in active if item["kind"] == "commitment"],
        "next_step": plan.action.focus, "completion_signal": plan.action.completion_signal,
        "limitations": "仅为聊天复盘；未查询库存、核价或执行任务。卖方自述不等于核验完成。",
    }


def _write(db, identity, inquiry_id, instance_id, revision, values):
    count = _owned(db, identity, inquiry_id).filter(
        ReplyInquiry.revision == revision, ReplyInquiry.instance_id == instance_id,
    ).update(
        {**values, "revision": revision + 1, "updated_at": beijing_now()}, synchronize_session=False,
    )
    if count != 1:
        db.rollback()
        raise error("reply_memory_conflict")
    db.commit()
    db.expire_all()
    return describe(get_inquiry(db, identity, inquiry_id))


def handle_memory(db, identity, command: MemoryCommand):
    try:
        require_supported_extension(identity)
        return _handle_memory(db, identity, command)
    except WhatsAppTranslationError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logging.getLogger("commission.whatsapp_reply").warning("inquiry operation failed error_type=%s", type(exc).__name__)
        print(f"[WhatsApp reply] inquiry operation failed error_type={type(exc).__name__}", flush=True)
        raise error("reply_unavailable", 503) from None


def _handle_memory(db, identity, command: MemoryCommand):
    settings = available()
    live_actor(db, identity)
    if command.operation == "list":
        rows = db.query(ReplyInquiry).filter(
            ReplyInquiry.user_id == identity.user_id, ReplyInquiry.device_id == identity.device_id,
            ReplyInquiry.expires_at > beijing_now(),
        ).order_by(ReplyInquiry.updated_at.desc(), ReplyInquiry.id).limit(MAX_INQUIRIES).all()
        return {"inquiries": [describe(row, details=False) for row in rows]}
    if command.operation == "create":
        # Serialize the cap and idempotent creation for this owner on MySQL.
        db.query(ArkUser).filter(ArkUser.id == identity.user_id).with_for_update().one()
        existing = db.query(ReplyInquiry).filter(ReplyInquiry.id == str(command.conversation_id)).first()
        if existing:
            result = describe(get_inquiry(db, identity, command.conversation_id))
            db.commit()
            return {"inquiry": result}
        count = db.query(ReplyInquiry).filter(ReplyInquiry.user_id == identity.user_id, ReplyInquiry.expires_at > beijing_now()).count()
        if count >= MAX_INQUIRIES:
            raise error("reply_memory_full")
        now = beijing_now()
        row = ReplyInquiry(id=str(command.conversation_id), instance_id=str(uuid4()), user_id=identity.user_id, device_id=identity.device_id,
                           label=clean_text(command.label) or "新询盘", revision=0, entries=[],
                           created_at=now, updated_at=now,
                           expires_at=now + timedelta(days=settings.WHATSAPP_REPLY_MEMORY_RETENTION_DAYS))
        db.add(row)
        db.commit()
        return {"inquiry": describe(row)}
    row = get_inquiry(db, identity, command.conversation_id)
    inquiry_id, instance_id = row.id, row.instance_id
    if command.operation == "read":
        return {"inquiry": describe(row)}
    if command.operation == "delete":
        count = _owned(db, identity, inquiry_id).filter(
            ReplyInquiry.revision == command.revision, ReplyInquiry.instance_id == instance_id,
        ).delete(synchronize_session=False)
        if count != 1:
            db.rollback()
            raise error("reply_memory_conflict")
        db.commit()
        return {"deleted": True}
    if command.operation == "correct":
        entries = deepcopy(row.entries)
        entry = next((item for item in entries if item["id"] == str(command.entry_id)), None)
        if entry is None:
            raise error("reply_memory_not_found", 404)
        if command.status == "human_completed" and entry["kind"] not in {"commitment", "request", "question"}:
            raise error("reply_invalid_request", 422)
        if command.status == "human_confirmed" and entry["kind"] != "need":
            raise error("reply_invalid_request", 422)
        entry.update(status=command.status, human_note=clean_text(command.note), updated_at=beijing_now().isoformat())
        return {"inquiry": _write(db, identity, inquiry_id, instance_id, command.revision, {"entries": entries, "last_commit_request": None})}
    if row.last_commit_request == str(command.request_id) and row.revision == command.revision + 1:
        return {"inquiry": describe(row)}
    # Cached model response is the only admissible proposal; client cannot replace
    # its contents or save a draft as a customer observation.
    from app.whatsapp_translation.reply_service import _cached_response, _configuration_signature, preset_signature
    record = db.query(ReplyRequestRecord).filter_by(
        user_id=identity.user_id, device_id=identity.device_id, request_id=str(command.request_id),
    ).first()
    if record is None:
        raise error("reply_result_unavailable")
    response = _cached_response(db, identity, record, _configuration_signature(settings, preset_signature(db, settings)))
    if str(response.memory_conversation_id) != inquiry_id or response.memory_revision != command.revision or str(response.memory_instance_id) != instance_id:
        raise error("reply_memory_conflict")
    return {"inquiry": _write(db, identity, inquiry_id, instance_id, command.revision,
                            {"entries": response.memory_update, "last_commit_request": str(command.request_id)})}


def purge_expired_inquiries(db):
    """Existing scheduled housekeeping calls this; expiry is enforced on reads too."""
    count = db.query(ReplyInquiry).filter(ReplyInquiry.expires_at <= beijing_now()).delete(synchronize_session=False)
    db.commit()
    return count
