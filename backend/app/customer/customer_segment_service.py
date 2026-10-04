"""Company-wide versioned candidate policy and server-side commercial projection."""

import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from statistics import mean, median
from datetime import timedelta

from sqlalchemy import func, or_
from app.core.time import beijing_now
from app.customer.models import CustomerAccount, CustomerConversation, CustomerMessage, CustomerOrder, CustomerOrderItem, CustomerListProjection, CustomerSyncCursor, CustomerExternalIdentity, CustomerSourceRecord
from app.whatsapp.models import WhatsAppAccount
from app.customer.logical_customer_service import logical_owner_expression, logical_subject_matches_customer
from app.customer.pcw_order_service import derive_order_type
from app.customer.query_service import scoped_customer_query, _summary, iso_beijing
from app.customer.pcw_overview_service import _scope_customer_ids, _collect_watermarks, WATERMARK_STALE_AFTER
from app.core.list_sort import apply_items_sort

POLICY = json.loads(Path(__file__).with_name("customer_segment_policy.json").read_text(encoding="utf-8"))


def _source_coverage(orders, conversations, identity_scopes, cursors, wa_accounts, now):
    """Map coverage to real adapters: OKKI orders include items; Alibaba inquiries include messages."""
    order_scopes = {(row.source_system, row.source_account_key) for row in orders} | set(identity_scopes)
    if not order_scopes or not conversations:
        return False

    def fresh_cursor(source, resource, scope):
        cursor = cursors.get((source, resource, scope))
        return (cursor is not None and cursor.last_success_at is not None
            and cursor.sync_status not in {"degraded", "failed"}
            and now - cursor.last_success_at <= WATERMARK_STALE_AFTER)

    if not all(source == "okki" and fresh_cursor(source, "orders", scope)
               for source, scope in order_scopes):
        return False
    for conversation in conversations:
        if conversation.source_system == "alibaba":
            if not fresh_cursor("alibaba", "inquiries", conversation.source_account_key):
                return False
        elif conversation.source_system == "whatsapp":
            account = wa_accounts.get(conversation.source_account_key)
            if account is None or account.status != "active" or account.last_sync_at is None \
                    or now - account.last_sync_at > WATERMARK_STALE_AFTER:
                return False
        else:
            return False
    return True


def classify(*, days, last_interaction, covered, now, policy=POLICY):
    dates = sorted(set(days))
    if not covered:
        return "unknown", "商业订单或互动来源覆盖尚未核验"
    intervals = [(b-a).days for a,b in zip(dates, dates[1:])]
    if len(dates) >= policy["minimum_commercial_batches"] and intervals:
        center = median(intervals)
        regular = center > 0 and (max(intervals)-min(intervals))/center <= policy["irregular_range_ratio"]
        age = (now.date()-dates[-1]).days
        if regular and center-policy["window_margin_days"] <= age <= center+policy["window_margin_days"]:
            return "reorder", "有效商业批次中位数窗口；提醒核实需求，不代表客户缺货"
    order_age = (now.date()-dates[-1]).days if dates else None
    interaction_age = (now-last_interaction).days if last_interaction else None
    if order_age is not None and order_age <= policy["active_order_days"] or interaction_age is not None and interaction_age <= policy["active_interaction_days"]:
        return "active", "最近有效商业订单或真实客户互动"
    if not dates and interaction_age is not None and interaction_age <= policy["new_interaction_days"]:
        return "new", "未见有效商业订单，近期有真实互动"
    if order_age is not None and order_age <= policy["wake_order_days"]:
        return "wake", "历史成交客户，超过活跃窗口"
    return "sleep", "已核验覆盖，订单与互动均超出候选窗口"


def prototype_comparison(*, days, covered, now, policy=POLICY):
    """Replay the old demo reorder window only; it is never an active policy."""
    dates = sorted(set(days))
    demo = policy["prototype_comparison"]
    if not covered or len(dates) < demo["minimum_orders"]:
        return False
    intervals = [(b-a).days for a,b in zip(dates, dates[1:])]
    center = mean(intervals)
    age = (now.date()-dates[-1]).days
    return center > 0 and demo["lower_ratio"]*center <= age <= demo["upper_ratio"]*center


def list_customers(db, user, *, page, page_size, keyword=None, customer_scope="primary", tier=None, sort="value", focus=None, preview=False,
    sort_field: str | None = None,
    sort_order: str | None = None,
):
    from app.customer.work_item_service import live_user
    user = live_user(db, user)
    perms = set(user.get("permissions", []))
    if "super_admin" in user.get("roles", []):
        perms.add("customer:read_all")
    ids = _scope_customer_ids(db, actor_user_id=int(user["sub"]), perms=perms, customer_scope=customer_scope)
    query = scoped_customer_query(db, user, include_public_pool=False).filter(CustomerAccount.id.in_(ids))
    if keyword and keyword.strip():
        pattern = "%"+keyword.strip()+"%"
        query = query.filter(or_(CustomerAccount.display_name.ilike(pattern), CustomerAccount.customer_code.ilike(pattern), CustomerAccount.canonical_company_name.ilike(pattern)))
    accounts = query.all()
    ids = [row.id for row in accounts]
    now = beijing_now()
    watermarks = _collect_watermarks(db, now)
    cursors = {(row.source_system, row.resource_type, row.scope_key): row
               for row in db.query(CustomerSyncCursor).all()}
    wa_accounts = {row.account_uid: row for row in db.query(WhatsAppAccount).all()}
    orders = db.query(CustomerOrder, logical_owner_expression(CustomerOrder, "order").label("logical_id")).filter(logical_owner_expression(CustomerOrder,"order").in_(ids)).all()
    by_order = defaultdict(list)
    for row in db.query(CustomerOrderItem).filter(CustomerOrderItem.order_id.in_([row.id for row,_ in orders])):
        by_order[row.order_id].append(row)
    by_customer = defaultdict(list)
    excluded = defaultdict(Counter)
    for order, logical_id in orders:
        kind = derive_order_type(by_order[order.id])
        if order.is_valid_business_order and kind in {"bulk", "mixed"} and order.account_date is not None:
            by_customer[logical_id].append(order)
        else:
            excluded[logical_id][kind if order.is_valid_business_order else "invalid"] += 1
    all_orders = defaultdict(list)
    for order, logical_id in orders:
        all_orders[logical_id].append(order)
    identity_scopes = defaultdict(set)
    identity_match = logical_subject_matches_customer(CustomerExternalIdentity,
        "external_identity", CustomerAccount)
    for identity, logical_id in db.query(CustomerExternalIdentity, CustomerAccount.id).join(
            CustomerAccount, identity_match).filter(CustomerAccount.id.in_(ids),
            CustomerExternalIdentity.source_system == "okki",
            CustomerExternalIdentity.status == "active",
            CustomerExternalIdentity.verification_status == "verified",
            CustomerExternalIdentity.identity_strength == "strong",
            CustomerExternalIdentity.cardinality == "one_to_one"):
        identity_scopes[logical_id].add(("okki", identity.source_account_key))
    # Conversations carry the true logical customer; generated research is never an interaction.
    conversation_owner = logical_owner_expression(CustomerConversation, "conversation")
    conversations = defaultdict(list)
    for conversation, logical_id in db.query(CustomerConversation, conversation_owner).filter(
            conversation_owner.in_(ids)).all():
        conversations[logical_id].append(conversation)
    source_owner = logical_owner_expression(CustomerSourceRecord, "source_record")
    visible_scopes = ("all_authorized", "customer_team", "management") if "customer:read_all" in perms else (
        "all_authorized", "customer_team")
    # Aggregate by the message's concrete FK first. MySQL ONLY_FULL_GROUP_BY cannot
    # group by the correlated logical-owner expression and select it at the same time.
    latest_per_conversation = db.query(
        CustomerMessage.conversation_id.label("conversation_id"),
        func.max(CustomerMessage.sent_at).label("last_sent_at"),
    ).select_from(CustomerMessage).join(CustomerConversation,
        CustomerConversation.id == CustomerMessage.conversation_id).join(CustomerSourceRecord,
        CustomerSourceRecord.id == CustomerMessage.source_record_id).filter(conversation_owner.in_(ids),
        source_owner == conversation_owner,
        CustomerSourceRecord.visibility_scope.in_(visible_scopes),
        CustomerMessage.direction.in_(("in", "out")), CustomerMessage.sent_at <= now,
    ).group_by(CustomerMessage.conversation_id).subquery()
    interactions = {}
    for logical_id, sent_at in db.query(conversation_owner,
            latest_per_conversation.c.last_sent_at).select_from(CustomerConversation).join(
            latest_per_conversation,
            latest_per_conversation.c.conversation_id == CustomerConversation.id):
        if logical_id not in interactions or sent_at > interactions[logical_id]:
            interactions[logical_id] = sent_at
    projections = {row.customer_id: row for row in db.query(CustomerListProjection).filter(CustomerListProjection.customer_id.in_(ids))}
    policy_active = POLICY["status"] == "approved" and POLICY["approved_by"] is not None and POLICY["effective_at"] is not None
    results = []
    for account in accounts:
        commercial = by_customer[account.id]
        days = [row.account_date for row in commercial]
        last = interactions.get(account.id)
        # A row's synced_at alone cannot prove absence of unknown orders or missing source pages.
        covered = _source_coverage(all_orders[account.id], conversations[account.id],
            identity_scopes[account.id], cursors, wa_accounts, now)
        candidate, reason = classify(days=days, last_interaction=last, covered=covered, now=now)
        row = _summary(db, account, projection=projections.get(account.id), has_primary=True)
        amount_known = all(order.amount_original is not None and order.currency and order.amount_usd is not None for order in commercial)
        prototype_reorder = prototype_comparison(days=days, covered=covered, now=now) if preview else False
        row.update({"tier": candidate if policy_active or preview else "unknown",
            "tier_reason": reason if policy_active or preview else "统一候选策略等待业务回放定版",
            "tier_policy_version": POLICY["version"], "segment_policy_status": POLICY["status"],
            "order_count": len(set(days)), "order_amount_usd": str(sum((order.amount_usd for order in commercial), Decimal(0))) if commercial and amount_known else None,
            "amount_quality": "projected" if amount_known else "unknown", "excluded_orders": dict(excluded[account.id]),
            "last_order_at": max(days).isoformat() if days else None, "last_interaction_at": iso_beijing(last),
            "primary_product_families": sorted({item.product_family for order in commercial for item in by_order[order.id] if item.product_family}),
            "data_as_of": iso_beijing(now), "source_coverage": "verified" if covered else "unknown"})
        if preview:
            row["candidate_tier"] = candidate
            row["prototype_reorder"] = prototype_reorder
            row["prototype_comparison_reason"] = "三单均值演示窗口，不作为正式策略" if prototype_reorder else "未命中三单均值演示窗口"
        results.append(row)
    summary = dict(Counter(row["tier"] for row in results))
    all_results = results
    if tier:
        results = [row for row in results if row["tier"] == tier]
    keys = {"value": "order_amount_usd", "order": "last_order_at", "contact": "last_interaction_at", "profile": "profile_completeness", "updated": "updated_at"}
    key = keys[sort]
    results.sort(key=lambda row: (row[key] is not None, Decimal(row[key] or 0) if sort == "value" else row[key] or "", row["customer_id"]), reverse=True)
    results = apply_items_sort(results, sort_field, sort_order, {**{key: key for key in ("display_name", "tier", "order_count", "last_interaction_at", "profile_completeness")}, "order_amount_usd": lambda row: Decimal(row["order_amount_usd"]) if row["order_amount_usd"] is not None else None}, tie_breaker="customer_id")
    response = {"items": results[(page-1)*page_size:page*page_size], "total": len(results), "page": page, "page_size": page_size,
        "segment_summary": summary, "policy_version": POLICY["version"], "policy_status": POLICY["status"], "source_watermarks": watermarks}
    if preview:
        response["replay_summary"] = {"sample_size": len(accounts),
            "candidate_counts": dict(Counter(row["candidate_tier"] for row in all_results)),
            "prototype_reorder_count": sum(row["prototype_reorder"] for row in all_results),
            "coverage_unknown_count": sum(row["source_coverage"] == "unknown" for row in all_results),
            "window_disagreement_count": sum((row["candidate_tier"] == "reorder") != row["prototype_reorder"] for row in all_results)}
    return response
