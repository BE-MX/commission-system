"""洞见读取、证据重验、反馈、采纳与转待办。"""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now, beijing_today
from app.domestic.models import DomesticCustomer
from app.domestic_followup.collaboration_models import FollowupResponsibility
from app.domestic_followup import config_service, insight_evidence, insight_generation, insight_queue, task_service, visibility
from app.domestic_followup.insight_models import DomesticFollowupInsight, DomesticFollowupInsightSnapshot
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupItem

DAILY_REFRESH_LIMIT = 2


def _target_user(db: Session, current_user: dict, user_id: int | None) -> int:
    actor = visibility.uid(current_user)
    target = user_id or actor
    if target != actor and not visibility.can_read_all(current_user):
        raise PermissionError("只能查看自己的 AI 建议")
    if db.get(ArkUser, target) is None:
        raise LookupError("业务员不存在")
    return target


def _evidence(db: Session, current_user: dict, items: list[DomesticFollowupInsight]) -> dict[int, dict]:
    ids = sorted({record_id for item in items for record_id in item.evidence_followup_ids or []})
    if not ids:
        return {}
    query = db.query(DomesticFollowup).filter(DomesticFollowup.id.in_(ids), DomesticFollowup.status == "confirmed")
    condition = visibility.followup_filter(current_user)
    if condition is not None:
        query = query.filter(condition)
    records = query.all()
    customer_ids = {row.customer_id for row in records}
    authors = {row.author_user_id for row in records}
    customers = {row.id: row for row in db.query(DomesticCustomer).filter(DomesticCustomer.id.in_(customer_ids))}
    users = {row.id: row for row in db.query(ArkUser).filter(ArkUser.id.in_(authors))}
    items_by_followup = defaultdict(list)
    detail_rows = db.query(DomesticFollowupItem).filter(
        DomesticFollowupItem.followup_id.in_([row.id for row in records]),
        DomesticFollowupItem.status != "withdrawn").all()
    for item in detail_rows:
        items_by_followup[item.followup_id].append(item.text)
    return {row.id: {
        "id": row.id, "version": row.version, "customer_id": row.customer_id,
        "shop_name": customers[row.customer_id].shop_name if row.customer_id in customers else None,
        "author_name": users[row.author_user_id].real_name if row.author_user_id in users else None,
        "followup_date": row.followup_date.isoformat(), "channel": row.channel,
        "summary": row.summary, "raw_text": row.raw_text, "items": items_by_followup[row.id],
    } for row in records}


def _deidentify(db: Session, text: str | None) -> str | None:
    if not text:
        return text
    result = text
    names = db.query(DomesticCustomer.shop_name).order_by(DomesticCustomer.shop_name.desc()).all()
    for (name,) in names:
        if name:
            result = result.replace(name, "某客户")
    return result


def _serialize_snapshot(db: Session, current_user: dict, snapshot: DomesticFollowupInsightSnapshot | None,
                        *, company: bool = False) -> dict | None:
    if snapshot is None:
        return None
    items = (db.query(DomesticFollowupInsight)
             .filter(DomesticFollowupInsight.snapshot_id == snapshot.id)
             .order_by(DomesticFollowupInsight.id).all())
    manager = visibility.can_read_all(current_user)
    deidentified = company and not manager
    if deidentified:
        items = [item for item in items if item.category in ("common", "practice")
                 and (item.category != "common" or item.sample_size >= 3)]
    evidence = _evidence(db, {"roles": ["super_admin"]} if deidentified else current_user, items)
    themes, current_sample = {}, set()
    if company and any(item.category in ("common", "practice", "frequency") for item in items):
        _, context = insight_generation._record_context(db, snapshot.period_start, snapshot.period_end)
        themes = insight_generation._themes(context)
        current_sample = {row["customer_id"] for row in context}
    customer_ids = {item.customer_id for item in items if item.customer_id}
    customers = {row.id: row for row in db.query(DomesticCustomer).filter(DomesticCustomer.id.in_(customer_ids))}
    serialized = []
    for item in items:
        valid_ids = insight_evidence.valid_evidence_ids(item, evidence)
        if not valid_ids or len(valid_ids) != len(item.evidence_followup_ids or []):
            continue
        if item.category == "common":
            theme = themes.get(item.theme_key)
            if not theme or theme["customer_count"] != item.sample_size:
                continue
        if item.category in ("practice", "frequency"):
            sample = set(item.sample_customer_ids or [])
            if (len(sample) < 10 or not sample.issubset(current_sample)
                    or insight_evidence.won_customer_ids(db, sample, beijing_today()) != sample):
                continue
        public = item.public_summary or {}
        if deidentified and not public:
            continue
        customer = customers.get(item.customer_id) if item.category in ("deal", "cold", "single") else None
        if customer and not company and item.category in ("deal", "cold"):
            # A previous author's retained history is not a current customer opportunity.
            responsibility = db.get(FollowupResponsibility, customer.id)
            if customer.status != 1 or (responsibility is not None and (
                    responsibility.status not in ("following", "handoff")
                    or responsibility.owner_user_id != snapshot.user_id)):
                continue
            if responsibility is None and customer.owner_user_id != snapshot.user_id:
                continue
        writable = False
        if customer and not deidentified and item.category in ("deal", "cold"):
            permissions = current_user.get("permissions") or []
            writable = ("domestic_followup:write" in permissions or visibility.is_super_admin(current_user))
            if writable:
                writable = visibility.can_write_customer(db, current_user, customer)
        feedback_source = db.get(DomesticFollowupInsight, item.source_insight_id) if item.source_insight_id else item
        own_feedback = (feedback_source.feedbacks or {}).get(str(visibility.uid(current_user)), {}) if feedback_source else {}
        serialized.append({
            "id": item.id, "category": item.category, "customer_id": customer.id if customer and not deidentified else None,
            "shop_name": None if deidentified else (customer.shop_name if customer else None),
            "customer_level": None if deidentified else (customer.customer_level if customer else None),
            "theme_key": None if deidentified else item.theme_key, "title": _deidentify(db, public.get("title")) if deidentified else item.title,
            "body": _deidentify(db, public.get("body")) if deidentified else item.body,
            "suggested_action": (_deidentify(db, public.get("suggested_action")) if deidentified else item.suggested_action),
            "suggested_date": item.suggested_date.isoformat() if item.suggested_date else None,
            "signals": [] if deidentified else (item.signals or []),
            "sample_size": item.sample_size, "numeric_values": {} if deidentified else (item.numeric_values or {}),
            "evidence": [] if deidentified else [evidence[record_id] for record_id in valid_ids],
            "feedback": own_feedback.get("value"),
            "task_id": item.task_id if writable else None, "can_task": writable and not item.task_id,
            "can_record": writable, "can_adopt": manager,
            "adopted": item.adopted_at is not None, "adoption_note": None if deidentified else item.adoption_note,
            "generated_at": item.created_at.isoformat() if item.created_at else None,
            "order_comparison": insight_evidence.order_comparison(db, current_user, item.customer_id, beijing_today())
                                if item.category == "cold" and not deidentified else None,
            "deidentified": deidentified,
        })
    return {"id": snapshot.id, "generated_at": snapshot.generated_at.isoformat() if snapshot.generated_at else None,
            "record_count": snapshot.record_count, "highlights": [] if company else (snapshot.payload or {}).get("highlights", []),
            "empty_sections": (snapshot.payload or {}).get("empty_sections", []), "items": serialized}


def get(db: Session, current_user: dict, *, user_id: int | None = None) -> dict:
    target = _target_user(db, current_user, user_id)
    if insight_queue.recover_stale(db):
        db.commit()
    personal = insight_generation._latest_done(db, "personal", target)
    company = insight_generation._latest_done(db, "company", None)
    running = db.query(DomesticFollowupInsightSnapshot.id).filter(
        DomesticFollowupInsightSnapshot.status.in_(insight_queue.ACTIVE),
        ((DomesticFollowupInsightSnapshot.scope == "personal")
         & (DomesticFollowupInsightSnapshot.user_id == target))
        | (DomesticFollowupInsightSnapshot.scope == "company")).all()
    today = beijing_today()
    used = db.query(DomesticFollowupInsightSnapshot).filter(
        DomesticFollowupInsightSnapshot.requested_by_user_id == visibility.uid(current_user),
        DomesticFollowupInsightSnapshot.request_day == today,
        DomesticFollowupInsightSnapshot.trigger == "manual").count()
    latest = db.query(DomesticFollowupInsightSnapshot).filter(
        DomesticFollowupInsightSnapshot.scope == "personal", DomesticFollowupInsightSnapshot.user_id == target,
    ).order_by(DomesticFollowupInsightSnapshot.id.desc()).first()
    jobs = db.query(DomesticFollowupInsightSnapshot).filter(
        DomesticFollowupInsightSnapshot.requested_by_user_id == visibility.uid(current_user),
        DomesticFollowupInsightSnapshot.request_day == today,
    ).all()
    return {"personal": _serialize_snapshot(db, current_user, personal),
            "company": _serialize_snapshot(db, current_user, company, company=True),
            "target_user_id": target, "refresh": {"status": "running" if running else (latest.status if latest else "idle"),
            "enabled": config_service.get_config(db)["insight_generation_enabled"],
            "jobs": [{"id": job.id, "status": job.status} for job in jobs],
            "remaining": max(DAILY_REFRESH_LIMIT - used, 0), "limit": DAILY_REFRESH_LIMIT}}


def refresh(db: Session, current_user: dict, *, user_id: int | None = None) -> dict:
    config = config_service.get_config(db)
    if not config["insight_generation_enabled"]:
        raise ValueError("AI 建议生成已停用，请联系管理员")
    target = _target_user(db, current_user, user_id)
    insight_queue.lock_admission(db)
    insight_queue.recover_stale(db)
    running = insight_queue.active(db, "personal", target)
    if running:
        return {"status": "running", "snapshot_ids": [running.id], "started": False}
    today = beijing_today()
    used = len(db.query(DomesticFollowupInsightSnapshot).filter(
        DomesticFollowupInsightSnapshot.requested_by_user_id == visibility.uid(current_user),
        DomesticFollowupInsightSnapshot.request_day == today,
        DomesticFollowupInsightSnapshot.trigger == "manual").with_for_update().all())
    if used >= DAILY_REFRESH_LIMIT:
        raise ValueError("每人每天最多重新生成 2 次")
    start, end = today - timedelta(days=59), today
    personal = DomesticFollowupInsightSnapshot(
        scope="personal", user_id=target, status="queued", trigger="manual", period_start=start, period_end=end,
        requested_by_user_id=visibility.uid(current_user), request_day=today,
    )
    db.add(personal)
    db.flush()
    ids = [personal.id]
    company_running = insight_queue.active(db, "company", None)
    if not company_running:
        company = DomesticFollowupInsightSnapshot(
            scope="company", user_id=None, status="queued", trigger="manual_linked", period_start=start, period_end=end,
            requested_by_user_id=visibility.uid(current_user), request_day=today,
        )
        db.add(company)
        db.flush()
        ids.append(company.id)
    return {"status": "running", "snapshot_ids": ids, "started": True}


def refresh_status(db: Session, current_user: dict, snapshot_id: int) -> dict:
    snapshot = db.get(DomesticFollowupInsightSnapshot, snapshot_id)
    actor = visibility.uid(current_user)
    if snapshot is None or not (visibility.can_read_all(current_user)
            or snapshot.requested_by_user_id == actor or snapshot.user_id == actor):
        raise LookupError("生成任务不存在")
    if insight_queue.recover_stale(db):
        db.commit()
        db.refresh(snapshot)
    return {"id": snapshot.id, "status": snapshot.status}


def _visible_item(db: Session, current_user: dict, insight_id: int) -> DomesticFollowupInsight:
    item = db.get(DomesticFollowupInsight, insight_id)
    snapshot = db.get(DomesticFollowupInsightSnapshot, item.snapshot_id) if item else None
    if snapshot and snapshot.status == "done":
        company = snapshot.scope == "company"
        if not company:
            _target_user(db, current_user, snapshot.user_id)
        data = _serialize_snapshot(db, current_user, snapshot, company=company)
        if any(row["id"] == insight_id for row in data["items"]):
            return item
    raise LookupError("建议不存在、证据已失效或无权查看")


def feedback(db: Session, current_user: dict, insight_id: int, value: str | None) -> dict:
    item = _visible_item(db, current_user, insight_id)
    canonical = item.source_insight_id or item.id
    source = db.query(DomesticFollowupInsight).filter_by(id=canonical).populate_existing().with_for_update().one()
    feedbacks = dict(source.feedbacks or {})
    key = str(visibility.uid(current_user))
    if value:
        feedbacks[key] = {"value": value, "at": beijing_now().isoformat()}
    else:
        feedbacks.pop(key, None)
    source.feedbacks = feedbacks
    db.commit()
    return {"id": item.id, "feedback": value}


def adopt(db: Session, current_user: dict, insight_id: int, note: str) -> dict:
    if not visibility.can_read_all(current_user):
        raise PermissionError("公司建议采纳需要全部客户跟进查看权限")
    item = _visible_item(db, current_user, insight_id)
    snapshot = db.get(DomesticFollowupInsightSnapshot, item.snapshot_id)
    if snapshot.scope != "company":
        raise ValueError("个人客户建议请使用生成待办或记跟进")
    item.adopted_by_user_id = visibility.uid(current_user)
    item.adopted_at = beijing_now()
    item.adoption_note = note.strip() or None
    db.commit()
    return {"id": item.id, "adopted": True, "adoption_note": item.adoption_note}


def to_task(db: Session, current_user: dict, insight_id: int, due_date: date, content: str) -> dict:
    item = db.query(DomesticFollowupInsight).filter_by(id=insight_id).populate_existing().with_for_update().first()
    if item is None:
        raise LookupError("建议不存在")
    snapshot = db.get(DomesticFollowupInsightSnapshot, item.snapshot_id)
    if snapshot.status != "done" or snapshot.scope != "personal" or item.category not in ("deal", "cold"):
        raise ValueError("这条建议不能生成客户待办")
    if snapshot.user_id != visibility.uid(current_user) and not visibility.can_read_all(current_user):
        raise PermissionError("只能处理自己的建议")
    visible = _visible_item(db, current_user, insight_id)
    if visible is None:
        raise PermissionError("证据已失效，不能生成待办")
    customer = visibility.ensure_customer_writable(db, current_user, item.customer_id, lock=True)
    if item.task_id:
        return {"id": item.id, "task_id": item.task_id, "created": False}
    if not content.strip():
        raise ValueError("请填写待办内容")
    if due_date < beijing_today():
        raise ValueError("待办日期不能早于今天")
    task, created = task_service.upsert_task(
        db, source_key=f"insight:{item.id}", task_type="plan", purpose="maintenance",
        customer_id=item.customer_id, assignee_user_id=visibility.uid(current_user),
        title=f"{customer.shop_name}：{content.strip()}", due_date=due_date,
        payload={"plan": content.strip(), "insight_id": item.id},
    )
    item.task_id = task.id
    db.commit()
    return {"id": item.id, "task_id": task.id, "created": created}
