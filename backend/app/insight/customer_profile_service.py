"""客户画像服务 — Profile CRUD + 事件入口

活画像的核心逻辑：从现有 CustomerOpportunity 数据创建/更新画像，
插入事件流，重算优先级分数。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.insight.models import (
    CustomerProfile,
    CustomerProfileEvent,
    CustomerOpportunity,
)

logger = logging.getLogger("insight.profile")


# ── 画像 CRUD ───────────────────────────────────────────


def get_or_create_profile(
    db: Session,
    customer_name: str,
    customer_region: Optional[str] = None,
    customer_external_id: Optional[str] = None,
    source: str = "alibaba_international",
    owner_user_id: Optional[int] = None,
    owner_resolve_status: str = "unassigned",
) -> CustomerProfile:
    """按 name+region 或 external_id 去重获取/创建画像。"""
    profile = None

    # 优先按 external_id 查找
    if customer_external_id:
        profile = db.query(CustomerProfile).filter(
            CustomerProfile.customer_external_id == customer_external_id,
        ).first()

    # 按 name+region 查找
    if not profile and customer_name:
        q = db.query(CustomerProfile).filter(
            CustomerProfile.customer_name == customer_name,
        )
        if customer_region:
            q = q.filter(CustomerProfile.customer_region == customer_region)
        profile = q.first()

    if profile:
        # 更新 owner（如果新信息更完整）
        if owner_user_id and not profile.owner_user_id:
            profile.owner_user_id = owner_user_id
            profile.owner_resolve_status = "resolved"
        if customer_external_id and not profile.customer_external_id:
            profile.customer_external_id = customer_external_id
        db.commit()
        db.refresh(profile)
        return profile

    # 新建画像
    now = datetime.utcnow()
    profile = CustomerProfile(
        customer_name=customer_name or "",
        customer_region=customer_region,
        customer_external_id=customer_external_id,
        owner_user_id=owner_user_id,
        owner_resolve_status=owner_resolve_status if owner_user_id else "unassigned",
        source=source,
        first_seen_at=now,
        last_event_at=now,
        status="active",
        profile_tags=[],
        profile_signals_json=[],
        weight_adjustments={},
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    logger.info("Created profile id=%s name=%s", profile.id, customer_name)
    return profile


def get_profile(db: Session, profile_id: int) -> Optional[CustomerProfile]:
    return db.query(CustomerProfile).filter(CustomerProfile.id == profile_id).first()


def get_profile_by_opportunity(db: Session, opportunity_id: int) -> Optional[CustomerProfile]:
    """通过事件流反查画像（一个 opportunity 可能对应一个 profile）。"""
    evt = db.query(CustomerProfileEvent).filter(
        CustomerProfileEvent.opportunity_id == opportunity_id,
    ).order_by(CustomerProfileEvent.id.desc()).first()
    if not evt:
        return None
    return db.query(CustomerProfile).filter(CustomerProfile.id == evt.profile_id).first()


def list_profiles(
    db: Session,
    owner_user_id: int,
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """业务员可见的画像列表。"""
    query = db.query(CustomerProfile).filter(
        CustomerProfile.owner_user_id == owner_user_id,
    )
    if status:
        query = query.filter(CustomerProfile.status == status)
    else:
        query = query.filter(CustomerProfile.status == "active")

    if keyword:
        kw = f"%{keyword}%"
        query = query.filter(
            (CustomerProfile.customer_name.like(kw))
            | (CustomerProfile.customer_region.like(kw))
            | (CustomerProfile.customer_company.like(kw))
        )

    total = query.count()
    rows = query.order_by(CustomerProfile.priority_score.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return {"total": total, "items": rows, "page": page, "page_size": page_size}


# ── 事件入口 ────────────────────────────────────────────


def ingest_opportunity_event(
    db: Session,
    opportunity: CustomerOpportunity,
    event_type: Optional[str] = None,
) -> Optional[CustomerProfileEvent]:
    """从现有 CustomerOpportunity 创建/更新画像并插入事件。

    在 customer_opportunity_service 的 import/status_change/feedback/assign 后调用。
    """
    try:
        # 确定事件类型
        if not event_type:
            status_to_event = {
                "pending": "new_inquiry",
                "contacted": "replied",
                "replied": "replied",
                "quoted": "quoted",
                "won": "won",
                "lost": "lost",
                "dismissed": "dismissed",
            }
            event_type = status_to_event.get(opportunity.status, "updated")

        # 获取或创建画像
        owner_uid = opportunity.owner_user_id
        profile = get_or_create_profile(
            db,
            customer_name=opportunity.customer_name or "",
            customer_region=opportunity.customer_region,
            customer_external_id=opportunity.customer_external_id,
            source=opportunity.source or "alibaba_international",
            owner_user_id=owner_uid,
            owner_resolve_status=opportunity.owner_resolve_status or "unassigned",
        )

        now = datetime.utcnow()

        # 事件分数：不同事件对优先级的贡献
        score_map = {
            "new_inquiry": 20,
            "replied": 10,
            "quoted": 30,
            "won": 50,
            "lost": -20,
            "dismissed": -30,
            "updated": 5,
        }

        # 构建事件标题
        title_map = {
            "new_inquiry": f"新询盘: {opportunity.customer_name}",
            "replied": f"客户回复: {opportunity.customer_name}",
            "quoted": f"已报价: {opportunity.customer_name}",
            "won": f"已成交: {opportunity.customer_name}",
            "lost": f"已流失: {opportunity.customer_name}",
            "dismissed": f"已忽略: {opportunity.customer_name}",
            "updated": f"信息更新: {opportunity.customer_name}",
        }

        # 检查是否已有同 opportunity + 同 event_type 的事件（防重复）
        existing = db.query(CustomerProfileEvent).filter(
            CustomerProfileEvent.profile_id == profile.id,
            CustomerProfileEvent.opportunity_id == opportunity.id,
            CustomerProfileEvent.event_type == event_type,
        ).first()

        if existing:
            # 更新已有事件而非重复插入
            existing.event_title = title_map.get(event_type, opportunity.title or "")
            existing.occurred_at = now
            existing.event_payload = {
                "status": opportunity.status,
                "priority_level": opportunity.priority_level,
                "confidence_score": opportunity.confidence_score,
                "urgency": opportunity.urgency,
            }
            db.commit()
            db.refresh(existing)
            _recompute_profile_score(db, profile)
            return existing

        evt = CustomerProfileEvent(
            profile_id=profile.id,
            event_source="accio_inquiry",
            event_type=event_type,
            source_ref_type="opportunity",
            source_ref_id=str(opportunity.id),
            opportunity_id=opportunity.id,
            event_title=title_map.get(event_type, opportunity.title or ""),
            event_summary=opportunity.summary or opportunity.title or "",
            event_payload={
                "status": opportunity.status,
                "priority_level": opportunity.priority_level,
                "confidence_score": opportunity.confidence_score,
                "urgency": opportunity.urgency,
            },
            event_score=score_map.get(event_type, 0),
            occurred_at=now,
        )
        db.add(evt)

        # 更新画像统计
        profile.total_opportunities = (
            db.query(CustomerOpportunity)
            .filter(CustomerOpportunity.customer_name == profile.customer_name)
            .count()
        )
        profile.total_events = db.query(CustomerProfileEvent).filter(
            CustomerProfileEvent.profile_id == profile.id
        ).count() + 1  # +1 for the event we just added (not committed yet)
        profile.last_event_at = now
        profile.last_opportunity_at = now

        # 从 opportunity 继承信号
        if opportunity.key_signals_json and not profile.profile_signals_json:
            profile.profile_signals_json = opportunity.key_signals_json
        if opportunity.opening_message_en and not profile.suggested_message:
            profile.suggested_message = opportunity.opening_message_en

        # 继承画像标签
        tags = list(profile.profile_tags or [])
        if opportunity.priority_level == "A" and "高价值" not in tags:
            tags.append("高价值")
        if opportunity.urgency == "urgent" and "紧急" not in tags:
            tags.append("紧急")
        if opportunity.confidence_score and opportunity.confidence_score >= 70 and "高置信" not in tags:
            tags.append("高置信")
        profile.profile_tags = tags

        # 构建画像判断
        if not profile.profile_judgement:
            parts = []
            if opportunity.recommended_strategy:
                parts.append(opportunity.recommended_strategy)
            if opportunity.summary:
                parts.append(opportunity.summary)
            profile.profile_judgement = "；".join(parts) if parts else ""

        db.commit()
        db.refresh(profile)

        _recompute_profile_score(db, profile)
        logger.info("Ingested event profile=%s type=%s opp=%s", profile.id, event_type, opportunity.id)
        return evt

    except Exception:
        logger.exception("Failed to ingest opportunity event opp=%s", opportunity.id)
        return None


def _recompute_profile_score(db: Session, profile: CustomerProfile) -> None:
    """重算画像优先级分数：事件分之和 + 权重调整。"""
    result = db.query(func.coalesce(func.sum(CustomerProfileEvent.event_score), 0)).filter(
        CustomerProfileEvent.profile_id == profile.id,
    ).scalar()

    base_score = int(result)
    adjustments = profile.weight_adjustments or {}
    adj = adjustments.get("score_offset", 0)
    final = max(0, min(100, base_score + adj))

    profile.priority_score = final
    db.commit()
    logger.debug("Profile %s score: base=%s adj=%s final=%s", profile.id, base_score, adj, final)
