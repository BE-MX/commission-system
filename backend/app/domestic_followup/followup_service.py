"""跟进主流程：直接保存 / 草稿 / 确认 / 作废 / 已回访无问题 / 列表 / 时间线（规格 3.1 / 4.1 / 4.4 / 4.5）。

三条落正式记录的路径共用 _apply_and_confirm，保证校验、任务、别名、紧急推送口径一致。
"""
import logging
from datetime import datetime, time, timedelta

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now, beijing_today
from app.domestic.models import DomesticCustomer
from app.domestic.shipment_models import DomesticShipment, DomesticShipmentLine
from app.domestic_followup import attachment_service, config_service, dict_service, task_service, visibility
from app.domestic_followup.constants import (
    DICT_CATEGORY, DICT_CHANNEL, DICT_STATE_CHANGE, RECEIPT_OK_TEXT, TRACKED_KINDS, URGENT,
)
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupItem, DomesticFollowupTask
from app.domestic_followup.schemas import ConfirmIn, DirectSaveIn, DraftCreateIn, FollowupFields

logger = logging.getLogger("commission")

Followup = DomesticFollowup
TIMELINE_LIMIT = 100
SHIPMENT_LOOKBACK_DAYS = 90


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
    customer = visibility.ensure_customer_writable(db, current_user, fields.customer_id)
    user_id = visibility.uid(current_user)
    if fields.followup_date:
        followup.followup_date = fields.followup_date
    if not fields.channel and followup.channel:  # 建草稿时带的沟通方式也要过字典校验
        fields = fields.model_copy(update={"channel": followup.channel})
    _validate(fields, dict_service.load_values(db), followup.followup_date)

    followup.customer_id = customer.id
    followup.channel = fields.channel or followup.channel
    followup.summary = fields.summary
    followup.chat_title = fields.chat_title
    followup.next_date = fields.next_date
    followup.next_plan = fields.next_plan
    followup.next_method = fields.next_method
    followup.state_changes = list(dict.fromkeys(fields.state_changes)) or None

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
    task_service.create_plan_task(db, followup, customer.shop_name)
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
            visibility.ensure_customer_writable(db, current_user, payload.customer_id)
        followup, created = _new_followup(db, user_id, payload, ai_status="running")
        if not created:
            return followup, False
        followup.customer_id = payload.customer_id
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
        "next_date": followup.next_date.isoformat() if followup.next_date else None,
        "next_plan": followup.next_plan, "next_method": followup.next_method, "chat_title": followup.chat_title,
        "source": followup.source, "status": followup.status, "ai_status": followup.ai_status,
        "ai_result": followup.ai_result, "ai_error": followup.ai_error, "version": followup.version,
        "source_task_id": followup.source_task_id,
        "created_at": followup.created_at.isoformat() if followup.created_at else None,
        "attachments": attachment_service.list_for(db, [followup.id]).get(followup.id, []),
    }
    if with_items:
        items = (db.query(DomesticFollowupItem).filter(DomesticFollowupItem.followup_id == followup.id)
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


def list_drafts(db: Session, current_user: dict) -> list[dict]:
    rows = (db.query(Followup)
            .filter(Followup.author_user_id == visibility.uid(current_user), Followup.status == "draft")
            .order_by(Followup.created_at.desc()).limit(20).all())
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
        task = db.query(DomesticFollowupTask).filter(DomesticFollowupTask.id == task_id).with_for_update().first()
        if task is None or task.task_type != "receipt":
            raise LookupError("回访待办不存在")
        if task.status != "todo":
            raise ConflictError("该回访待办已结束")
        task_service.ensure_task_actor(db, current_user, task)
        followup = Followup(author_user_id=user_id, request_id=request_id, followup_date=beijing_today(),
                            raw_text=RECEIPT_OK_TEXT, source="web", status="draft", ai_status="none",
                            source_task_id=task.id, version=1)
        db.add(followup)
        db.flush()
        _apply_and_confirm(db, current_user, followup,
                           FollowupFields(customer_id=task.customer_id, summary=RECEIPT_OK_TEXT))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return followup


def list_followups(db: Session, current_user: dict, *, customer_id: int | None = None, mine: bool = False,
                   page: int = 1, page_size: int = 20) -> dict:
    query = db.query(Followup).filter(Followup.status == "confirmed")
    condition = visibility.followup_filter(current_user)
    if condition is not None:
        query = query.filter(condition)
    if customer_id:
        query = query.filter(Followup.customer_id == customer_id)
    if mine:
        query = query.filter(Followup.author_user_id == visibility.uid(current_user))
    total = query.count()
    rows = (query.order_by(Followup.followup_date.desc(), Followup.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    return {"items": [serialize(db, r) for r in rows], "total": total, "page": page, "page_size": page_size}


def timeline(db: Session, current_user: dict, customer_id: int) -> dict:
    """客户时间线：确认跟进 + 近 90 天发货，倒序；头部给跟进频率与未结异常（规格 4.6）。"""
    customer = db.get(DomesticCustomer, customer_id)
    if customer is None:
        raise LookupError("客户不存在")
    today = beijing_today()
    writable = visibility.can_write_customer(db, current_user, customer)
    # 可读 ≠ 可写：公海客户、只有待办的人可以记录，但只能看自己写过 / 被派任务的那几条（规格第六节）
    readable = visibility.in_customer_scope(db, current_user, customer_id)

    query = db.query(Followup).filter(Followup.customer_id == customer_id, Followup.status == "confirmed")
    if not readable:
        query = query.filter(visibility.followup_filter(current_user))
    followups = query.order_by(Followup.followup_date.desc(), Followup.id.desc()).limit(TIMELINE_LIMIT).all()
    if not readable and not writable and not followups:
        raise PermissionError("无权查看该客户的跟进")
    events = [{"type": "followup", "date": f.followup_date.isoformat(), "data": serialize(db, f)} for f in followups]

    # 发货批次也是客户经营数据：不可读的人（公海/只有待办）只看自己相关的跟进，不看发货
    shipments = []
    if readable:
        since = datetime.combine(today - timedelta(days=SHIPMENT_LOOKBACK_DAYS), time.min)
        shipments = (db.query(DomesticShipment)
                     .filter(DomesticShipment.customer_id == customer_id, DomesticShipment.cancelled_at.is_(None),
                             DomesticShipment.ship_time >= since)
                     .order_by(DomesticShipment.ship_time.desc()).limit(TIMELINE_LIMIT).all())
    quantities = dict(db.query(DomesticShipmentLine.shipment_id, func.sum(DomesticShipmentLine.quantity))
                      .filter(DomesticShipmentLine.shipment_id.in_([s.id for s in shipments] or [0]))
                      .group_by(DomesticShipmentLine.shipment_id).all())
    events += [{"type": "shipment", "date": s.ship_time.date().isoformat(),
                "data": {"id": s.id, "shipment_no": s.shipment_no, "quantity": int(quantities.get(s.id) or 0),
                         "received_date": s.received_date.isoformat() if s.received_date else None}}
               for s in shipments]
    # 同日：跟进排在发货之上（倒序读起来是「发货 → 回访」）
    events.sort(key=lambda e: (e["date"], e["type"] == "followup"), reverse=True)

    last = followups[0].followup_date if followups else None
    frequency = config_service.get_config(db)["frequency_days"].get(customer.customer_level or "")
    open_items = []
    if readable:
        open_items = (db.query(DomesticFollowupItem)
                      .filter(DomesticFollowupItem.customer_id == customer_id,
                              DomesticFollowupItem.status.in_(("open", "handling")))
                      .order_by(DomesticFollowupItem.created_at).all())
    return {
        "customer": {
            "id": customer.id, "shop_name": customer.shop_name, "customer_level": customer.customer_level,
            "lifecycle_status": customer.lifecycle_status, "owner_user_id": customer.owner_user_id,
            "last_followup_date": last.isoformat() if last else None,
            "days_since_followup": (today - last).days if last else None,
            "frequency_days": frequency, "writable": writable, "readable": readable,
        },
        "open_items": [serialize_item(i) for i in open_items],
        "events": events[:TIMELINE_LIMIT],
    }


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
