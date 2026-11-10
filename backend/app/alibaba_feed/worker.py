"""Recoverable local normalization with a batch fence on every item write."""
from collections import Counter, defaultdict
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import or_

from app.core.time import beijing_now
from .canonical import digest, parse_json
from .errors import FeedError
from .models import AlibabaFeedBatch, AlibabaFeedItem, AlibabaFeedSource
from .service import log_failure
from .validation import record_quality


def claim_batch(db, *, now=None, lease_seconds=120, pilot_only=False):
    claim_time = now or beijing_now()
    query = db.query(AlibabaFeedBatch).filter(or_(
        AlibabaFeedBatch.status == "queued",
        (AlibabaFeedBatch.status == "running") & (AlibabaFeedBatch.lease_expires_at <= claim_time),
    ))
    if pilot_only:
        from .pilot_service import active_pilot
        pilot = active_pilot(db)
        if pilot is None:
            db.rollback()
            return None
        source_uid = db.query(AlibabaFeedSource.source_account_uid).filter_by(id=pilot.source_id).scalar_subquery()
        query = query.filter(AlibabaFeedBatch.source_account_uid == source_uid)
    batch = query.order_by(AlibabaFeedBatch.created_at, AlibabaFeedBatch.id).with_for_update(skip_locked=True).first()
    if batch is None:
        db.rollback()
        return None
    claim_time = now or beijing_now()  # Lock waits do not consume the new lease.
    batch.status = "running"
    batch.lease_token = uuid4().hex
    batch.lease_expires_at = claim_time + timedelta(seconds=lease_seconds)
    batch.attempts += 1
    result = (batch.id, batch.lease_token)
    db.commit()
    return result


def fence(db, batch_id, token, now, *, pilot_only=False):
    if pilot_only:
        from .pilot_service import active_pilot
        pilot = active_pilot(db)
        if pilot is None:
            raise FeedError(409, "PILOT_PAUSED")
    batch = db.query(AlibabaFeedBatch).filter_by(id=batch_id).populate_existing().with_for_update().one()
    check_time = now or beijing_now()
    if batch.status != "running" or batch.lease_token != token or batch.lease_expires_at <= check_time:
        raise FeedError(409, "LEASE_LOST")
    if pilot_only:
        source_uid = db.query(AlibabaFeedSource.source_account_uid).filter_by(id=pilot.source_id).scalar()
        if batch.source_account_uid != source_uid:
            raise FeedError(409, "PILOT_PAUSED")
    return batch


def _release_paused_batch(db, batch_id, token, now):
    try:
        batch = fence(db, batch_id, token, now)
        batch.status = "queued"
        batch.lease_token = None
        batch.lease_expires_at = None
        batch.attempts -= 1
        db.commit()
    except FeedError as lost:
        db.rollback()
        log_failure("pause lease release", lost)


def version_candidate(item):
    """Only complete, valid observations participate in version arbitration."""
    return (
        item.snapshot.get("detail_scraped") is True
        and item.snapshot.get("scrape_status") == "success"
        and not (set(item.issues or []) - {"WINDOW_PRECISION_INSUFFICIENT", "VERSION_CONFLICT"})
    )


def process_item(db, batch_id, token, index, record, window, duplicate=False, *, now=None, lease_seconds=120,
                 schema_version="ark_alibaba_feed_v1", run_coverage=None, pilot_only=False):
    def clock():
        return now if now is not None else beijing_now()

    def renew_and_commit(batch, original_expiry):
        if clock() >= original_expiry:
            raise FeedError(409, "LEASE_LOST")
        batch.lease_expires_at = clock() + timedelta(seconds=lease_seconds)
        db.flush()
        if clock() >= original_expiry:
            raise FeedError(409, "LEASE_LOST")
        db.commit()

    try:
        batch = fence(db, batch_id, token, now, pilot_only=pilot_only)
        original_expiry = batch.lease_expires_at
        source = db.query(AlibabaFeedSource).filter_by(source_account_uid=batch.source_account_uid).populate_existing().with_for_update().one()
        if clock() >= original_expiry:
            raise FeedError(409, "LEASE_LOST")
        existing = db.query(AlibabaFeedItem).filter_by(batch_id=batch.id, record_index=index).first()
        if existing:
            renew_and_commit(batch, original_expiry)
            return
        if schema_version == "ark_alibaba_feed_v1.1":
            from .v11_worker import process_record
            process_record(db, source, batch, index, record, window, run_coverage, duplicate, clock)
            renew_and_commit(batch, original_expiry)
            return
        window_result, issues = record_quality(record, window, batch.max_message_bytes)
        if duplicate:
            issues.append("DUPLICATE_RECORD_KEY")
        if not source.ingest_enabled or source.consent_state != "authorized":
            issues.append("SOURCE_DISABLED")
        if source.collection_generation != batch.collection_generation:
            issues.append("SOURCE_GENERATION_RETIRED")
        if batch.source_status == "failed":
            issues.append("SOURCE_FAILED")
        snapshot_hash = digest(record)
        outcome = "quarantined" if set(issues) - {"WINDOW_PRECISION_INSUFFICIENT", "DETAIL_INCOMPLETE"} else "history_only"
        logical = db.query(AlibabaFeedItem).filter_by(
            source_account_uid=batch.source_account_uid, collection_generation=batch.collection_generation,
            record_type=record["type"], inquiry_id=record["inquiry_id"],
        )
        # The source lock also serializes records that have no preexisting item row.
        peers = [item for item in logical.filter(AlibabaFeedItem.observed_at == batch.observed_at).with_for_update().all()
                 if version_candidate(item)]
        complete_candidate = outcome != "quarantined" and "DETAIL_INCOMPLETE" not in issues
        if complete_candidate and any(p.snapshot_hash != snapshot_hash for p in peers):
            outcome = "quarantined"
            issues.append("VERSION_CONFLICT")
            # Equal observations cannot select current by HTTP arrival order.
            for peer in peers:
                peer.is_current = False
            db.flush()  # Production sessions disable autoflush; queries must see demotion.
            candidates = logical.filter(AlibabaFeedItem.observed_at < batch.observed_at,
                                        AlibabaFeedItem.outcome == "current_updated").order_by(AlibabaFeedItem.observed_at.desc()).all()
            current = logical.filter_by(is_current=True).first()
            if current is None:
                for candidate in candidates:
                    if "VERSION_CONFLICT" not in (candidate.issues or []):
                        candidate.is_current = True
                        break
            for peer in peers:
                peer.issues = sorted(set(peer.issues or []) | {"VERSION_CONFLICT"})
        elif complete_candidate:
            current = logical.filter_by(is_current=True).with_for_update().first()
            # Valid complete observations (including unresolved conflicts) fence
            # older arrivals. Missing/invalid details never block a complete copy.
            latest = next((item for item in logical.order_by(AlibabaFeedItem.observed_at.desc())
                           if version_candidate(item)), None)
            if latest is not None and latest.observed_at > batch.observed_at:
                outcome = "history_only"
            elif peers:
                outcome = "quarantined" if any("VERSION_CONFLICT" in (p.issues or []) for p in peers) else "unchanged"
                if outcome == "quarantined":
                    issues.append("VERSION_CONFLICT")
            elif current is None or current.observed_at < batch.observed_at:
                outcome = "current_updated"
                if current:
                    current.is_current = False
        db.add(AlibabaFeedItem(
            batch_id=batch.id, record_index=index, source_account_uid=batch.source_account_uid,
            collection_generation=batch.collection_generation, record_type=record["type"],
            inquiry_id=record["inquiry_id"], observed_at=batch.observed_at,
            snapshot_hash=snapshot_hash, snapshot=record, outcome=outcome,
            is_current=outcome == "current_updated", window_result=window_result,
            issues=sorted(set(issues)), created_at=clock(),
        ))
        renew_and_commit(batch, original_expiry)
    except Exception:
        db.rollback()
        raise


def batch_issues(data):
    issues = []
    records = data["records"]
    expected = {"records_total": len(records), "inquiry_records": sum(r["type"] == "inquiry" for r in records), "tm_raw": sum(r["type"] == "tm" for r in records)}
    if any(data["stats"].get(key) != value for key, value in expected.items()):
        issues.append({"code": "STATS_MISMATCH", "field_path": "stats"})
    grouped = defaultdict(list)
    for record in records:
        grouped[record.get("assignee_name")].append(record)
    producer = data["by_assignee"]
    matched = len(producer) == len(grouped)
    names = set()
    for group in producer:
        name = group.get("assignee_name")
        rows = grouped.get(name, [])
        expected_counts = {status: sum(r["reply_status"] == status for r in rows) for status in ("replied", "pending", "unreplied", "unknown")}
        expected_counts["total"] = len(rows)
        matched &= name not in names and group["counts"] == expected_counts and Counter(group["inquiry_ids"]) == Counter(r["inquiry_id"] for r in rows)
        names.add(name)
    if not matched:
        issues.append({"code": "ASSIGNEE_COUNTS_MISMATCH", "field_path": "by_assignee"})
    if data["run"]["status"] == "partial":
        issues.append({"code": "SOURCE_PARTIAL", "field_path": "run.status"})
    return issues


def process_next_batch(db, *, now=None, lease_seconds=120, pilot_only=False):
    claim = claim_batch(db, now=now, lease_seconds=lease_seconds, pilot_only=pilot_only)
    if claim is None:
        return False
    batch_id, token = claim
    try:
        batch = db.get(AlibabaFeedBatch, batch_id)
        data = parse_json(batch.raw_body)
        db.rollback()
        counts = Counter((r["type"], r["inquiry_id"]) for r in data["records"])
        # Deterministic logical ordering; record_index preserves producer array order.
        records = sorted(enumerate(data["records"]), key=lambda pair: (pair[1]["type"], pair[1]["inquiry_id"], pair[0]))
        for index, record in records:
            process_item(db, batch_id, token, index, record, data["run"]["window"],
                         counts[(record["type"], record["inquiry_id"])] > 1,
                         now=now, lease_seconds=lease_seconds,
                         schema_version=data["schema"], run_coverage=data["run"].get("coverage"), pilot_only=pilot_only)
        batch = fence(db, batch_id, token, now, pilot_only=pilot_only)
        original_expiry = batch.lease_expires_at
        batch.issues = batch_issues(data)
        items = db.query(AlibabaFeedItem).filter_by(batch_id=batch_id).all()
        if len(items) != batch.received_records:
            raise FeedError(409, "INCOMPLETE_PROGRESS")
        batch.status = "completed_with_issues" if batch.issues or any(item.issues for item in items) else "completed"
        if batch.source_status == "failed" and not data["records"]:
            batch.status = "recorded_source_failure"
        batch.finished_at = now or beijing_now()
        batch.lease_token = None
        batch.lease_expires_at = None
        db.flush()
        if (now or beijing_now()) >= original_expiry:
            raise FeedError(409, "LEASE_LOST")
        db.commit()
    except Exception as exc:
        db.rollback()
        if isinstance(exc, FeedError) and exc.error_code == "PILOT_PAUSED":
            _release_paused_batch(db, batch_id, token, now)
            return False
        log_failure("worker", exc)
        # A lost lease must not write even a failure status. Other failures remain
        # running until expiry and are retried within the original durable batch.
        if not isinstance(exc, FeedError) or exc.error_code != "LEASE_LOST":
            try:
                failed = fence(db, batch_id, token, now, pilot_only=pilot_only)
                original_expiry = failed.lease_expires_at
                if failed.attempts >= 3:
                    failed.status = "processing_failed"
                    failed.issues = list(failed.issues or []) + [{"code": "NORMALIZATION_FAILED", "field_path": "records"}]
                    failed.finished_at = now or beijing_now()
                    failed.lease_token = None
                    failed.lease_expires_at = None
                    db.flush()
                    if (now or beijing_now()) >= original_expiry:
                        raise FeedError(409, "LEASE_LOST")
                    db.commit()
                else:
                    db.rollback()
            except Exception as persistence_error:
                db.rollback()
                if isinstance(persistence_error, FeedError) and persistence_error.error_code == "PILOT_PAUSED":
                    _release_paused_batch(db, batch_id, token, now)
                    return False
                log_failure("failure receipt", persistence_error)
            raise
    return True


def drain_queue(session_factory, *, limit=10, lease_seconds=120):
    processed = 0
    for _ in range(limit):
        with session_factory() as db:
            try:
                if not process_next_batch(db, lease_seconds=lease_seconds, pilot_only=True):
                    break
                processed += 1
            except Exception as exc:
                db.rollback()
                log_failure("drain", exc)
                break
    return processed
