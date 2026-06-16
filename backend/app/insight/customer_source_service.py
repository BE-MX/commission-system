"""客户原始记录服务 — 证据层

从 opportunities + events 聚合原始记录，
按类型分 Tab 供前端抽屉展示。
"""

from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from app.insight.models import (
    CustomerOpportunity,
    CustomerProfile,
    CustomerProfileEvent,
)

logger = logging.getLogger("insight.source")


def get_source_records(
    db: Session,
    profile_id: int,
    source_type: Optional[str] = None,
) -> List[dict]:
    """获取画像的原始记录（统一格式）。

    source_type 过滤：opportunity / event / note / all
    """
    profile = db.query(CustomerProfile).filter(CustomerProfile.id == profile_id).first()
    if not profile:
        return []

    records = []

    # ── 询盘/机会记录 ──
    if not source_type or source_type in ("opportunity", "all"):
        opportunities = db.query(CustomerOpportunity).filter(
            CustomerOpportunity.customer_name == profile.customer_name,
        ).order_by(CustomerOpportunity.created_at.desc()).limit(20).all()

        for opp in opportunities:
            records.append({
                "type": "询盘记录",
                "type_code": "opportunity",
                "color": "blue",
                "title": opp.title or f"询盘: {opp.customer_name}",
                "meta": f"{opp.source or 'alibaba'} · {opp.source_ref_id or ''} · {opp.created_at.strftime('%Y-%m-%d') if opp.created_at else ''}",
                "summary": opp.summary or "",
                "raw": _format_opportunity_raw(opp),
                "occurred_at": opp.created_at.isoformat() if opp.created_at else None,
            })

    # ── 事件记录 ──
    if not source_type or source_type in ("event", "all"):
        events = db.query(CustomerProfileEvent).filter(
            CustomerProfileEvent.profile_id == profile_id,
        ).order_by(CustomerProfileEvent.occurred_at.desc()).limit(20).all()

        for evt in events:
            type_label_map = {
                "new_inquiry": "询盘信号",
                "replied": "回复信号",
                "quoted": "报价信号",
                "won": "成交信号",
                "lost": "流失信号",
                "manual_note": "手动备注",
            }
            records.append({
                "type": type_label_map.get(evt.event_type, "事件"),
                "type_code": "event",
                "color": "green" if evt.event_score > 0 else ("red" if evt.event_score < 0 else "gray"),
                "title": evt.event_title,
                "meta": f"{evt.event_source} · {evt.occurred_at.strftime('%Y-%m-%d %H:%M') if evt.occurred_at else ''}",
                "summary": evt.event_summary or "",
                "raw": _format_event_raw(evt),
                "occurred_at": evt.occurred_at.isoformat() if evt.occurred_at else None,
            })

    # 按时间倒序
    records.sort(key=lambda r: r.get("occurred_at") or "", reverse=True)
    return records


def add_manual_note(
    db: Session,
    profile_id: int,
    note_text: str,
    user_id: int,
) -> CustomerProfileEvent:
    """添加手动备注（存为事件）。"""
    from datetime import datetime

    now = datetime.utcnow()
    evt = CustomerProfileEvent(
        profile_id=profile_id,
        event_source="manual_note",
        event_type="manual_note",
        event_title=f"业务员备注",
        event_summary=note_text[:200],
        event_payload={"note": note_text},
        event_score=0,
        actor_user_id=user_id,
        occurred_at=now,
    )
    db.add(evt)

    # 更新画像
    profile = db.query(CustomerProfile).filter(CustomerProfile.id == profile_id).first()
    if profile:
        profile.last_event_at = now
        profile.total_events = (profile.total_events or 0) + 1

    db.commit()
    db.refresh(evt)
    return evt


def _format_opportunity_raw(opp: CustomerOpportunity) -> str:
    """格式化机会的原始文本。"""
    lines = []
    lines.append(f"客户: {opp.customer_name}")
    if opp.customer_region:
        lines.append(f"地区: {opp.customer_region}")
    lines.append(f"等级: {opp.priority_level}")
    lines.append(f"置信度: {opp.confidence_score}")
    lines.append(f"紧急度: {opp.urgency}")
    lines.append(f"状态: {opp.status}")
    if opp.recommended_strategy:
        lines.append(f"策略: {opp.recommended_strategy}")
    if opp.key_signals_json:
        for sig in (opp.key_signals_json if isinstance(opp.key_signals_json, list) else []):
            lines.append(f"· {sig}")
    return "\n".join(lines)


def _format_event_raw(evt: CustomerProfileEvent) -> str:
    """格式化事件的原始文本。"""
    lines = []
    lines.append(f"来源: {evt.event_source}")
    lines.append(f"类型: {evt.event_type}")
    if evt.event_payload:
        payload = evt.event_payload if isinstance(evt.event_payload, dict) else {}
        for k, v in payload.items():
            lines.append(f"{k}: {v}")
    return "\n".join(lines)
