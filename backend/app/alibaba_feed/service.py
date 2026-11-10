"""Durable ingestion and safe, source-scoped receipts."""
import hashlib
import logging
from datetime import timedelta
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from app.core.time import beijing_now
from .canonical import digest
from .errors import FeedError
from .models import AlibabaFeedBatch, AlibabaFeedItem, AlibabaFeedSource
from .validation import limit, parse_envelope, timestamp

logger = logging.getLogger(__name__)
TERMINAL = ("completed", "completed_with_issues", "recorded_source_failure", "processing_failed")
OUTCOMES = ("current_updated", "history_only", "unchanged", "quarantined")


def log_failure(action, error):
    # Exception text may contain SQL parameters or untrusted message bodies.
    message = f"Alibaba feed {action} failed ({type(error).__name__})"
    logger.warning(message)
    print(message, flush=True)


def accept_batch(db, source, raw_body, idempotency_key, *, now=None, limits=None):
    now = now or beijing_now()
    data = parse_envelope(raw_body, idempotency_key, now, limits)
    if data.get("source_account_uid", source.source_account_uid) != source.source_account_uid:
        raise FeedError(403, "SOURCE_SCOPE_DENIED")
    declared_generation = data["run"].get("collection_generation")
    if declared_generation is not None and declared_generation != getattr(source, "generation", None):
        raise FeedError(409, "SOURCE_GENERATION_RETIRED")
    body_hash = digest(data)
    # This service owns its short ingestion transaction. Discard the authentication
    # read snapshot before locking; MySQL repeatable-read must see concurrent posts.
    source_uid = source.source_account_uid
    db.rollback()
    try:
        # Lock order matches pilot/admin operations: pilot -> app -> source -> batch.
        from .auth import recheck_feed_principal
        from .pilot_service import require_receiver
        pilot = require_receiver(db)
        recheck_feed_principal(db, source, required_scope="alibaba_feed:write")
        row = db.query(AlibabaFeedSource).filter_by(source_account_uid=source_uid).populate_existing().with_for_update().first()
        if (row is None or not row.ingest_enabled or row.consent_state != "authorized"
                or getattr(source, "generation", row.collection_generation) != row.collection_generation
                or getattr(source, "integration_app_id", row.integration_app_id) != row.integration_app_id):
            raise FeedError(403, "SOURCE_DISABLED")
        if pilot.source_id != row.id:
            raise FeedError(403, "SOURCE_SCOPE_DENIED")
        existing = db.query(AlibabaFeedBatch).filter_by(source_account_uid=row.source_account_uid, run_id=idempotency_key).first()
        if existing:
            if existing.body_hash != body_hash:
                raise FeedError(409, "IDEMPOTENCY_PAYLOAD_MISMATCH")
            result = receipt(db, existing)
            result["replayed"] = True
            db.commit()
            return result
        pending = db.query(AlibabaFeedBatch).filter(AlibabaFeedBatch.source_account_uid == row.source_account_uid, AlibabaFeedBatch.status.in_(("queued", "running"))).count()
        recent = db.query(AlibabaFeedBatch).filter(AlibabaFeedBatch.source_account_uid == row.source_account_uid, AlibabaFeedBatch.created_at > now - timedelta(minutes=1)).count()
        if pending >= limit(limits, "SOURCE_PENDING_LIMIT", 2) or recent >= limit(limits, "SOURCE_REQUESTS_PER_MINUTE", 10):
            raise FeedError(429, "SOURCE_BACKPRESSURE", retry_after=60)
        batch = AlibabaFeedBatch(
            id="afb_" + uuid4().hex, source_account_uid=row.source_account_uid,
            run_id=idempotency_key, collection_generation=row.collection_generation,
            body_hash=body_hash, raw_hash=hashlib.sha256(raw_body).hexdigest(),
            raw_body=raw_body, body_bytes=len(raw_body),
            max_message_bytes=limit(limits, "MAX_MESSAGE_BYTES", 65536), source_status=data["run"]["status"],
            status="queued", observed_at=timestamp(data["run"]["reply_status_snapshot_at"]),
            received_records=len(data["records"]), received_messages=sum(len(r["messages"]) for r in data["records"]),
            issues=[], created_at=now,
        )
        db.add(batch)
        db.flush()
        result = receipt(db, batch)
        result["replayed"] = False
        db.commit()  # No 202 until this succeeds.
        return result
    except FeedError:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        log_failure("ingest", exc)
        raise FeedError(503, "INGEST_TEMPORARILY_UNAVAILABLE") from None


def get_receipt(db, source_uid, *, batch_id=None, run_id=None, issue_offset=0, issue_limit=100):
    query = db.query(AlibabaFeedBatch).filter_by(source_account_uid=source_uid)
    query = query.filter_by(id=batch_id) if batch_id is not None else query.filter_by(run_id=run_id)
    batch = query.first()
    if batch is None:
        raise FeedError(404, "BATCH_NOT_FOUND" if batch_id else "RUN_NOT_FOUND")
    return receipt(db, batch, issue_offset=issue_offset, issue_limit=issue_limit)


def receipt(db, batch, *, issue_offset=0, issue_limit=100):
    items = db.query(AlibabaFeedItem.record_index, AlibabaFeedItem.record_type, AlibabaFeedItem.inquiry_id,
                     AlibabaFeedItem.outcome, AlibabaFeedItem.window_result, AlibabaFeedItem.issues).filter_by(batch_id=batch.id).order_by(AlibabaFeedItem.record_index).all()
    outcomes = {key: 0 for key in OUTCOMES}
    issues = list(batch.issues or [])
    for item in items:
        outcomes[item.outcome] += 1
        for code in item.issues:
            # External IDs and text are intentionally omitted from the collector receipt.
            issues.append({"record_index": item.record_index, "type": item.record_type,
                           "code": code, "field_path": f"records[{item.record_index}]"})
    offset = max(0, issue_offset)
    page_size = min(100, max(1, issue_limit))
    state = batch.status
    if state == "completed" and issues:
        state = "completed_with_issues"
    return {
        "batch_id": batch.id, "run_id": batch.run_id, "source_account_uid": batch.source_account_uid,
        "body_hash": batch.body_hash, "source_status": batch.source_status,
        "processing_state": state, "received_records": batch.received_records,
        "received_messages": batch.received_messages, "processed_records": len(items),
        "unprocessed_records": max(0, batch.received_records - len(items)),
        "provisional": batch.status not in TERMINAL, "outcomes": outcomes,
        "eligibility": {"owner_unmapped": len(items), "private_linked": 0, "ai_eligible": 0, "rule_eligible": 0},
        "quality": {"window_uncertain": sum(i.window_result == "uncertain" for i in items),
                    "window_outside": sum(i.window_result == "out_of_window" for i in items),
                    "buyer_count_verifiable": False, "message_identity_stable": False},
        "issues": issues[offset:offset + page_size], "issues_total": len(issues),
        "issues_offset": offset, "issues_limit": page_size,
        "status_url": f"/api/alibaba-feed/v1/batches/{batch.id}",
        "next_action": "review_source_failure" if batch.source_status == "failed" else "review_owner_mapping_and_source_coverage",
    }
