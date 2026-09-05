"""Shared read-only preview/batch evaluator over current logical customer data."""

from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal
import re

from sqlalchemy import String, and_, cast, func, or_

from app.core.time import beijing_now
from app.customer.logical_customer_service import logical_owner_expression, logical_subject_matches_customer
from app.customer.models import (
    CustomerAccount, CustomerAction, CustomerAnnotation, CustomerAssignment, CustomerContactPoint,
    CustomerConversation, CustomerEvent, CustomerOrder, CustomerOrderItem, CustomerTargetMatch,
    CustomerSuppressionRegistry,
)
from app.sales_automation.pool_rule_schema import PoolRules, PoolQuotas


REASONS = {
    "identity_status": "身份待确认", "assigned": "已有主负责人", "dnc": "禁止开发",
    "country": "国家不符", "contact": "无符合条件的联系渠道", "commerce": "成交条件不符",
    "product": "产品不符或缺少明细", "order_date_missing": "订单日期缺失",
    "recent_order": "近期有下单", "followup_missing": "跟进日期缺失",
    "recent_followup": "近期有跟进", "quota": "超出配额",
}


def _text(value):
    return re.sub(r"[\s_\-]+", "", (value or "").casefold())


def matches_commerce(orders, items, rule):
    amounts = [Decimal(str(o.amount_usd)) for o in orders]
    financial = (len(orders) >= rule.min_orders and sum(amounts) > Decimal(str(rule.total_usd_gt))) or any(a > Decimal(str(rule.single_usd_gt)) for a in amounts)
    sample = bool(orders) and all(items[o.id] and all(i.item_type == "sample" for i in items[o.id]) for o in orders)
    return financial, sample and rule.allow_sample_only


def evaluate(db, rules, quotas, *, watermark=None, now=None, lock_accounts=False):
    rules = PoolRules.model_validate(rules)
    quotas = PoolQuotas.model_validate(quotas)
    now = now or beijing_now()
    query = db.query(CustomerAccount).filter(CustomerAccount.record_status == "active")
    if watermark is not None:
        query = query.filter(CustomerAccount.id <= watermark)
    query = query.order_by(CustomerAccount.id)
    if lock_accounts:
        query = query.populate_existing().with_for_update()
    candidates = query.all()
    # DNC is live policy, even when the batch's commercial cutoff is frozen.
    policy_now = beijing_now()
    annotation_owner = logical_owner_expression(CustomerAnnotation, "annotation")
    denied = {owner for (owner,) in db.query(annotation_owner).filter(
        CustomerAnnotation.annotation_type == "do_not_contact", CustomerAnnotation.status == "active",
        CustomerAnnotation.policy_effective_at <= policy_now,
        or_(CustomerAnnotation.policy_scope_type == "global", and_(CustomerAnnotation.policy_scope_type == "source", CustomerAnnotation.policy_scope_ref_id == "public_pool")),
    )}
    denied.update(owner for (owner,) in db.query(CustomerSuppressionRegistry.mapped_customer_id).filter(
        CustomerSuppressionRegistry.status == "active", CustomerSuppressionRegistry.effective_at <= policy_now,
        or_(CustomerSuppressionRegistry.scope_type == "global", and_(CustomerSuppressionRegistry.scope_type == "source", CustomerSuppressionRegistry.scope_ref_id == "public_pool")),
    ))
    assigned = {v for (v,) in db.query(CustomerAssignment.customer_id).filter(
        CustomerAssignment.assignment_role == "primary", CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    )}
    scores = dict(db.query(CustomerTargetMatch.customer_id, func.max(CustomerTargetMatch.match_score)).filter(CustomerTargetMatch.is_current.is_(True)).group_by(CustomerTargetMatch.customer_id).all())
    exclusions = Counter()
    eligible = []
    # Bound IN lists and avoid a query per order/contact/customer for commercial data.
    for offset in range(0, len(candidates), 300):
        chunk = candidates[offset:offset + 300]
        ids = [a.id for a in chunk]
        orders = defaultdict(list)
        owner = logical_owner_expression(CustomerOrder, "order")
        for order, customer_id in db.query(CustomerOrder, owner).filter(owner.in_(ids), CustomerOrder.is_valid_business_order.is_(True)):
            orders[customer_id].append(order)
        items = defaultdict(list)
        for item in db.query(CustomerOrderItem).join(CustomerOrder, CustomerOrder.id == CustomerOrderItem.order_id).filter(owner.in_(ids), CustomerOrder.is_valid_business_order.is_(True)):
            items[item.order_id].append(item)
        contacts = defaultdict(set)
        for customer_id, point_type, platform in db.query(CustomerAccount.id, CustomerContactPoint.point_type, CustomerContactPoint.platform).join(
            CustomerContactPoint, logical_subject_matches_customer(CustomerContactPoint, "contact_point", CustomerAccount),
        ).filter(CustomerAccount.id.in_(ids), func.length(func.trim(CustomerContactPoint.normalized_value)) > 0, CustomerContactPoint.verification_status.notin_(["invalid", "disputed"]), CustomerContactPoint.contactability_status.in_(["allowed", "unknown"])):
            if point_type == "phone":
                contacts[customer_id].add("phone")
            elif point_type == "social" and platform in {"instagram", "facebook"}:
                contacts[customer_id].add(platform)
        latest = {}
        conversation_owner = logical_owner_expression(CustomerConversation, "conversation")
        for customer_id, last in db.query(conversation_owner, func.max(CustomerConversation.last_message_at)).filter(conversation_owner.in_(ids)).group_by(conversation_owner):
            if last:
                latest[customer_id] = last
        # Sales activity timestamps are actual occurred_at, not completion time.
        action_owner = logical_owner_expression(CustomerAction, "action")
        for event, customer_id in db.query(CustomerEvent, action_owner).join(CustomerAction, cast(CustomerAction.id, String) == CustomerEvent.source_ref_id).filter(
            CustomerEvent.event_type == "sales_activity.logged", CustomerEvent.source_ref_type == "action", action_owner.in_(ids),
        ):
            if event.event_payload.get("channel") != "internal":
                latest[customer_id] = max(latest.get(customer_id, event.occurred_at), event.occurred_at)
        terms, excluded_terms = [_text(v) for v in rules.product_terms], [_text(v) for v in rules.product_exclusions]
        for account in chunk:
            reason = None
            customer_orders = orders[account.id]
            financial, sample = matches_commerce(customer_orders, items, rules.commerce)
            products = [_text(" ".join(filter(None, [i.product_family, i.model, i.product_name]))) for o in customer_orders for i in items[o.id]]
            product_match = any(any(t in p for t in terms) and not any(t in p for t in excluded_terms) for p in products)
            dates = [o.account_date for o in customer_orders]
            last = latest.get(account.id)
            if account.identity_status not in {"identified", "verified"}:
                reason = "identity_status"
            elif account.id in assigned:
                reason = "assigned"
            elif account.id in denied:
                reason = "dnc"
            elif account.primary_country_code not in rules.countries:
                reason = "country"
            elif not contacts[account.id].intersection(rules.contact_channels):
                reason = "contact"
            elif not (financial or sample):
                reason = "commerce"
            elif not product_match and not (sample and not rules.commerce.sample_requires_product):
                reason = "product"
            elif not dates or any(d is None for d in dates):
                reason = "order_date_missing"
            elif max(dates) >= (now - timedelta(days=rules.no_order_days)).date():
                reason = "recent_order"
            elif last is None and rules.missing_followup == "exclude":
                reason = "followup_missing"
            elif last is not None and last >= now - timedelta(days=rules.no_followup_days):
                reason = "recent_followup"
            if reason:
                exclusions[reason] += 1
                continue
            score = scores.get(account.id, 0)
            eligible.append({"account": account, "tier": "T1" if score >= 80 else "T2" if score >= 60 else "T3", "instagram": "instagram" in contacts[account.id], "commerce_path": "financial" if financial else "sample_only"})
    eligible.sort(key=lambda item: (-(rules.prefer_instagram and item["instagram"]), item["account"].id))
    selected, tier_counts = [], Counter()
    for item in eligible:
        if len(selected) >= quotas.total_limit or tier_counts[item["tier"]] >= quotas.tiers[item["tier"]]:
            exclusions["quota"] += 1
        else:
            selected.append(item)
            tier_counts[item["tier"]] += 1
    summary = {
        "candidate_count": len(candidates), "eligible_count": len(eligible), "selected_count": len(selected),
        "selected_by_tier": {tier: tier_counts[tier] for tier in quotas.tiers},
        "instagram_selected": sum(item["instagram"] for item in selected),
        "exclusions": [{"code": code, "label": label, "count": exclusions[code]} for code, label in REASONS.items()],
        "evaluated_at": now.isoformat(),
    }
    return selected, summary
