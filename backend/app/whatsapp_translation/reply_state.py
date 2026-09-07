"""Live authorization and cross-worker metadata-only request ownership."""

import hashlib
import json
import threading
import time
from collections import OrderedDict
from datetime import timedelta
from uuid import uuid4

from app.auth.models import ArkUser
from app.auth.service import get_live_user_authorization
from app.core.time import beijing_now
from app.whatsapp_translation.errors import WhatsAppTranslationError
from app.whatsapp_translation.models import ReplyRequestRecord, TranslationDevice


OWNER_ID = str(uuid4())


def error(code: str, status: int = 409) -> WhatsAppTranslationError:
    return WhatsAppTranslationError(status, code, "WhatsApp reply request could not be completed")


def live_actor(db, identity) -> dict:
    # Call only at a transaction boundary: end MySQL REPEATABLE READ snapshots,
    # discard ORM cached rows, then verify current device ownership and human ACL.
    db.rollback()
    db.expire_all()
    device = db.query(TranslationDevice).filter(
        TranslationDevice.id == identity.device_id,
        TranslationDevice.user_id == identity.user_id,
        TranslationDevice.is_active.is_(True),
        TranslationDevice.expires_at > beijing_now(),
    ).first()
    if device is None:
        raise error("device_revoked", 403)
    roles, permissions = get_live_user_authorization(db, identity.user_id)
    if "super_admin" not in roles and "whatsapp_reply:write" not in permissions:
        raise error("reply_permission_denied", 403)
    return {"sub": str(identity.user_id), "roles": roles, "permissions": permissions}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def reserve_request(db, identity, request, settings) -> tuple[ReplyRequestRecord, bool]:
    """Serialize admission per user on MySQL; a unique key backs duplicate safety.

    Expired owners are NEVER taken over. A new explicit request ID is required.
    The lease releases only the user concurrency slot, not the duplicate guard.
    """
    db.rollback()
    db.query(ArkUser).filter(ArkUser.id == identity.user_id).with_for_update().one()
    request_hash = digest(request.model_dump(mode="json"))
    existing = db.query(ReplyRequestRecord).filter_by(
        device_id=identity.device_id, request_id=str(request.request_id),
    ).first()
    if existing is not None:
        if existing.user_id != identity.user_id or existing.payload_hash != request_hash:
            db.rollback()
            raise error("reply_request_conflict")
        db.commit()
        return existing, False
    now = beijing_now()
    own = db.query(ReplyRequestRecord).filter(ReplyRequestRecord.user_id == identity.user_id)
    if own.filter(ReplyRequestRecord.status == "pending", ReplyRequestRecord.lease_until > now).count():
        db.rollback()
        raise error("reply_busy", 429)
    if own.filter(ReplyRequestRecord.created_at >= now - timedelta(minutes=1)).count() >= settings.WHATSAPP_REPLY_RATE_PER_MINUTE:
        db.rollback()
        raise error("reply_rate_limited", 429)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if own.filter(ReplyRequestRecord.created_at >= day_start).count() >= settings.WHATSAPP_REPLY_DAILY_REQUESTS:
        db.rollback()
        raise error("reply_daily_quota_exceeded", 429)
    row = ReplyRequestRecord(
        user_id=identity.user_id, device_id=identity.device_id,
        request_id=str(request.request_id), payload_hash=request_hash, owner_id=OWNER_ID,
        status="pending", input_chars=sum(len(item.text) for item in request.messages) + len(request.draft_intent) + len(request.goal),
        created_at=now, lease_until=now + timedelta(seconds=settings.WHATSAPP_REPLY_TIMEOUT_SECONDS + 10),
        source_revisions=[], timings_ms={},
    )
    db.add(row)
    db.commit()
    return row, True


def finish_request(db, row_id: int, *, status: str, sources=(), timings=None, error_code=None):
    db.rollback()
    db.query(ReplyRequestRecord).filter(
        ReplyRequestRecord.id == row_id, ReplyRequestRecord.owner_id == OWNER_ID,
    ).update({
        "status": status, "finished_at": beijing_now(), "error_code": error_code,
        "source_revisions": [{"document_id": item["document_id"], "revision_id": item["revision_id"]} for item in sources],
        "timings_ms": timings or {},
    }, synchronize_session=False)
    db.commit()


class EphemeralReplyCache:
    """Bounded memory only, no session data in disk/Redis; no cost retry on miss."""

    def __init__(self, max_entries=128, ttl=120):
        self.max_entries, self.ttl = max_entries, ttl
        self._values = OrderedDict()
        self._lock = threading.Lock()
        self._timer = None

    def _prune(self):
        cutoff = time.monotonic() - self.ttl
        for key in [key for key, value in self._values.items() if value[0] < cutoff]:
            self._values.pop(key, None)

    def _schedule_expiry(self):
        if self._timer is None and self._values:
            next_expiry = min(value[0] for value in self._values.values()) + self.ttl
            self._timer = threading.Timer(max(0.001, next_expiry - time.monotonic()), self._expire)
            self._timer.daemon = True
            self._timer.start()

    def _expire(self):
        with self._lock:
            self._timer = None
            self._prune()
            self._schedule_expiry()

    def put(self, key, value):
        with self._lock:
            self._prune()
            self._values[key] = (time.monotonic(), value)
            while len(self._values) > self.max_entries:
                self._values.popitem(last=False)
            self._schedule_expiry()

    def get(self, key):
        with self._lock:
            self._prune()
            entry = self._values.get(key)
            return entry[1] if entry else None

    def clear(self):
        with self._lock:
            self._values.clear()
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


reply_cache = EphemeralReplyCache()
