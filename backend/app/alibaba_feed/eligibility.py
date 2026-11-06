"""Explain rule qualification without scheduling, model calls, or outbound actions."""
from datetime import timedelta

from app.auth.models import ArkUserExternalBinding
from app.core.config import get_settings
from app.core.time import beijing_now
from .models import AlibabaFeedItem, AlibabaFeedMessage, AlibabaFeedSource
from .validation import timestamp


def bound_employee(db, external_id):
    if not external_id:
        return None
    # Compare identifiers exactly after SQL retrieval; legacy binding columns may
    # use a case-insensitive collation. Duplicate bindings never authorize access.
    rows = db.query(ArkUserExternalBinding).filter_by(
        provider="alibaba_icbu", binding_status="active", deleted_at=None,
        external_account_id=external_id,
    ).populate_existing().with_for_update(read=True).all()
    matches = [row for row in rows if row.provider == "alibaba_icbu" and row.external_account_id == external_id]
    return matches[0].ark_user_id if len(matches) == 1 else None


def rule_eligibility(db, item, source=None, *, user_id=None, now=None):
    """Return factual prerequisites separately from the disabled execution gate."""
    source = source or db.query(AlibabaFeedSource).filter_by(source_account_uid=item.source_account_uid).first()
    settings = get_settings()
    now = now or beijing_now()
    reasons = []
    capabilities = source.verified_capabilities or {} if source else {}
    snapshot = item.snapshot or {}
    coverage = item.coverage or {}
    checks = {
        "schema": item.schema_version == "ark_alibaba_feed_v1.1",
        "linked_private_customer": user_id is not None,
        "source_authorized": bool(source and source.consent_state == "authorized" and source.crm_shared and source.private_feed_enabled),
        "current_generation": bool(source and item.collection_generation == source.collection_generation),
        "current_qualified_snapshot": bool(item.is_current and item.outcome != "quarantined"
                                           and snapshot.get("detail_scraped") is True and snapshot.get("scrape_status") == "success"),
        "stable_identity": bool(item.conversation_id and snapshot.get("messages")
                                and all(m.get("message_id") for m in snapshot.get("messages", []))),
        "fresh_observation": bool(item.observed_at and now - timedelta(hours=settings.ALIBABA_FEED_MAX_OBSERVATION_AGE_HOURS) <= item.observed_at <= now + timedelta(minutes=5)),
        "capability_evidence": bool(capabilities.get("evidence_note", "").strip()),
    }
    for name, value in checks.items():
        if not value:
            reasons.append(name.upper() + "_REQUIRED")
    rows = []
    if checks["schema"] and item.conversation_id:
        rows = db.query(AlibabaFeedMessage).filter_by(source_account_uid=item.source_account_uid,
            collection_generation=item.collection_generation, conversation_id=item.conversation_id).populate_existing().with_for_update(read=True).all()
    active = [row for row in rows if row.tombstone_revision is None and row.deleted_at is None]
    coherent = bool(rows) and not any(row.version_conflict or row.order_conflict for row in rows)
    orders = [row.source_order for row in rows]
    ordered = bool(orders) and all(order is not None for order in orders) and len(set(orders)) == len(orders)
    conversation_rows = db.query(AlibabaFeedItem).filter_by(source_account_uid=item.source_account_uid,
        collection_generation=item.collection_generation, conversation_id=item.conversation_id).populate_existing().with_for_update(read=True).all() if checks["schema"] and item.conversation_id else []
    from .normalization import qualified
    candidates = [row for row in conversation_rows if qualified(row)]
    # A known newer incomplete conversation forbids falling back to an older
    # complete tail. Completeness is tested only after selecting its revision.
    highest = max((row.conversation_revision or 0 for row in candidates), default=0)
    bounds = False
    activity_bounds = False
    try:
        start, end = timestamp(coverage.get("covered_from")), timestamp(coverage.get("covered_through"))
        bounds = start <= end and item.observed_at - timedelta(minutes=5) <= end <= item.observed_at + timedelta(minutes=5)
        if coverage.get("selection") == "activity_window":
            activity_bounds = start <= timestamp(coverage.get("activity_window_start")) and end >= timestamp(coverage.get("activity_window_end"))
    except (ValueError, TypeError, OverflowError):
        # Absent or invalid bounds are an explicit missing qualification, never full coverage.
        bounds = False
    latest = bool(coverage.get("latest_complete") and not coverage.get("has_more") and highest
                  and item.conversation_revision == highest and bounds)
    if any("CONVERSATION_VERSION_CONFLICT" in (row.issues or []) for row in conversation_rows
           if row.conversation_revision == item.conversation_revision):
        coherent = False
    stable = all(checks.values()) and coherent and bool(capabilities.get("stable_message_ids"))
    ordered_latest = stable and ordered and latest and bool(capabilities.get("reliable_order") and capabilities.get("latest_coverage"))
    roles_verifiable = bool(capabilities.get("human_identity") and active
                            and all(row.actor_type in {"human", "bot", "system"} for row in active))
    activity = stable and activity_bounds and coverage.get("selection") == "activity_window" and coverage.get("activity_scan_complete") is True and bool(capabilities.get("activity_scan"))
    human_outbound = any(row.actor_type == "human" and (row.content or {}).get("dir") == "seller"
                         and bound_employee(db, row.sender_external_user_id) == user_id for row in active) if user_id is not None else False
    qualified = {
        "reply_rules": bool(ordered_latest and roles_verifiable),
        "automatic_followup_completion": bool(ordered_latest and capabilities.get("human_identity") and human_outbound),
        "last_contact_and_silence": bool(activity and capabilities.get("human_identity") and coverage.get("history_complete")),
        "routine_ai": bool(ordered_latest and source and source.ai_egress_allowed),
    }
    for label, passed in (("MESSAGE_VERSION_OR_ORDER_CONFLICT", coherent), ("RELIABLE_ORDER_REQUIRED", ordered),
                          ("LATEST_COVERAGE_REQUIRED", latest), ("ROLE_SEMANTICS_UNVERIFIED", roles_verifiable)):
        if not passed:
            reasons.append(label)
    enabled = bool(settings.ALIBABA_FEED_AUTOMATION_ENABLED and settings.CLIENT_DESK_ENABLED
                   and settings.ALIBABA_FEED_BUSINESS_ENABLED
                   and user_id is not None and user_id in settings.CLIENT_DESK_PILOT_USER_IDS)
    if not enabled:
        reasons.append("AUTOMATION_DISABLED")
    missing_capabilities = [name for name in ("stable_message_ids", "reliable_order", "latest_coverage", "human_identity", "activity_scan", "deletions")
                            if capabilities.get(name) is not True]
    return {"enabled": enabled, "qualified": qualified,
            "allowed": {name: enabled and value for name, value in qualified.items()},
            "reasons": sorted(set(reasons)), "coverage_selection": coverage.get("selection", "created_window"),
            "missing_verified_capabilities": missing_capabilities,
            "conversation_revision": item.conversation_revision,
            "latest_qualified_conversation_revision": highest,
            "message_identity_stable": checks["stable_identity"], "normalized_message_count": len(active)}
