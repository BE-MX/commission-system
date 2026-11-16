from datetime import timedelta
import logging

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now, beijing_today
from app.domestic.models import DomesticCustomer
from app.domestic.shipment_models import DomesticShipment
from app.domestic_followup import config_service, prep_access, template_service, visibility
from app.domestic_followup.constants import OPEN_ITEM_STATES
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupItem, DomesticFollowupTask
from app.domestic_followup.prep_models import DomesticFollowupPrep


logger = logging.getLogger("commission")


class PrepConflictError(Exception):
    pass


def _latest_confirmed(db, customer_id):
    return (db.query(DomesticFollowup).filter(DomesticFollowup.customer_id == customer_id,
            DomesticFollowup.status == "confirmed")
            .order_by(DomesticFollowup.followup_date.desc(), DomesticFollowup.id.desc()).first())


def _open_issues(db, customer_id):
    return db.query(DomesticFollowupItem).filter(
        DomesticFollowupItem.customer_id == customer_id, DomesticFollowupItem.kind == "issue",
        DomesticFollowupItem.status.in_(OPEN_ITEM_STATES),
    )


def _recommendation(db, user, customer, source_task, today) -> dict | None:
    latest = _latest_confirmed(db, customer.id)
    issue = _open_issues(db, customer.id).first()
    readable = visibility.in_customer_scope(db, user, customer.id)
    if issue:
        reason = f"有 1 条未处理完的异常：{issue.text[:80]}" if readable else "有 1 条未处理完的异常，请先核对处理情况"
        return {"code": "T06", "reason": reason}
    if latest and latest.result_code == "客户拒绝":
        return {"code": "T10", "reason": f"{latest.followup_date.isoformat()} 已记录客户拒绝"}
    if source_task and source_task.task_type == "receipt":
        return {"code": "T05", "reason": "从收货回访待办进入"}
    if customer.lifecycle_status == "潜在" and latest is None:
        return {"code": "T02", "reason": "潜在客户还没有已确认跟进"}
    if latest and latest.result_code == "已报价":
        return {"code": "T03", "reason": "最近一次结果是已报价"}
    frequency = (config_service.get_config(db)["frequency_days"] or {}).get(customer.customer_level or "")
    has_order = db.query(DomesticShipment.id).filter(DomesticShipment.customer_id == customer.id).first()
    if has_order and frequency and (latest is None or (today - latest.followup_date).days > frequency):
        return {"code": "T08", "reason": f"有订单且超过 {frequency} 天维护频率"}
    if latest is None or (today - latest.followup_date).days > 60:
        return {"code": "T09", "reason": "超过 60 天没有已确认跟进"}
    return None


def serialize(db, user, prep: DomesticFollowupPrep) -> dict:
    from app.domestic_followup import strategy_service

    customer = db.get(DomesticCustomer, prep.customer_id)
    author = db.get(ArkUser, prep.author_user_id)
    return {
        "id": prep.id, "customer_id": prep.customer_id, "shop_name": customer.shop_name if customer else None,
        "author_user_id": prep.author_user_id, "author_name": author.real_name if author else None,
        "template_code": prep.template_code, "template_version": prep.template_version,
        "goal": prep.goal, "contact_reason": prep.contact_reason, "reason_source": prep.reason_source,
        "reason_date": prep.reason_date.isoformat() if prep.reason_date else None,
        "known_facts": prep.known_facts or [], "to_confirm": prep.to_confirm or [], "answers": prep.answers or {},
        "status": prep.status, "strategy_status": prep.strategy_status, "strategy": prep.strategy,
        "strategy_count": prep.strategy_count, "remaining_generations": max(5 - prep.strategy_count, 0),
        "strategy_error": prep.strategy_error, "source_task_id": prep.source_task_id,
        "followup_id": prep.followup_id, "request_id": prep.request_id, "version": prep.version,
        "created_at": prep.created_at.isoformat() if prep.created_at else None,
        "updated_at": prep.updated_at.isoformat() if prep.updated_at else None,
        "is_current_owner": bool(customer and prep_access.current_owner(db, customer) == visibility.uid(user)),
        "readonly": prep.author_user_id != visibility.uid(user),
        "can_clone": bool(customer and visibility.can_write_customer(db, user, customer)),
        "strategy_stale": strategy_service.is_stale(db, prep),
        "scope_note": "当时的资料范围按作者的权限生成",
    }


def context(db, user, customer_id, source_task_id=None):
    today = beijing_today()
    customer = prep_access.ensure_context_write(db, user, customer_id, source_task_id)
    source_task = db.get(DomesticFollowupTask, source_task_id) if source_task_id else None
    latest_used = (db.query(DomesticFollowupPrep).filter(DomesticFollowupPrep.customer_id == customer_id,
                   DomesticFollowupPrep.status == "used")
                   .order_by(DomesticFollowupPrep.created_at.desc(), DomesticFollowupPrep.id.desc()).first())
    known = []
    if latest_used and prep_access.can_read(db, user, latest_used, customer):
        for fact in (latest_used.known_facts or [])[:8]:
            known.append({**fact, "carried_from_prep_id": latest_used.id})
    return {
        "customer": {"id": customer.id, "shop_name": customer.shop_name},
        "templates": template_service.list_active(db),
        "recommendation": _recommendation(db, user, customer, source_task, today),
        "source_task": {"id": source_task.id, "title": source_task.title} if source_task else None,
        "carried_facts": known, "history_count": _history_count(db, user, customer_id),
        "today": today.isoformat(),
    }


def _history_count(db, user, customer_id):
    try:
        return len(list_preps(db, user, customer_id))
    except PermissionError:
        return 0


def _values(payload):
    return payload.model_dump(mode="json", exclude={"request_id", "customer_id", "source_task_id", "version"})


def _create_matches(prep, payload):
    expected = {"customer_id": payload.customer_id, "source_task_id": payload.source_task_id, **_values(payload)}
    expected["template_code"] = expected["template_code"].upper()
    actual = {"customer_id": prep.customer_id, "source_task_id": prep.source_task_id,
              "template_code": prep.template_code, "goal": prep.goal, "contact_reason": prep.contact_reason,
              "reason_source": prep.reason_source,
              "reason_date": prep.reason_date.isoformat() if prep.reason_date else None,
              "known_facts": prep.known_facts or [], "to_confirm": prep.to_confirm or [], "answers": prep.answers or {}}
    return actual == expected


def _replay_create(db, user, prep, payload):
    prep_access.ensure_author(db, user, prep)
    prep_access.ensure_context_write(db, user, payload.customer_id, payload.source_task_id)
    if not _create_matches(prep, payload):
        raise ValueError("请求编号已用于其他准备内容，请更换请求编号")
    return prep


def _insert_idempotent(db, prep, replay):
    savepoint = db.begin_nested()
    try:
        db.add(prep)
        db.flush()
        savepoint.commit()
        return prep
    except IntegrityError as exc:
        savepoint.rollback()
        logger.warning("followup prep insert conflict request_id=%s: %s", prep.request_id, type(exc.orig).__name__)
        print(f"[domestic_followup] prep insert conflict request_id={prep.request_id}", flush=True)
        existing = (db.query(DomesticFollowupPrep).filter(DomesticFollowupPrep.request_id == prep.request_id)
                    .populate_existing().with_for_update().first())
        if existing is None:
            raise exc
        return replay(existing)


def create(db, user, payload):
    existing = db.query(DomesticFollowupPrep).filter(DomesticFollowupPrep.request_id == payload.request_id).first()
    if existing:
        return _replay_create(db, user, existing, payload)
    prep_access.ensure_context_write(db, user, payload.customer_id, payload.source_task_id)
    template = template_service.get_template(db, payload.template_code)
    data = _values(payload)
    data["template_code"] = template.code
    prep = DomesticFollowupPrep(
        customer_id=payload.customer_id, author_user_id=visibility.uid(user), source_task_id=payload.source_task_id,
        request_id=payload.request_id, template_version=template.version, status="draft", strategy_status="none",
        version=1, **data,
    )
    return _insert_idempotent(db, prep, lambda existing: _replay_create(db, user, existing, payload))


def locked(db, prep_id, *, populate=True):
    query = db.query(DomesticFollowupPrep).filter(DomesticFollowupPrep.id == prep_id)
    if populate:
        query = query.populate_existing().with_for_update()
    row = query.first()
    if row is None:
        raise LookupError("准备卡不存在")
    return row


def update_prep(db, user, prep_id, payload):
    prep = locked(db, prep_id)
    prep_access.ensure_author(db, user, prep)
    if prep.version != payload.version:
        raise PrepConflictError("准备卡已在别处修改，请刷新")
    if prep.status not in ("draft", "ready"):
        raise PrepConflictError("准备卡已使用或已收口，不能修改")
    changes = payload.model_dump(mode="json", exclude={"version"}, exclude_unset=True)
    if "goal" in changes and not (changes["goal"] or "").strip():
        raise ValueError("本次目标不能为空")
    if changes.get("template_code"):
        template = template_service.get_template(db, changes["template_code"])
        changes["template_code"] = template.code
        changes["template_version"] = template.version
    for key, value in changes.items():
        setattr(prep, key, value)
    if changes:
        cloned_from = (prep.strategy or {}).get("cloned_from_prep_id")
        prep.strategy_status = "none"
        prep.strategy = {"cloned_from_prep_id": cloned_from} if cloned_from else None
        prep.strategy_error = None
        prep.version += 1
    db.flush()
    return prep


def list_preps(db, user, customer_id):
    customer = db.get(DomesticCustomer, customer_id)
    if customer is None:
        raise LookupError("客户不存在")
    query = db.query(DomesticFollowupPrep).filter(DomesticFollowupPrep.customer_id == customer_id)
    if prep_access.current_owner(db, customer) != visibility.uid(user):
        if not visibility.in_customer_scope(db, user, customer_id):
            raise PermissionError("无权查看该客户的准备卡")
        query = query.filter(DomesticFollowupPrep.author_user_id == visibility.uid(user))
    return query.order_by(DomesticFollowupPrep.created_at.desc(), DomesticFollowupPrep.id.desc()).all()


def detail(db, user, prep_id):
    prep = db.get(DomesticFollowupPrep, prep_id)
    if prep is None:
        raise LookupError("准备卡不存在")
    prep_access.ensure_read(db, user, prep)
    return prep


def _replay_clone(db, user, existing, source, payload):
    prep_access.ensure_author(db, user, existing)
    prep_access.ensure_context_write(db, user, source.customer_id)
    metadata = existing.strategy or {}
    if (existing.customer_id != source.customer_id or metadata.get("cloned_from_prep_id") != source.id
            or (payload.template_code and existing.template_code != payload.template_code.upper())):
        raise ValueError("请求编号已用于其他准备卡，请更换请求编号")
    return existing


def clone(db, user, prep_id, payload):
    source = detail(db, user, prep_id)
    existing = db.query(DomesticFollowupPrep).filter(DomesticFollowupPrep.request_id == payload.request_id).first()
    if existing:
        return _replay_clone(db, user, existing, source, payload)
    prep_access.ensure_context_write(db, user, source.customer_id)
    template = (template_service.get_template(db, payload.template_code) if payload.template_code
                else template_service.get_template(db, source.template_code))
    facts = [{**fact, "carried_from_prep_id": source.id} for fact in (source.known_facts or [])[:8]]
    prep = DomesticFollowupPrep(
        customer_id=source.customer_id, author_user_id=visibility.uid(user), template_code=template.code,
        template_version=template.version, goal=source.goal, contact_reason=source.contact_reason,
        reason_source=source.reason_source, reason_date=source.reason_date, known_facts=facts,
        to_confirm=list(source.to_confirm or [])[:5], answers=dict(source.answers or {}), status="draft",
        strategy_status="none", strategy={"cloned_from_prep_id": source.id}, request_id=payload.request_id, version=1,
    )
    return _insert_idempotent(db, prep, lambda existing: _replay_clone(db, user, existing, source, payload))


def abandon(db, user, prep_id):
    prep = locked(db, prep_id)
    prep_access.ensure_author(db, user, prep)
    if prep.status == "used":
        raise PrepConflictError("已使用的准备卡不能作废")
    prep.status = "abandoned"
    prep.version += 1
    db.flush()
    return prep


def feedback(db, user, prep_id, value):
    prep = locked(db, prep_id)
    prep_access.ensure_author(db, user, prep)
    strategy = dict(prep.strategy or {})
    entries = list(strategy.get("feedbacks") or [])
    entries.append({"feedback": value, "created_at": beijing_now().isoformat()})
    strategy["feedbacks"] = entries[-20:]
    prep.strategy = strategy
    db.flush()
    return prep


def bind_for_followup(db, user, followup, prep_id) -> list[str]:
    if not prep_id:
        followup.prep_id = None
        return []
    prep = db.query(DomesticFollowupPrep).filter(DomesticFollowupPrep.id == prep_id).populate_existing().with_for_update().first()
    if prep is None:
        followup.prep_id = None
        return ["准备卡不存在，已解除关联"]
    warning = None
    if prep.customer_id != followup.customer_id:
        warning = "准备卡与客户不一致，已解除关联"
    elif prep.author_user_id != visibility.uid(user) or prep.status not in ("draft", "ready") or prep.followup_id:
        warning = "准备卡已使用、已收口或不属于当前作者，已解除关联"
    else:
        try:
            prep_access.ensure_author(db, user, prep)
        except PermissionError:
            warning = "当前账号已失去该准备卡权限，已解除关联"
    if warning:
        followup.prep_id = None
        return [warning]
    prep.status = "used"
    prep.followup_id = followup.id
    followup.prep_id = prep.id
    if not followup.template_code:
        followup.template_code = prep.template_code
        followup.template_version = prep.template_version
    if not followup.template_answers:
        followup.template_answers = {"fields": dict(prep.answers or {}), "questions": [
            {"q": row.get("q", ""), "answer": "", "state": "not_asked"}
            for row in (prep.strategy or {}).get("key_questions", [])
        ]}
    db.flush()
    return []


def expire_stale(db, today=None) -> int:
    cutoff = beijing_now() - timedelta(days=14)
    result = db.execute(update(DomesticFollowupPrep).where(
        DomesticFollowupPrep.status.in_(("draft", "ready")), DomesticFollowupPrep.updated_at < cutoff,
    ).values(status="expired"))
    return result.rowcount or 0


def expire_for_owner_change(db, customer_ids) -> int:
    ids = list(customer_ids)
    if not ids:
        return 0
    result = db.execute(update(DomesticFollowupPrep).where(
        DomesticFollowupPrep.customer_id.in_(ids), DomesticFollowupPrep.status.in_(("draft", "ready")),
    ).values(status="expired").execution_options(synchronize_session="evaluate"))
    return result.rowcount or 0
