"""Record metadata arbitration, called within the P1 worker transaction fence."""
from .canonical import digest
from .models import AlibabaFeedItem
from .normalization import SCHEMA, SOFT_ISSUES, add_issue, normalize_messages, qualified
from .v11_validation import quality
from .validation import timestamp


def process_record(db, source, batch, index, record, window, run_coverage, duplicate, clock):
    window_result, issues = quality(record, window, (run_coverage or {}).get("selection", "created_window"), batch.max_message_bytes)
    if duplicate:
        issues.append("DUPLICATE_RECORD_KEY")
    if not source.ingest_enabled or source.consent_state != "authorized":
        issues.append("SOURCE_DISABLED")
    if source.collection_generation != batch.collection_generation:
        issues.append("SOURCE_GENERATION_RETIRED")
    if batch.source_status == "failed":
        issues.append("SOURCE_FAILED")
    meta = {key: value for key, value in record.items()
            if key not in {"messages", "conversation_revision", "coverage", "observed_at"}}
    item = AlibabaFeedItem(
        batch_id=batch.id, record_index=index, source_account_uid=batch.source_account_uid,
        collection_generation=batch.collection_generation, record_type=record["type"], inquiry_id=record["inquiry_id"],
        observed_at=timestamp(record["observed_at"]), schema_version=SCHEMA,
        conversation_id=record.get("conversation_id"), snapshot_revision=record["snapshot_revision"],
        conversation_revision=record.get("conversation_revision"), coverage={**(run_coverage or {}), **record["coverage"]},
        snapshot_hash=digest(meta), snapshot=record, outcome="history_only", is_current=False,
        window_result=window_result, issues=sorted(set(issues)), created_at=clock(),
    )
    db.add(item)
    db.flush()  # first_item_id is durable in this same transaction, never separately.
    logical = db.query(AlibabaFeedItem).filter_by(
        source_account_uid=batch.source_account_uid, collection_generation=batch.collection_generation,
        record_type=record["type"], inquiry_id=record["inquiry_id"], schema_version=SCHEMA,
    ).filter(AlibabaFeedItem.id != item.id)
    peers = [p for p in logical.with_for_update().all() if qualified(p, include_conflicts=True)]
    if qualified(item):
        same = [p for p in peers if p.snapshot_revision == item.snapshot_revision]
        if any(p.snapshot_hash != item.snapshot_hash or "VERSION_CONFLICT" in (p.issues or []) for p in same):
            add_issue(item, "VERSION_CONFLICT")
            for peer in same:
                add_issue(peer, "VERSION_CONFLICT")
                peer.is_current = False
        inverted = [p for p in peers if
                    (p.snapshot_revision < item.snapshot_revision and p.observed_at > item.observed_at)
                    or (p.snapshot_revision > item.snapshot_revision and p.observed_at < item.observed_at)]
        if inverted:
            add_issue(item, "VERSION_ORDER_CONFLICT")
            for peer in inverted:
                add_issue(peer, "VERSION_ORDER_CONFLICT")
                peer.is_current = False
    normalize_messages(db, source, item, clock)
    if set(item.issues or []) - SOFT_ISSUES - {"DETAIL_INCOMPLETE"}:
        item.outcome = "quarantined"
    elif qualified(item):
        latest = max((p.snapshot_revision for p in peers), default=0)
        current = next((p for p in peers if p.is_current), None)
        newer_view = current is None or (item.conversation_revision or 0) > (current.conversation_revision or 0)
        if item.snapshot_revision > latest or (item.snapshot_revision == latest and newer_view):
            for peer in logical.filter_by(is_current=True):
                peer.is_current = False
            # v1 current copies may coexist until a v1.1 record supersedes them.
            for peer in db.query(AlibabaFeedItem).filter_by(
                source_account_uid=item.source_account_uid, collection_generation=item.collection_generation,
                record_type=item.record_type, inquiry_id=item.inquiry_id, is_current=True,
            ):
                peer.is_current = False
            item.is_current = True
            item.outcome = "current_updated"
        elif item.snapshot_revision == latest:
            item.outcome = "unchanged"
    db.flush()
    return item
