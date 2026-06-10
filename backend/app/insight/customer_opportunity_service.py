"""客户机会服务 — ACCIO 导入 + 机会 CRUD + 状态管理"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.insight.models import InquiryImportBatch, CustomerOpportunity, CustomerOpportunityEvent
from app.insight.external_binding_service import resolve_owner, OwnerResult

logger = logging.getLogger("insight.opportunity")

# ── 等级 → due_at 规则 ──────────────────────────────────
_DUE_RULES = {
    "A": lambda now: now + timedelta(hours=2),
    "B": lambda now: now.replace(hour=18, minute=0, second=0, microsecond=0) if now.hour < 18 else (now + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0),
    "C": lambda now: (now + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0),
}
_LEAD_GRADE_MAP = {"A": "A", "B": "B", "C": "C", "D": "D"}


# ── 导入 ────────────────────────────────────────────────

def import_accio_inquiries(db: Session, payload: dict) -> dict:
    """
    处理 ACCIO WORK 推送的询盘 JSON。
    返回 {batch_id, created_count, updated_count, unassigned_count, failed_count, unassigned_external_accounts}
    """
    schema_version = payload.get("schema_version", "")
    batch_id_str = payload.get("batch_id", "")
    items = payload.get("items", [])
    now = datetime.utcnow()

    # 创建或获取批次
    batch = db.query(InquiryImportBatch).filter(InquiryImportBatch.batch_id == batch_id_str).first()
    if not batch:
        batch = InquiryImportBatch(
            batch_id=batch_id_str,
            source="accio_work",
            schema_version=schema_version,
            generated_at=_parse_dt(payload.get("generated_at")),
            time_range_start=_parse_dt(payload.get("time_range", {}).get("start")),
            time_range_end=_parse_dt(payload.get("time_range", {}).get("end")),
            item_count=len(items),
            status="processing",
            raw_payload=payload,
        )
        db.add(batch)
        db.flush()

    created_count = 0
    updated_count = 0
    unassigned_count = 0
    failed_count = 0
    unassigned_accounts = []

    for item in items:
        try:
            conv = item.get("conversation", {})
            bg = item.get("background_check", {})
            seed = item.get("opportunity_seed", {})
            source_key = item.get("source_key", "")

            if not source_key:
                failed_count += 1
                continue

            self_ali_id = conv.get("self_ali_id", "")
            subaccount_name = conv.get("subaccount_name", "")
            buyer_name = conv.get("buyer_name") or "未知买家"
            buyer_country = conv.get("buyer_country")
            buyer_level = conv.get("buyer_level", "")
            latest_content = conv.get("latest_content", "")
            latest_send_time = _parse_dt(conv.get("latest_send_time"))
            chat_link = conv.get("chat_link", "")
            conversation_id = conv.get("conversation_id", "")

            # 归属解析
            owner_result = resolve_owner(
                db,
                provider="alibaba_icbu",
                external_account_id=str(self_ali_id),
                external_display_name=subaccount_name,
                raw_payload=conv,
            )

            # 优先级
            lead_grade = bg.get("lead_grade", "")
            priority_level = _LEAD_GRADE_MAP.get(lead_grade, "C")
            if not lead_grade:
                priority_level = seed.get("priority_level", "C")

            # 置信度
            confidence_score = bg.get("confidence_score", seed.get("confidence_score", 0))

            # 紧急度
            urgency = "normal"
            overdue_minutes = payload.get("filters", {}).get("overdue_minutes")
            if overdue_minutes:
                urgency = "urgent"
            elif priority_level == "A":
                urgency = "high"

            # due_at
            due_at = None
            if priority_level in _DUE_RULES:
                due_at = _DUE_RULES[priority_level](now)

            # 标题
            title = seed.get("title", "") or f"{buyer_name} 值得跟进"

            # 背调
            bg_json = None
            if bg and bg.get("research_status") != "missing":
                bg_json = bg

            # 策略
            strategy = bg.get("next_action") or seed.get("recommended_strategy")

            # 话术
            opening_msg = ""  # ACCIO v1 不含话术，后续 AI 生成
            follow_msg = ""

            # 关键信号
            key_signals = seed.get("key_signals") or bg.get("key_evidence")

            # source_owner_external_json
            source_owner_ext = {
                "provider": "alibaba_icbu",
                "self_ali_id": str(self_ali_id),
                "subaccount_name": subaccount_name,
                "buyer_level": buyer_level,
            }

            # 幂等 upsert
            existing = db.query(CustomerOpportunity).filter(
                CustomerOpportunity.source_key == source_key
            ).first()

            if existing:
                # 更新（不覆盖已处理状态）
                updated_count += 1
                existing.title = title
                existing.summary = latest_content
                existing.background_check_json = bg_json
                existing.recommended_strategy = strategy
                existing.key_signals_json = key_signals
                existing.confidence_score = confidence_score
                existing.priority_level = priority_level
                existing.urgency = urgency
                existing.latest_message_at = latest_send_time
                existing.source_owner_external_json = source_owner_ext
                if existing.status == "pending":
                    existing.due_at = due_at
                existing.updated_at = now
                if existing.owner_resolve_status != owner_result.status:
                    existing.owner_resolve_status = owner_result.status
                    if owner_result.status == "resolved":
                        existing.owner_user_id = owner_result.user_id
                        existing.owner_binding_id = owner_result.binding_id
                # 写事件
                db.add(CustomerOpportunityEvent(
                    opportunity_id=existing.id, event_type="imported",
                    event_payload={"action": "updated"},
                ))
            else:
                # 新建
                opp = CustomerOpportunity(
                    opportunity_type="ali_inquiry",
                    source="alibaba_international",
                    source_key=source_key,
                    source_ref_type="conversation",
                    source_ref_id=conversation_id,
                    owner_user_id=owner_result.user_id,
                    owner_binding_id=owner_result.binding_id,
                    owner_resolve_status=owner_result.status,
                    source_owner_external_json=source_owner_ext,
                    customer_name=buyer_name,
                    customer_region=buyer_country,
                    priority_level=priority_level,
                    confidence_score=confidence_score,
                    urgency=urgency,
                    title=title,
                    summary=latest_content,
                    key_signals_json=key_signals,
                    background_check_json=bg_json,
                    recommended_strategy=strategy,
                    opening_message_en=opening_msg,
                    follow_up_message_en=follow_msg,
                    status="pending",
                    due_at=due_at,
                    latest_message_at=latest_send_time,
                )
                db.add(opp)
                db.flush()
                created_count += 1
                # 写事件
                db.add(CustomerOpportunityEvent(
                    opportunity_id=opp.id, event_type="created",
                    event_payload={"source": "accio_import", "batch_id": batch_id_str},
                ))

            if owner_result.status in ("unassigned", "conflict", "inactive_user"):
                unassigned_count += 1
                if owner_result.status == "unassigned" and str(self_ali_id) not in [a.get("external_account_id") for a in unassigned_accounts]:
                    unassigned_accounts.append({
                        "provider": "alibaba_icbu",
                        "external_account_id": str(self_ali_id),
                        "external_display_name": subaccount_name,
                    })

        except Exception as e:
            logger.error(f"Failed to process item {item.get('source_key', '?')}: {e}")
            failed_count += 1

    # 更新批次统计
    batch.created_count = created_count
    batch.updated_count = updated_count
    batch.unassigned_count = unassigned_count
    batch.failed_count = failed_count
    batch.item_count = len(items)
    batch.status = "success" if failed_count == 0 else ("partial_failed" if created_count + updated_count > 0 else "failed")
    db.commit()

    return {
        "batch_id": batch.id,
        "batch_source_id": batch_id_str,
        "item_count": len(items),
        "created_count": created_count,
        "updated_count": updated_count,
        "unassigned_count": unassigned_count,
        "failed_count": failed_count,
        "status": batch.status,
        "unassigned_external_accounts": unassigned_accounts,
    }


# ── 机会查询 ────────────────────────────────────────────

def get_opportunity(db: Session, opp_id: int) -> CustomerOpportunity | None:
    return db.query(CustomerOpportunity).get(opp_id)


def list_my_opportunities(
    db: Session, user_id: int,
    status: str | None = None, priority_level: str | None = None,
    source: str | None = None, keyword: str | None = None,
    date_from: str | None = None, date_to: str | None = None,
    page: int = 1, page_size: int = 20,
) -> dict:
    q = db.query(CustomerOpportunity).filter(
        CustomerOpportunity.owner_user_id == user_id,
    )
    if status:
        q = q.filter(CustomerOpportunity.status == status)
    if priority_level:
        q = q.filter(CustomerOpportunity.priority_level == priority_level)
    if source:
        q = q.filter(CustomerOpportunity.source == source)
    if keyword:
        kw = f"%{keyword}%"
        q = q.filter(or_(
            CustomerOpportunity.customer_name.like(kw),
            CustomerOpportunity.title.like(kw),
            CustomerOpportunity.summary.like(kw),
        ))
    if date_from:
        q = q.filter(CustomerOpportunity.created_at >= date_from)
    if date_to:
        q = q.filter(CustomerOpportunity.created_at <= date_to)

    total = q.count()
    items = q.order_by(CustomerOpportunity.due_at.asc().nulls_last(), CustomerOpportunity.created_at.desc()) \
        .offset((page - 1) * page_size).limit(page_size).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def list_all_opportunities(
    db: Session,
    status: str | None = None, priority_level: str | None = None,
    owner_user_id: int | None = None, resolve_status: str | None = None,
    keyword: str | None = None,
    page: int = 1, page_size: int = 20,
) -> dict:
    q = db.query(CustomerOpportunity)
    if status:
        q = q.filter(CustomerOpportunity.status == status)
    if priority_level:
        q = q.filter(CustomerOpportunity.priority_level == priority_level)
    if owner_user_id:
        q = q.filter(CustomerOpportunity.owner_user_id == owner_user_id)
    if resolve_status:
        q = q.filter(CustomerOpportunity.owner_resolve_status == resolve_status)
    if keyword:
        kw = f"%{keyword}%"
        q = q.filter(or_(
            CustomerOpportunity.customer_name.like(kw),
            CustomerOpportunity.title.like(kw),
        ))
    total = q.count()
    items = q.order_by(CustomerOpportunity.created_at.desc()) \
        .offset((page - 1) * page_size).limit(page_size).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def list_unassigned_opportunities(db: Session, page: int = 1, page_size: int = 20) -> dict:
    q = db.query(CustomerOpportunity).filter(
        CustomerOpportunity.owner_resolve_status.in_(["unassigned", "conflict", "inactive_user"])
    )
    total = q.count()
    items = q.order_by(CustomerOpportunity.created_at.desc()) \
        .offset((page - 1) * page_size).limit(page_size).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def get_opportunity_stats(db: Session, user_id: int) -> dict:
    """获取当前用户的 KPI 统计"""
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    base = db.query(CustomerOpportunity).filter(CustomerOpportunity.owner_user_id == user_id)

    total = base.count()
    pending = base.filter(CustomerOpportunity.status == "pending").count()
    contacted = base.filter(CustomerOpportunity.status == "contacted").count()
    replied = base.filter(CustomerOpportunity.status == "replied").count()
    quoted = base.filter(CustomerOpportunity.status == "quoted").count()
    won = base.filter(CustomerOpportunity.status == "won").count()
    lost = base.filter(CustomerOpportunity.status == "lost").count()

    # A 类
    a_count = base.filter(CustomerOpportunity.priority_level == "A").count()

    # 超时未处理
    overdue = base.filter(
        CustomerOpportunity.status == "pending",
        CustomerOpportunity.due_at.isnot(None),
        CustomerOpportunity.due_at < now,
    ).count()

    # 今日已联系
    today_contacted = base.filter(
        CustomerOpportunity.status.in_(["contacted", "replied", "quoted"]),
        CustomerOpportunity.handled_at >= today_start,
    ).count()

    return {
        "total": total,
        "pending": pending,
        "contacted": contacted,
        "replied": replied,
        "quoted": quoted,
        "won": won,
        "lost": lost,
        "a_count": a_count,
        "overdue": overdue,
        "today_contacted": today_contacted,
    }


# ── 状态/反馈 ───────────────────────────────────────────

def update_opportunity_status(db: Session, opp_id: int, new_status: str, note: str | None, user_id: int) -> CustomerOpportunity:
    opp = db.query(CustomerOpportunity).get(opp_id)
    if not opp:
        raise ValueError(f"Opportunity {opp_id} not found")
    old_status = opp.status
    opp.status = new_status
    if new_status in ("contacted", "replied", "quoted", "won", "lost", "dismissed"):
        if not opp.handled_at:
            opp.handled_at = datetime.utcnow()
    db.add(CustomerOpportunityEvent(
        opportunity_id=opp_id,
        event_type="status_changed",
        actor_user_id=user_id,
        event_payload={"old_status": old_status, "new_status": new_status, "note": note},
    ))
    db.commit()
    return opp


def add_opportunity_feedback(db: Session, opp_id: int, feedback: str, note: str | None, user_id: int) -> CustomerOpportunityEvent:
    opp = db.query(CustomerOpportunity).get(opp_id)
    if not opp:
        raise ValueError(f"Opportunity {opp_id} not found")
    opp.feedback = feedback
    event = CustomerOpportunityEvent(
        opportunity_id=opp_id,
        event_type="feedback",
        actor_user_id=user_id,
        event_payload={"feedback": feedback, "note": note},
    )
    db.add(event)
    db.commit()
    return event


def assign_opportunity(db: Session, opp_id: int, user_id: int, admin_user_id: int) -> CustomerOpportunity:
    """管理员手动分配机会给指定用户"""
    opp = db.query(CustomerOpportunity).get(opp_id)
    if not opp:
        raise ValueError(f"Opportunity {opp_id} not found")
    old_owner = opp.owner_user_id
    opp.owner_user_id = user_id
    opp.owner_resolve_status = "resolved"
    db.add(CustomerOpportunityEvent(
        opportunity_id=opp_id,
        event_type="assigned",
        actor_user_id=admin_user_id,
        event_payload={"old_owner": old_owner, "new_owner": user_id},
    ))
    db.commit()
    return opp


# ── 辅助 ────────────────────────────────────────────────

def _parse_dt(val) -> datetime | None:
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.strptime(str(val), "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        try:
            return datetime.strptime(str(val), "%Y-%m-%dT%H:%M:%S")
        except (ValueError, TypeError):
            return None
