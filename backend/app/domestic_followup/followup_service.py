"""跟进主流程：直接保存 / 草稿 / 确认 / 作废 / 已回访无问题 / 列表 / 时间线（规格 3.1 / 4.1 / 4.4 / 4.5）。

三条落正式记录的路径共用 _apply_and_confirm，保证校验、任务、别名、紧急推送口径一致。
"""
import logging
from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now, beijing_today
from app.domestic.models import DomesticCustomer
from app.domestic_followup import attachment_service, config_service, dict_service, task_service, visibility
from app.domestic_followup.constants import (
    DICT_CATEGORY, DICT_CHANNEL, DICT_OBSTACLE, DICT_RESULT, DICT_STATE_CHANGE, NEGATIVE_RESULT_CODES,
    RECEIPT_OK_TEXT, TRACKED_KINDS, URGENT,
)
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupItem, DomesticFollowupTask
from app.domestic_followup.schemas import ConfirmIn, DirectSaveIn, DraftCreateIn, FollowupFields

logger = logging.getLogger("commission")

Followup = DomesticFollowup
OUTCOME_FIELDS = ("result_code", "obstacles", "evidence_kind", "shared_summary", "effective_progress")


class ConflictError(Exception):
    """草稿状态或版本不符，路由映射为 409。"""


def _enqueue_urgent(db: Session, item, customer, followup) -> None:
    from app.domestic_followup.digest_service import enqueue_urgent  # 延迟导入：digest 反向依赖本模块序列化

    enqueue_urgent(db, item, customer, followup)


def _by_request(db: Session, request_id: str, user_id: int) -> Followup | None:
    row = db.query(Followup).filter(Followup.request_id == request_id).first()
    if row and row.author_user_id != user_id:
        raise ValueError("请求编号冲突，请刷新后重试")
    return row


def _validate(fields: FollowupFields, values: dict, followup_date) -> None:
    channels, states, categories = values[DICT_CHANNEL], values[DICT_STATE_CHANGE], values[DICT_CATEGORY]
    if fields.channel and fields.channel not in channels:
        raise ValueError(f"沟通方式「{fields.channel}」不在字典中")
    if fields.next_method and fields.next_method not in channels:
        raise ValueError(f"下次跟进方式「{fields.next_method}」不在字典中")
    unknown = [s for s in fields.state_changes if s not in states]
    if unknown:
        raise ValueError(f"状态变化「{'、'.join(unknown)}」不在字典中")
    for item in fields.items:
        if item.kind in TRACKED_KINDS and item.category and item.category not in categories:
            raise ValueError(f"分类「{item.category}」不在字典中")
    if followup_date > beijing_today():
        raise ValueError("跟进日期不能晚于今天")
    if fields.next_date and fields.next_date < followup_date:
        raise ValueError("下次跟进日期不能早于跟进日期")


def validate_outcome(values, result, obstacles, effective, *, previous=None, required=False):
    if required and not (result or "").strip():
        raise ValueError("请选择本次结果")
    prior_result = previous.result_code if previous is not None else None
    prior_obstacles = (previous.obstacles or []) if previous is not None else []
    if result and result != prior_result and result not in values[DICT_RESULT]:
        raise ValueError("本次沟通结果不在当前字典中")
    if set(obstacles) - set(prior_obstacles) - set(values[DICT_OBSTACLE]):
        raise ValueError("推进障碍不在当前字典中")
    if effective and (not result or result in NEGATIVE_RESULT_CODES):
        raise ValueError("标记有效推进前，请选择有实际进展的沟通结果")


def _active_user(db: Session, user_id: int) -> bool:
    return db.query(ArkUser.id).filter(ArkUser.id == user_id, ArkUser.is_active.is_(True),
                                       ArkUser.deleted_at.is_(None)).first() is not None


def _write_items(db: Session, followup: Followup, customer: DomesticCustomer, items, user_id: int) -> None:
    seq = {"content": 0, "issue": 0, "suggestion": 0}
    for item_in in items:
        seq[item_in.kind] += 1
        tracked = item_in.kind in TRACKED_KINDS
        if tracked and item_in.handler_user_id and not _active_user(db, item_in.handler_user_id):
            raise ValueError("处理人不存在或已停用")
        item = DomesticFollowupItem(
            followup_id=followup.id, customer_id=customer.id, seq=seq[item_in.kind], kind=item_in.kind,
            text=item_in.text.strip(), origin=item_in.origin,
            category=item_in.category if tracked else None,
            severity=(item_in.severity or "一般") if tracked else None,
            status=("closed_no_action" if item_in.record_only else "open") if tracked else None,
            resolution="仅记录" if tracked and item_in.record_only else None,
            handler_user_id=(item_in.handler_user_id or user_id) if tracked else None,
        )
        db.add(item)
        db.flush()
        if tracked and not item_in.record_only:
            task_service.create_item_task(db, item, followup, customer.shop_name)
        if tracked and item.severity == URGENT and not item_in.record_only:  # 「仅记录」不打扰人
            _enqueue_urgent(db, item, customer, followup)


def _apply_and_confirm(db: Session, current_user: dict, followup: Followup, fields: FollowupFields) -> Followup:
    if not fields.customer_id:
        raise ValueError("请选择客户")
    from app.domestic_followup import record_access

    user_id = visibility.uid(current_user)
    if fields.followup_date:
        followup.followup_date = fields.followup_date
    if not fields.channel and followup.channel:  # 建草稿时带的沟通方式也要过字典校验
        fields = fields.model_copy(update={"channel": followup.channel})
    values = dict_service.load_values(db)
    _validate(fields, values, followup.followup_date)
    validate_outcome(values, fields.result_code, fields.obstacles, fields.effective_progress, required=True)
    customer, responsibility, task_only = record_access.confirm_access(db, current_user, followup, fields)

    followup.customer_id = customer.id
    followup.channel = fields.channel or followup.channel
    followup.summary = fields.summary
    followup.chat_title = fields.chat_title
    followup.next_date = fields.next_date
    followup.next_plan = fields.next_plan
    followup.next_method = fields.next_method
    followup.state_changes = list(dict.fromkeys(fields.state_changes)) or None
    for name in OUTCOME_FIELDS:
        setattr(followup, name, getattr(fields, name))
    followup.responsibility_version = responsibility.version if responsibility else None

    _write_items(db, followup, customer, fields.items, user_id)
    for resolved in fields.resolved_items:
        item = db.get(DomesticFollowupItem, resolved.item_id)
        if item is None or item.customer_id != customer.id:
            raise ValueError("勾选处理的异常/意见不属于该客户")
        task_service.resolve_item(db, current_user, item.id, status=resolved.status,
                                  resolution=resolved.resolution, followup_id=followup.id)

    close_ids = set(fields.close_task_ids)
    if followup.source_task_id:
        close_ids.add(followup.source_task_id)
    task_service.close_tasks_for_followup(db, current_user, customer.id, close_ids, followup.id)
    if not task_only and not fields.historical_only:
        plan_owner = record_access.plan_assignee(db, responsibility, fields)
        task_service.create_plan_task(db, followup, customer.shop_name, assignee_id=plan_owner, purpose=fields.plan_purpose)
        record_access.update_responsibility(db, responsibility, followup, fields)
        visibility.learn_alias(db, customer.id, followup.chat_title, user_id)

    followup.status = "confirmed"
    followup.confirmed_at = beijing_now()
    followup.version += 1
    db.flush()
    return followup


def _new_followup(db: Session, user_id: int, payload, *, ai_status: str) -> tuple[Followup, bool]:
    """返回 (记录, 是否新建)。撞唯一键时重查：双击并发提交返回已落库的那条。"""
    followup = Followup(
        author_user_id=user_id, request_id=payload.request_id,
        followup_date=payload.followup_date or beijing_today(),
        raw_text=(payload.raw_text or "").strip() or None, channel=payload.channel,
        source=payload.source, status="draft", ai_status=ai_status,
        source_task_id=payload.source_task_id, version=1,
    )
    db.add(followup)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        existing = _by_request(db, payload.request_id, user_id)  # 同一 request_id 并发提交，另一请求已落库
        if existing:
            return existing, False
        # 不是 request_id 撞键（如外键失效），别误报成「重复」
        logger.warning("followup insert failed request_id=%s: %s", payload.request_id, type(exc.orig).__name__)
        print(f"[domestic_followup] followup insert failed request_id={payload.request_id}", flush=True)
        raise ValueError("保存失败，请重试") from exc
    return followup, True


def direct_save(db: Session, current_user: dict, payload: DirectSaveIn) -> tuple[Followup, list[int]]:
    """返回 (记录, 待 OCR 附件 ID)；路由把后者交给后台线程。"""
    user_id = visibility.uid(current_user)
    existing = _by_request(db, payload.request_id, user_id)
    if existing:
        return existing, []
    if not ((payload.raw_text or "").strip() or payload.attachment_ids or payload.items):
        raise ValueError("请填写跟进内容或上传截图")
    try:
        followup, created = _new_followup(db, user_id, payload, ai_status="none")
        if not created:
            return followup, []
        attachments = attachment_service.bind(db, user_id, followup.id, payload.attachment_ids)
        _apply_and_confirm(db, current_user, followup, payload)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return followup, [a.id for a in attachments if a.ocr_status == "pending"]


def create_draft(db: Session, current_user: dict, payload: DraftCreateIn) -> tuple[Followup, bool]:
    """返回 (草稿, 是否新建)；路由只对新建的草稿排 AI 任务，重放请求不会重复调模型。"""
    user_id = visibility.uid(current_user)
    existing = _by_request(db, payload.request_id, user_id)
    if existing:
        return existing, False
    if not ((payload.raw_text or "").strip() or payload.attachment_ids):
        raise ValueError("请填写跟进内容或上传截图")
    try:
        if payload.customer_id:
            from app.domestic_followup import record_access
            record_access.draft_access(db, current_user, payload.customer_id, payload.source_task_id)
        validate_outcome(dict_service.load_values(db), payload.result_code, payload.obstacles, payload.effective_progress)
        followup, created = _new_followup(db, user_id, payload, ai_status="running")
        if not created:
            return followup, False
        followup.customer_id = payload.customer_id
        for name in OUTCOME_FIELDS:
            setattr(followup, name, getattr(payload, name))
        attachment_service.bind(db, user_id, followup.id, payload.attachment_ids)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return followup, True


def _own_draft(db: Session, current_user: dict, followup_id: int, *, lock: bool = False) -> Followup:
    query = db.query(Followup).filter(Followup.id == followup_id)
    if lock:
        query = query.with_for_update()
    followup = query.first()
    if followup is None or followup.author_user_id != visibility.uid(current_user):
        raise LookupError("草稿不存在")
    return followup


def serialize_item(item: DomesticFollowupItem) -> dict:
    return {
        "id": item.id, "followup_id": item.followup_id, "customer_id": item.customer_id, "seq": item.seq,
        "kind": item.kind, "text": item.text, "category": item.category, "severity": item.severity,
        "origin": item.origin, "status": item.status, "handler_user_id": item.handler_user_id,
        "resolution": item.resolution,
        "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def serialize(db: Session, followup: Followup, *, with_items: bool = True) -> dict:
    customer = db.get(DomesticCustomer, followup.customer_id) if followup.customer_id else None
    author = db.get(ArkUser, followup.author_user_id)
    data = {
        "id": followup.id, "customer_id": followup.customer_id,
        "shop_name": customer.shop_name if customer else None,
        "author_user_id": followup.author_user_id, "author_name": author.real_name if author else None,
        "followup_date": followup.followup_date.isoformat(), "channel": followup.channel,
        "raw_text": followup.raw_text, "summary": followup.summary, "state_changes": followup.state_changes or [],
        "result_code": followup.result_code, "obstacles": followup.obstacles or [],
        "evidence_kind": followup.evidence_kind, "shared_summary": followup.shared_summary,
        "effective_progress": followup.effective_progress,
        "responsibility_version": followup.responsibility_version,
        "next_date": followup.next_date.isoformat() if followup.next_date else None,
        "next_plan": followup.next_plan, "next_method": followup.next_method, "chat_title": followup.chat_title,
        "source": followup.source, "status": followup.status, "ai_status": followup.ai_status,
        "ai_result": followup.ai_result, "ai_error": followup.ai_error, "version": followup.version,
        "source_task_id": followup.source_task_id,
        "created_at": followup.created_at.isoformat() if followup.created_at else None,
        "attachments": attachment_service.list_for(db, [followup.id]).get(followup.id, []),
    }
    if with_items:
        items = (db.query(DomesticFollowupItem).filter(DomesticFollowupItem.followup_id == followup.id,
                 or_(DomesticFollowupItem.status.is_(None), DomesticFollowupItem.status != "withdrawn"))
                 .order_by(DomesticFollowupItem.kind, DomesticFollowupItem.seq).all())
        data["items"] = [serialize_item(i) for i in items]
    return data


AI_STALE_MINUTES = 10


def _recover_stale_ai(db: Session, rows: list[Followup]) -> None:
    """后端重启会让后台 AI 线程丢失：running 超过 10 分钟的视为失败，前端不再无限轮询。"""
    cutoff = beijing_now() - timedelta(minutes=AI_STALE_MINUTES)
    stale = [r for r in rows if r.ai_status == "running" and r.updated_at and r.updated_at < cutoff]
    for row in stale:
        row.ai_status = "failed"
        row.ai_error = "AI 整理超时，请参考截图文字手动填写"
    if stale:
        db.commit()


def get_draft(db: Session, current_user: dict, followup_id: int) -> dict:
    followup = _own_draft(db, current_user, followup_id)
    _recover_stale_ai(db, [followup])
    return serialize(db, followup)


def list_drafts(db: Session, current_user: dict, *, potential_only: bool = False) -> list[dict]:
    query = db.query(Followup).filter(Followup.author_user_id == visibility.uid(current_user), Followup.status == "draft")
    if potential_only:
        query = query.filter(Followup.customer_id.in_(visibility.potential_customer_ids()))
    rows = query.order_by(Followup.created_at.desc()).limit(20).all()
    _recover_stale_ai(db, rows)
    return [serialize(db, r, with_items=False) for r in rows]


def confirm_draft(db: Session, current_user: dict, followup_id: int, payload: ConfirmIn) -> Followup:
    try:
        followup = _own_draft(db, current_user, followup_id, lock=True)
        if followup.status != "draft":
            raise ConflictError("该草稿已确认或已作废")
        if followup.version != payload.version:
            raise ConflictError("草稿已在别处更新，请刷新后再确认")
        _apply_and_confirm(db, current_user, followup, payload)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return followup


def discard_draft(db: Session, current_user: dict, followup_id: int) -> None:
    followup = _own_draft(db, current_user, followup_id, lock=True)
    if followup.status != "draft":
        db.rollback()
        raise ConflictError("该草稿已确认或已作废")
    followup.status = "discarded"
    followup.version += 1
    db.commit()


def quick_receipt_ok(db: Session, current_user: dict, task_id: int, request_id: str) -> Followup:
    """「已回访无问题」：自动生成一条简短记录并关闭回访任务（规格 4.4）。"""
    user_id = visibility.uid(current_user)
    existing = _by_request(db, request_id, user_id)
    if existing:
        return existing
    try:
        from app.domestic_followup.collaboration_access import lock_customer
        customer_id = db.scalar(select(DomesticFollowupTask.customer_id).where(DomesticFollowupTask.id == task_id))
        if customer_id is None:
            raise LookupError("回访待办不存在")
        lock_customer(db, customer_id)
        task = (db.query(DomesticFollowupTask).filter(DomesticFollowupTask.id == task_id)
                .populate_existing().with_for_update().first())
        if task is None or task.task_type != "receipt":
            raise LookupError("回访待办不存在")
        if task.status != "todo":
            # 双击：第二次在行锁上等到第一次提交，任务已关。用加锁读看最新版本，是同一请求就把那条还回去
            done = (db.query(Followup).filter(Followup.request_id == request_id)
                    .populate_existing().with_for_update().first())
            if done is not None and done.author_user_id == user_id:
                db.commit()
                return done
            raise ConflictError("该回访待办已结束")
        task_service.ensure_task_actor(db, current_user, task)
        if "有效沟通" not in dict_service.load_values(db)[DICT_RESULT]:
            raise ValueError("有效沟通已停用，请使用「记跟进」选择当前可用的本次结果")
        followup = Followup(author_user_id=user_id, request_id=request_id, followup_date=beijing_today(),
                            raw_text=RECEIPT_OK_TEXT, source="web", status="draft", ai_status="none",
                            source_task_id=task.id, version=1)
        db.add(followup)
        db.flush()
        _apply_and_confirm(db, current_user, followup,
                           FollowupFields(customer_id=task.customer_id, summary=RECEIPT_OK_TEXT,
                                          result_code="有效沟通"))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = _by_request(db, request_id, user_id)  # 同一 request_id 并发提交，另一请求已落库
        if existing:
            return existing
        logger.warning("receipt-ok insert failed request_id=%s: %s", request_id, type(exc.orig).__name__)
        print(f"[domestic_followup] receipt-ok insert failed request_id={request_id}", flush=True)
        raise ValueError("保存失败，请重试") from exc
    except Exception:
        db.rollback()
        raise
    return followup


def list_followups(db: Session, current_user: dict, *, customer_id: int | None = None, mine: bool = False,
                   page: int = 1, page_size: int = 20, author_user_id: int | None = None,
                   keyword: str = "", date_from: date | None = None, date_to: date | None = None,
                   potential_only: bool = False) -> dict:
    if date_from and date_to and date_from > date_to:
        raise ValueError("开始日期不能晚于结束日期")
    query = db.query(Followup).filter(Followup.status == "confirmed")
    if potential_only:
        query = query.filter(Followup.customer_id.in_(visibility.potential_customer_ids()))
    condition = visibility.followup_filter(current_user)
    if condition is not None:
        query = query.filter(condition)
    if customer_id:
        query = query.filter(Followup.customer_id == customer_id)
    if mine:
        query = query.filter(Followup.author_user_id == visibility.uid(current_user))
    if author_user_id:
        query = query.filter(Followup.author_user_id == author_user_id)
    if date_from:
        query = query.filter(Followup.followup_date >= date_from)
    if date_to:
        query = query.filter(Followup.followup_date <= date_to)
    keyword = keyword.strip()
    if keyword:
        customers = select(DomesticCustomer.id).where(or_(
            DomesticCustomer.shop_name.contains(keyword, autoescape=True),
            DomesticCustomer.custom_code.contains(keyword, autoescape=True),
            DomesticCustomer.contact.contains(keyword, autoescape=True),
        ))
        items = select(DomesticFollowupItem.followup_id).where(
            DomesticFollowupItem.text.contains(keyword, autoescape=True),
            or_(DomesticFollowupItem.status.is_(None), DomesticFollowupItem.status != "withdrawn"))
        query = query.filter(or_(Followup.customer_id.in_(customers), Followup.id.in_(items),
                                 Followup.summary.contains(keyword, autoescape=True),
                                 Followup.raw_text.contains(keyword, autoescape=True)))
    total = query.count()
    rows = (query.order_by(Followup.followup_date.desc(), Followup.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    return {"items": [serialize(db, r) for r in rows], "total": total, "page": page, "page_size": page_size}


def list_authors(db: Session, current_user: dict, *, potential_only: bool = False) -> list[dict]:
    """Only authors of visible confirmed records, including historical inactive users."""
    records = select(Followup.author_user_id).where(Followup.status == "confirmed")
    if potential_only:
        records = records.where(Followup.customer_id.in_(visibility.potential_customer_ids()))
    condition = visibility.followup_filter(current_user)
    if condition is not None:
        records = records.where(condition)
    rows = (db.query(ArkUser.id, ArkUser.real_name).filter(ArkUser.id.in_(records))
            .order_by(ArkUser.real_name, ArkUser.id).all())
    return [{"id": row.id, "real_name": row.real_name} for row in rows]


def timeline(db: Session, current_user: dict, customer_id: int, *, offset: int = 0,
             event_type: str = "all") -> dict:
    from app.domestic_followup.timeline_service import customer_timeline

    return customer_timeline(db, current_user, customer_id, today=beijing_today(), offset=offset, event_type=event_type)


def attachment_file(db: Session, current_user: dict, attachment_id: int):
    """截图原图：上传人本人，或能看到所属已确认记录的人。"""
    from app.domestic.file_service import FileValidationError, resolve_path
    from app.domestic_followup.models import DomesticFollowupAttachment

    att = db.get(DomesticFollowupAttachment, attachment_id)
    if att is None:
        raise LookupError("截图不存在")
    if att.uploader_user_id != visibility.uid(current_user):
        query = db.query(Followup.id).filter(Followup.id == att.followup_id, Followup.status == "confirmed")
        condition = visibility.followup_filter(current_user)
        if condition is not None:
            query = query.filter(condition)
        if att.followup_id is None or query.first() is None:
            raise PermissionError("无权查看该截图")
    try:
        path = resolve_path(att.file_path)
    except FileValidationError as exc:
        raise ValueError(str(exc)) from exc
    if not path.is_file():
        raise LookupError("截图文件不存在")
    return path, att.mime_type or "image/png"
