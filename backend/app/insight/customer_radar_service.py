"""客户经营雷达引擎 — 经营线索分组 + 行动推荐

MVP 策略：纯规则引擎，无 AI 调用。
行动推荐在查询时懒生成，首访触发、后续缓存。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.insight.models import (
    CustomerAction,
    CustomerOpportunity,
    CustomerProfile,
    CustomerProfileEvent,
)

logger = logging.getLogger("insight.radar")


# ── 经营线索分组定义 ─────────────────────────────────────

THREAD_GROUPS: Dict[str, Dict[str, Any]] = {
    "new_inquiry": {
        "label": "新询盘响应",
        "priority_label": "优先",
        "color": "blue",
        "sort": 10,
        "icon": "MailPlus",
        "desc": "需要快速判断和首回",
    },
    "sample_delivery": {
        "label": "样单/交付反馈",
        "priority_label": "优先",
        "color": "green",
        "sort": 20,
        "icon": "PackageCheck",
        "desc": "最容易被漏掉，但可能更接近成交",
    },
    "key_account": {
        "label": "大客户维护",
        "priority_label": "保持",
        "color": "purple",
        "sort": 30,
        "icon": "Gem",
        "desc": "不紧急但不能长期忽略",
    },
    "reorder_window": {
        "label": "复购窗口",
        "priority_label": "重点",
        "color": "teal",
        "sort": 40,
        "icon": "Repeat",
        "desc": "补货和新品推荐机会",
    },
    "reactivation": {
        "label": "老客唤醒",
        "priority_label": "重点",
        "color": "red",
        "sort": 50,
        "icon": "BellRing",
        "desc": "用历史订单重新切入",
    },
    "public_pool": {
        "label": "公海验证",
        "priority_label": "顺手",
        "color": "gray",
        "sort": 60,
        "icon": "Database",
        "desc": "低成本验证新增客户",
    },
}


# ── 行动模板（按 thread_group）─────────────────────────

_ACTION_TEMPLATES = {
    "new_inquiry": {
        "next_action": "回复询盘，确认需求后推荐热销品",
        "reason_template": "新询盘待响应：{name} 对你的产品感兴趣",
        "message_template": (
            "Hi {name}, thanks for your inquiry. "
            "Could you share your target products, quantity and delivery timeline "
            "so I can recommend the best options for you?"
        ),
    },
    "sample_delivery": {
        "next_action": "追样单使用反馈，推进批量",
        "reason_template": "{name} 已收到样单/报价，正处于反馈窗口",
        "message_template": (
            "Hi {name}, I hope everything is going well. "
            "Have you had a chance to evaluate the samples? "
            "I'd love to hear your feedback and help with your bulk order plan."
        ),
    },
    "key_account": {
        "next_action": "发送新品信息或补货提醒",
        "reason_template": "大客户 {name} 需要周期性维护，避免被新询盘挤掉",
        "message_template": (
            "Hi {name}, I wanted to share some new product updates "
            "that match your previous preferences. "
            "Would you like me to send some details?"
        ),
    },
    "reorder_window": {
        "next_action": "用补货窗口唤醒",
        "reason_template": "{name} 进入复购周期，适合补货提醒",
        "message_template": (
            "Hi {name}, many customers are preparing restock plans "
            "for the next sales cycle. "
            "Would you like updated pricing or new product recommendations?"
        ),
    },
    "reactivation": {
        "next_action": "用历史订单和新品重新切入",
        "reason_template": "{name} 超过90天未互动，适合低成本唤醒",
        "message_template": (
            "Hi {name}, it's been a while since our last conversation. "
            "We have some exciting new products that might interest you. "
            "Would you like me to share a quick overview?"
        ),
    },
    "public_pool": {
        "next_action": "发送低风险开发信",
        "reason_template": "公海客户 {name} 画像匹配，适合低成本验证",
        "message_template": (
            "Hi {name}, I noticed your business focus aligns well with our products. "
            "Would you be open to receiving some samples to compare quality?"
        ),
    },
}


# ── 规则引擎：经营线索分类 ───────────────────────────────


def compute_thread_group(
    profile: CustomerProfile,
    latest_opportunities: List[CustomerOpportunity],
) -> str:
    """根据画像和最近机会数据，返回经营线索分组（首匹配规则链）。"""
    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)
    ninety_days_ago = now - timedelta(days=90)

    # 分离不同状态的机会
    pending_opps = [o for o in latest_opportunities if o.status in ("pending", "contacted")]
    recent_pending = [o for o in pending_opps if o.created_at and o.created_at >= seven_days_ago]
    quoted_won = [o for o in latest_opportunities if o.status in ("quoted", "won")]
    recent_quoted_won = [o for o in quoted_won if o.updated_at and o.updated_at >= thirty_days_ago]
    old_quoted_won = [o for o in quoted_won if o.updated_at and thirty_days_ago >= o.updated_at >= ninety_days_ago]

    # 规则链（优先级从高到低）
    # 1. 有近期 pending/contacted 机会 → 新询盘
    if recent_pending:
        return "new_inquiry"

    # 2. 有近期 quoted/won → 样单反馈
    if recent_quoted_won:
        return "sample_delivery"

    # 3. A 级 + ≥3 个机会 → 大客户维护
    if profile.total_opportunities >= 3:
        has_a = any(o.priority_level == "A" for o in latest_opportunities)
        if has_a:
            return "key_account"

    # 4. 30-90 天内有 won/quoted → 复购窗口
    if old_quoted_won:
        return "reorder_window"

    # 5. 最后活跃 > 90 天 → 老客唤醒
    if profile.last_event_at and profile.last_event_at < ninety_days_ago:
        return "reactivation"

    # 6. 无归属 → 公海
    if profile.owner_resolve_status != "resolved":
        return "public_pool"

    # 7. 兜底 → 大客户
    return "key_account"


# ── 行动生成 ─────────────────────────────────────────────


def generate_daily_actions(
    db: Session,
    owner_user_id: int,
    action_date: Optional[date] = None,
) -> List[CustomerAction]:
    """为指定业务员生成今日行动（懒生成：首访触发）。

    1. 查询该用户的所有活跃画像
    2. 对每个画像查最近的机会数据
    3. 规则分类 + 生成行动
    4. Upsert 到 ark_customer_actions
    """
    if not action_date:
        action_date = date.today()

    # 清除该用户今日旧行动
    db.query(CustomerAction).filter(
        CustomerAction.owner_user_id == owner_user_id,
        CustomerAction.action_date == action_date,
    ).delete()
    db.flush()

    # 查询活跃画像
    profiles = db.query(CustomerProfile).filter(
        CustomerProfile.owner_user_id == owner_user_id,
        CustomerProfile.status == "active",
    ).all()

    now = datetime.utcnow()
    actions = []

    for profile in profiles:
        # 查询该画像关联的机会（通过 customer_name 匹配）
        opportunities = db.query(CustomerOpportunity).filter(
            CustomerOpportunity.owner_user_id == owner_user_id,
            CustomerOpportunity.customer_name == profile.customer_name,
        ).order_by(CustomerOpportunity.created_at.desc()).limit(10).all()

        if not opportunities and not profile.customer_external_id:
            # 无任何机会且无外部ID的画像跳过（极端情况）
            continue

        # 分类
        thread = compute_thread_group(profile, opportunities)
        template = _ACTION_TEMPLATES[thread]
        thread_info = THREAD_GROUPS[thread]

        # 构建推荐原因
        name = profile.customer_name or "客户"
        reason = template["reason_template"].format(name=name)

        # 构建推荐话术（优先用已有话术）
        message = profile.suggested_message
        if not message and opportunities:
            opp = opportunities[0]
            message = opp.opening_message_en
        if not message:
            message = template["message_template"].format(name=name)

        # 构建下一步
        next_action = template["next_action"]

        # 依据数据
        opp_ids = [o.id for o in opportunities[:3]]
        latest_status = opportunities[0].status if opportunities else "unknown"
        evidence = {
            "opportunity_ids": opp_ids,
            "latest_status": latest_status,
            "thread_group_reason": thread,
        }

        # 排序权重：priority_score + thread 排序加分
        sort_order = profile.priority_score * 10 + (100 - thread_info["sort"])

        action = CustomerAction(
            profile_id=profile.id,
            owner_user_id=owner_user_id,
            thread_group=thread,
            thread_priority=thread_info["priority_label"],
            action_reason=reason,
            suggested_next_action=next_action,
            suggested_message=message,
            source_evidence=evidence,
            action_status="pending",
            action_date=action_date,
            sort_order=sort_order,
        )
        db.add(action)
        actions.append(action)

    db.commit()
    # refresh to get IDs
    for a in actions:
        db.refresh(a)

    logger.info("Generated %d actions for user=%s date=%s", len(actions), owner_user_id, action_date)
    return actions


def get_daily_focus(
    db: Session,
    owner_user_id: int,
    action_date: Optional[date] = None,
    thread_group: Optional[str] = None,
) -> dict:
    """获取今日经营重点（懒生成）。"""
    if not action_date:
        action_date = date.today()

    # 检查是否已有今日行动
    existing = db.query(CustomerAction).filter(
        CustomerAction.owner_user_id == owner_user_id,
        CustomerAction.action_date == action_date,
    ).count()

    if existing == 0:
        generate_daily_actions(db, owner_user_id, action_date)

    # 查询行动
    query = db.query(CustomerAction).filter(
        CustomerAction.owner_user_id == owner_user_id,
        CustomerAction.action_date == action_date,
    )
    if thread_group:
        query = query.filter(CustomerAction.thread_group == thread_group)

    all_actions = query.order_by(CustomerAction.sort_order.desc()).all()

    # 按线索分组
    grouped: Dict[str, List] = {}
    for action in all_actions:
        grouped.setdefault(action.thread_group, []).append(action)

    # 构建分组列表（按 THREAD_GROUPS 的 sort 排序）
    threads = []
    for group_key in sorted(THREAD_GROUPS.keys(), key=lambda k: THREAD_GROUPS[k]["sort"]):
        group_actions = grouped.get(group_key, [])
        if not group_actions:
            continue
        info = THREAD_GROUPS[group_key]
        # 序列化行动
        serialized = [_serialize_action(a) for a in group_actions]
        threads.append({
            "group": group_key,
            "label": info["label"],
            "priority_label": info["priority_label"],
            "color": info["color"],
            "desc": info["desc"],
            "count": len(group_actions),
            "actions": serialized,
        })

    # 统计
    pending = sum(1 for a in all_actions if a.action_status == "pending")
    done = sum(1 for a in all_actions if a.action_status == "done")
    dismissed = sum(1 for a in all_actions if a.action_status == "dismissed")
    snoozed = sum(1 for a in all_actions if a.action_status == "snoozed")

    return {
        "action_date": str(action_date),
        "threads": threads,
        "summary": {
            "total": len(all_actions),
            "pending": pending,
            "done": done,
            "dismissed": dismissed,
            "snoozed": snoozed,
        },
    }


def get_thread_counts(db: Session, owner_user_id: int, action_date: Optional[date] = None) -> dict:
    """各线索数量（侧边栏角标用）。"""
    if not action_date:
        action_date = date.today()

    # 确保行动已生成
    existing = db.query(CustomerAction).filter(
        CustomerAction.owner_user_id == owner_user_id,
        CustomerAction.action_date == action_date,
    ).count()
    if existing == 0:
        generate_daily_actions(db, owner_user_id, action_date)

    rows = db.query(
        CustomerAction.thread_group,
        func.count(CustomerAction.id),
    ).filter(
        CustomerAction.owner_user_id == owner_user_id,
        CustomerAction.action_date == action_date,
    ).group_by(CustomerAction.thread_group).all()

    counts = {group_key: 0 for group_key in THREAD_GROUPS}
    for group, cnt in rows:
        counts[group] = cnt

    return counts


# ── 行动操作 ─────────────────────────────────────────────


def complete_action(
    db: Session,
    action_id: int,
    user_id: int,
    feedback: Optional[str] = None,
    note: Optional[str] = None,
) -> CustomerAction:
    action = db.query(CustomerAction).filter(CustomerAction.id == action_id).first()
    if not action:
        raise ValueError(f"行动不存在: id={action_id}")
    action.action_status = "done"
    action.completed_at = datetime.utcnow()
    action.completed_by = user_id
    if feedback:
        action.user_feedback = feedback
    if note:
        action.user_note = note
    db.commit()
    db.refresh(action)
    return action


def dismiss_action(
    db: Session,
    action_id: int,
    user_id: int,
    note: Optional[str] = None,
) -> CustomerAction:
    action = db.query(CustomerAction).filter(CustomerAction.id == action_id).first()
    if not action:
        raise ValueError(f"行动不存在: id={action_id}")
    action.action_status = "dismissed"
    action.completed_at = datetime.utcnow()
    action.completed_by = user_id
    if note:
        action.user_note = note
    db.commit()
    db.refresh(action)
    return action


def snooze_action(
    db: Session,
    action_id: int,
    user_id: int,
    until: datetime,
) -> CustomerAction:
    action = db.query(CustomerAction).filter(CustomerAction.id == action_id).first()
    if not action:
        raise ValueError(f"行动不存在: id={action_id}")
    action.action_status = "snoozed"
    action.snoozed_until = until
    db.commit()
    db.refresh(action)
    return action


def submit_feedback(
    db: Session,
    action_id: int,
    feedback: str,
    note: Optional[str],
    user_id: int,
) -> CustomerAction:
    """提交反馈并更新画像权重。"""
    action = db.query(CustomerAction).filter(CustomerAction.id == action_id).first()
    if not action:
        raise ValueError(f"行动不存在: id={action_id}")

    action.user_feedback = feedback
    if note:
        action.user_note = note
    db.flush()

    # 更新画像权重调整
    profile = db.query(CustomerProfile).filter(CustomerProfile.id == action.profile_id).first()
    if profile:
        adj = profile.weight_adjustments or {}
        if feedback == "not_useful":
            adj["score_offset"] = adj.get("score_offset", 0) - 5
        elif feedback == "useful":
            adj["score_offset"] = adj.get("score_offset", 0) + 3
        profile.weight_adjustments = adj
        # 重算分数
        from app.insight.customer_profile_service import _recompute_profile_score
        _recompute_profile_score(db, profile)

    db.commit()
    db.refresh(action)
    return action


# ── 序列化 ───────────────────────────────────────────────


def _serialize_action(action: CustomerAction) -> dict:
    profile = action.profile
    return {
        "id": action.id,
        "profile_id": action.profile_id,
        "customer_name": profile.customer_name if profile else "",
        "customer_region": profile.customer_region if profile else "",
        "customer_company": profile.customer_company if profile else "",
        "thread_group": action.thread_group,
        "thread_priority": action.thread_priority,
        "action_reason": action.action_reason,
        "suggested_next_action": action.suggested_next_action,
        "suggested_message": action.suggested_message,
        "source_evidence": action.source_evidence,
        "action_status": action.action_status,
        "action_date": str(action.action_date),
        "user_feedback": action.user_feedback,
        "user_note": action.user_note,
        "sort_order": action.sort_order,
        "profile_tags": profile.profile_tags if profile else [],
        "profile_judgement": profile.profile_judgement if profile else "",
        "profile_priority_score": profile.priority_score if profile else 0,
        "profile_signals_json": profile.profile_signals_json if profile else [],
        "snoozed_until": action.snoozed_until.isoformat() if action.snoozed_until else None,
    }
