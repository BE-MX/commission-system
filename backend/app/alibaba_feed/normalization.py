"""Stable conversation messages and read-time suppression of stale evidence.

All writes run inside the worker's batch fence and source lock transaction.
This module grants no business access or automation capability.
"""
from .canonical import digest
from .models import AlibabaFeedItem, AlibabaFeedMessage, AlibabaFeedSource
from .validation import timestamp

SCHEMA = "ark_alibaba_feed_v1.1"
SOFT_ISSUES = {"WINDOW_PRECISION_INSUFFICIENT", "ACTIVITY_TIME_UNKNOWN"}
CONFLICTS = {"VERSION_CONFLICT", "CONVERSATION_VERSION_CONFLICT", "VERSION_ORDER_CONFLICT",
             "MESSAGE_VERSION_CONFLICT", "MESSAGE_ORDER_CONFLICT"}


def message_hash(message):
    # ref is a position in an export, never a message identity or content version.
    return digest({key: value for key, value in message.items() if key != "ref"})


def qualified(item, *, include_conflicts=False):
    allowed = SOFT_ISSUES | (CONFLICTS if include_conflicts else set())
    return (item.snapshot.get("detail_scraped") is True
            and item.snapshot.get("scrape_status") == "success"
            and not (set(item.issues or []) - allowed))


def add_issue(item, code):
    item.issues = sorted(set(item.issues or []) | {code})


def conversation_items(db, item):
    return db.query(AlibabaFeedItem).filter_by(
        source_account_uid=item.source_account_uid, collection_generation=item.collection_generation,
        schema_version=SCHEMA, conversation_id=item.conversation_id,
    )


def complete_set(item):
    coverage = item.coverage or {}
    return coverage.get("history_complete") is True and coverage.get("has_more") is False


def message_set(item):
    return sorted((m.get("message_id"), m["message_revision"], message_hash(m))
                  for m in item.snapshot["messages"] if m.get("message_id"))


def latest_tail(item):
    coverage = item.coverage or {}
    messages = item.snapshot["messages"]
    if not (coverage.get("latest_complete") is True and coverage.get("has_more") is False):
        return None
    if not messages:
        return ()
    if not all(m.get("message_id") and m.get("source_order") is not None for m in messages):
        return None
    tail = max(messages, key=lambda m: m["source_order"])
    return tail["source_order"], tail["message_id"], tail["message_revision"], message_hash(tail)


def normalize_messages(db, source, item, clock):
    """Arbitrate independent message versions; retain withdrawal even on conflict."""
    valid = qualified(item, include_conflicts=True)
    # Incomplete detail may carry a valid explicit withdrawal, never a replacement.
    withdrawal_valid = not (set(item.issues or []) - SOFT_ISSUES - CONFLICTS - {"DETAIL_INCOMPLETE"})
    if not withdrawal_valid:
        return
    if any(m.get("deleted_at") for m in item.snapshot["messages"]):
        source.legacy_identity_blocked = True
    if not item.conversation_id:
        return
    peers = [p for p in conversation_items(db, item).filter(
        AlibabaFeedItem.id != item.id,
        AlibabaFeedItem.conversation_revision == item.conversation_revision,
    ).all() if qualified(p, include_conflicts=True)]
    if valid:
        tail = latest_tail(item)
        conflict_peers = [p for p in peers if
                          (complete_set(item) and complete_set(p) and message_set(p) != message_set(item))
                          or (tail is not None and latest_tail(p) is not None and latest_tail(p) != tail)]
        if conflict_peers:
            add_issue(item, "CONVERSATION_VERSION_CONFLICT")
            for peer in conflict_peers:
                add_issue(peer, "CONVERSATION_VERSION_CONFLICT")
    rows = db.query(AlibabaFeedMessage).filter_by(
        source_account_uid=item.source_account_uid, collection_generation=item.collection_generation,
        conversation_id=item.conversation_id,
    ).with_for_update().all()
    known = {row.message_id: row for row in rows}
    for message in item.snapshot["messages"]:
        message_id = message.get("message_id")
        deleted = message.get("deleted_at")
        if not message_id or (not valid and not deleted):
            continue
        revision = message["message_revision"]
        hashed = message_hash(message)
        row = known.get(message_id)
        if row is None:
            row = AlibabaFeedMessage(
                source_account_uid=item.source_account_uid, collection_generation=item.collection_generation,
                conversation_id=item.conversation_id, message_id=message_id,
                source_order=message.get("source_order"), message_revision=revision,
                latest_conversation_revision=item.conversation_revision,
                observed_at=item.observed_at, snapshot_hash=hashed,
                content=dict(message), actor_type=message["actor_type"],
                sender_external_user_id=message.get("sender_external_user_id"),
                first_item_id=item.id, created_at=clock(), updated_at=clock(),
                version_conflict=False, order_conflict=False,
            )
            known[message_id] = row
            db.add(row)
        else:
            if row.source_order != message.get("source_order"):
                row.order_conflict = True
                add_issue(item, "MESSAGE_ORDER_CONFLICT")
            inverted = ((revision > row.message_revision and item.conversation_revision <= row.latest_conversation_revision)
                        or (revision < row.message_revision and item.conversation_revision >= row.latest_conversation_revision)
                        or (revision > row.message_revision and item.observed_at < row.observed_at)
                        or (revision < row.message_revision and item.observed_at > row.observed_at))
            if inverted:
                row.version_conflict = True
                add_issue(item, "VERSION_ORDER_CONFLICT")
            elif revision == row.message_revision and row.snapshot_hash != hashed:
                row.version_conflict = True
                add_issue(item, "MESSAGE_VERSION_CONFLICT")
            elif revision > row.message_revision:
                row.message_revision = revision
                row.snapshot_hash = hashed
                row.latest_conversation_revision = item.conversation_revision
                row.observed_at = item.observed_at
                row.actor_type = message["actor_type"]
                row.sender_external_user_id = message.get("sender_external_user_id")
                row.version_conflict = False
                if row.tombstone_revision is None:
                    row.content = dict(message)
            elif revision == row.message_revision:
                row.latest_conversation_revision = max(row.latest_conversation_revision, item.conversation_revision)
        if deleted:
            # Even contradictory observations must never expose a withdrawn body.
            source.legacy_identity_blocked = True
            if row.tombstone_revision is None or revision > row.tombstone_revision:
                row.tombstone_revision = revision
                row.deleted_at = timestamp(deleted)
            row.content = None
        if row.tombstone_revision is not None:
            row.content = None
        order = message.get("source_order")
        if order is not None:
            for other in known.values():
                if other.message_id != message_id and other.source_order == order:
                    row.order_conflict = other.order_conflict = True
                    add_issue(item, "MESSAGE_ORDER_CONFLICT")
    db.flush()


def safe_messages(db, item):
    """Return only the exact evidence version, never substitute a later body."""
    source = db.query(AlibabaFeedSource).filter_by(source_account_uid=item.source_account_uid).populate_existing().with_for_update(read=True).one_or_none()
    if source is None:
        return []
    messages = item.snapshot.get("messages", [])
    stable = item.schema_version == SCHEMA and item.conversation_id
    if not stable:
        return [] if source.legacy_identity_blocked else [dict(m, _original_position=i) for i, m in enumerate(messages)
                                                        if not m.get("deleted_at")]
    if set(item.issues or []) & CONFLICTS:
        return []
    # Same-revision complete-set conflicts invalidate every reference to that view.
    if any("CONVERSATION_VERSION_CONFLICT" in (peer.issues or []) for peer in
           conversation_items(db, item).filter_by(conversation_revision=item.conversation_revision).populate_existing().with_for_update(read=True).all()):
        return []
    known = {m.message_id: m for m in db.query(AlibabaFeedMessage).filter_by(
        source_account_uid=item.source_account_uid, collection_generation=item.collection_generation,
        conversation_id=item.conversation_id,
    ).populate_existing().with_for_update(read=True).all()}
    result = []
    seen = set()
    for index, message in enumerate(messages):
        message_id = message.get("message_id")
        if not message_id:
            if not source.legacy_identity_blocked and not message.get("deleted_at"):
                result.append(dict(message, _original_position=index))
            continue
        row = known.get(message_id)
        if (message_id in seen or row is None or row.tombstone_revision is not None or row.deleted_at is not None
                or row.version_conflict or row.order_conflict or row.content is None
                or row.message_revision != message["message_revision"]
                or row.snapshot_hash != message_hash(message)):
            continue
        seen.add(message_id)
        result.append(dict(message, _original_position=index))
    return result
