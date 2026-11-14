"""Confirmed-record edits, immutable revisions and transactional task reconciliation."""
import hashlib
import json

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.auth.models import ArkUser
from app.core.time import beijing_now, beijing_today
from app.domestic.models import DomesticCustomer
from app.domestic_followup import attachment_service, dict_service, edit_item_service, edit_task_service, followup_service, visibility
from app.domestic_followup.constants import URGENT_MAX_ATTEMPTS
from app.domestic_followup.models import (
    DomesticFollowup as Followup, DomesticFollowupAttachment as Attachment,
    DomesticFollowupDigest as Digest, DomesticFollowupItem as Item,
    DomesticFollowupRevision as Revision, DomesticFollowupTask as Task,
)
from app.domestic_followup.schemas import FollowupFields

EDIT_FIELDS = ("raw_text", "followup_date", "channel", "summary", "state_changes", "next_date", "next_plan", "next_method")


def _validate_edit(db, row, payload, items):
    previous = {item.id: item for item in items if item.status != "withdrawn"}
    fields = FollowupFields(
        followup_date=payload.followup_date, next_date=payload.next_date,
        channel=payload.channel if payload.channel != row.channel else None,
        next_method=payload.next_method if payload.next_method != row.next_method else None,
        state_changes=[v for v in payload.state_changes if v not in (row.state_changes or [])],
        items=[entry.model_copy(update={"category": None})
               if entry.id in previous and entry.category == previous[entry.id].category else entry
               for entry in payload.items],
    )
    values = dict_service.load_values(db)
    followup_service._validate(fields, values, payload.followup_date)
    updates = payload.model_dump(include=payload.model_fields_set)
    followup_service.validate_outcome(
        values, updates.get("result_code", row.result_code), updates.get("obstacles", row.obstacles or []),
        updates.get("effective_progress", row.effective_progress), previous=row, required=True,
    )


def can_edit(user, row):
    return "super_admin" in (user.get("roles") or []) or (
        row.author_user_id == visibility.uid(user) and "domestic_followup:write" in (user.get("permissions") or []))


def _record(db, user, record_id, lock=False):
    query = db.query(Followup).filter(Followup.id == record_id, Followup.status == "confirmed")
    condition = visibility.followup_filter(user)
    if condition is not None:
        query = query.filter(condition)
    if lock:
        query = query.populate_existing().with_for_update()
    row = query.first()
    if row is None:
        raise LookupError("跟进记录不存在或无权查看")
    return row


def detail(db, user, record_id):
    from app.domestic_followup import collaboration_access

    row = _record(db, user, record_id)
    customer = db.get(DomesticCustomer, row.customer_id)
    managed = customer is not None and collaboration_access.customer_is_managed(db, customer)
    return {**followup_service.serialize(db, row), "can_edit": bool(customer and customer.status == 1 and can_edit(user, row)),
            "historical_edit": _historical_edit(db, user, row, customer, _tasks(db, row)),
            "planning_editable": not managed}


def _historical_edit(db, user, row, customer, tasks, *, lock=False):
    from app.domestic_followup import collaboration_access

    if customer is None or not collaboration_access.customer_is_managed(db, customer, lock=lock):
        return False
    return not visibility.can_write_customer(db, user, customer, lock=lock) or any(
        task.task_type == "plan" and task.assignee_user_id != row.author_user_id
        for task in tasks if task.source_followup_id == row.id
    )


def _historical_items(row, payload, items):
    if "shared_summary" in payload.model_fields_set and payload.shared_summary != row.shared_summary:
        raise PermissionError("共享摘要由当前负责人处理")
    existing = {i.id: i for i in items if i.kind != "content" and i.status != "withdrawn"}
    incoming = [i for i in payload.items if i.kind != "content"]
    if len(incoming) != len(existing) or {i.id for i in incoming} != set(existing):
        raise ValueError("历史记录更正须保留原有异常或意见，处理请使用异常意见入口")
    for entry in incoming:
        prior = existing[entry.id]
        if ((entry.kind, entry.text.strip(), entry.category, entry.severity or "一般", entry.record_only)
                != (prior.kind, prior.text, prior.category, prior.severity, edit_item_service.only_record(prior))
                or entry.handler_user_id not in (None, prior.handler_user_id)):
            raise ValueError("历史记录更正须保留原有异常或意见，处理请使用异常意见入口")
    return [i for i in payload.items if i.kind == "content"], [i for i in items if i.kind == "content"]


def _tasks(db, row, lock=False):
    query = db.query(Task).filter(or_(Task.source_followup_id == row.id, Task.closed_by_followup_id == row.id)).order_by(Task.id)
    if lock:
        query = query.populate_existing().with_for_update()
    return query.all()


def _snapshot(db, row):
    data = followup_service.serialize(db, row)
    # Keep the full business record and affected task states, without model prompts/errors.
    for key in ("ai_result", "ai_error", "ai_status"):
        data.pop(key, None)
    data["tasks"] = [{"id": t.id, "type": t.task_type, "status": t.status, "title": t.title,
                       "due_date": t.due_date.isoformat(), "assignee_user_id": t.assignee_user_id,
                       "assignee_name": (db.get(ArkUser, t.assignee_user_id).real_name if db.get(ArkUser, t.assignee_user_id) else None),
                       "source_item_id": t.source_item_id, "payload": t.payload,
                       "closed_reason": t.closed_reason, "closed_by_user_id": t.closed_by_user_id,
                       "closed_at": t.closed_at.isoformat() if t.closed_at else None}
                      for t in _tasks(db, row)]
    return data


def _attachments(db, row, ids, actor_id):
    ids = list(dict.fromkeys(ids))
    rows = attachment_service.lock_rows(db, row.id, ids)
    by_id = {a.id: a for a in rows}
    pending = []
    for key in ids:
        att = by_id.get(key)
        if att is None:
            raise LookupError("截图不存在，请重新上传")
        if att.followup_id != row.id and (att.followup_id is not None or att.uploader_user_id != actor_id):
            raise PermissionError("只能保留本记录的截图或添加本人上传且未使用的截图")
    for att in rows:
        if att.id not in ids:
            if att.archived_at is None:
                att.archived_at = beijing_now()
        else:
            if att.followup_id is None and att.ocr_status == "pending":
                pending.append(att.id)
            att.followup_id, att.archived_at, att.seq = row.id, None, ids.index(att.id) + 1
    return pending


def _urgent(db, row, customer, items, before):
    """Update only unsent reminders; delivered messages stay as historical facts."""
    from app.domestic_followup.digest_service import available_claim, enqueue_urgent, workbench_url
    previous = {i["id"]: i for i in before["items"]}
    for item in items:
        if item.kind not in ("issue", "suggestion"):
            continue
        urgent = item.severity == "紧急" and item.status in ("open", "handling")
        pending = (db.query(Digest).filter(Digest.kind == "urgent", Digest.ref_key == f"item:{item.id}",
                                         Digest.pushed_at.is_(None), available_claim()).with_for_update().all())
        for digest in pending:
            if not urgent:
                digest.attempts = URGENT_MAX_ATTEMPTS
                digest.last_error = "跟进修改后取消紧急提醒"
            else:
                digest.markdown = (f"### 紧急异常：{customer.shop_name}\n- **{item.category or '其他'}**：{item.text}"
                                   f"\n- 跟进日期：{row.followup_date.isoformat()}\n[查看客户跟进]({workbench_url(customer.id)})")
                if digest.last_error == "跟进修改后取消紧急提醒" and digest.digest_date == beijing_today():
                    digest.attempts, digest.last_error = 0, None
        old = previous.get(item.id)
        if urgent and (old is None or old["severity"] != "紧急" or old["status"] not in ("open", "handling")):
            enqueue_urgent(db, item, customer, row)


def _replay(db, user, record_id, payload, fingerprint):
    saved = (db.query(Revision).filter(Revision.request_id == payload.request_id)
             .populate_existing().with_for_update().first())
    if saved is None:
        return False
    if saved.followup_id != record_id or saved.editor_user_id != visibility.uid(user) or saved.request_hash != fingerprint:
        raise followup_service.ConflictError("修改请求编号已用于其他内容，请刷新后重试")
    return True


def update(db, user, record_id, payload):
    from app.domestic_followup import collaboration_access

    fingerprint = hashlib.sha256(json.dumps(payload.model_dump(mode="json"), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    try:
        customer_id = db.query(Followup.customer_id).filter(Followup.id == record_id).scalar()
        if customer_id is not None:
            collaboration_access.lock_customer(db, customer_id)
        row = _record(db, user, record_id, lock=True)
        if not can_edit(user, row):
            raise PermissionError("只能修改本人录入的跟进记录，超级管理员可修改全部记录")
        if _replay(db, user, record_id, payload, fingerprint):
            return row, []
        if payload.version != row.version:
            raise followup_service.ConflictError("记录已被修改，请重新载入最新版本；当前填写内容已保留")
        if not ((payload.raw_text or "").strip() or payload.items or payload.attachment_ids):
            raise ValueError("请保留跟进内容或截图")
        customer = db.get(DomesticCustomer, row.customer_id)
        if customer is None or customer.status != 1:
            raise PermissionError("客户已停用，历史记录仅供查看")
        managed = collaboration_access.customer_is_managed(db, customer, lock=True)
        if managed and not collaboration_access.has_live_write(db, user, lock=True):
            raise PermissionError("当前账号没有跟进编辑权限")
        if managed and any(getattr(payload, name) != getattr(row, name) for name in ("next_plan", "next_method")):
            raise ValueError("请通过新跟进或待办更新当前跟进计划和沟通方式")
        items = (db.query(Item).filter(Item.followup_id == row.id).order_by(Item.id)
                 .populate_existing().with_for_update().all())
        _validate_edit(db, row, payload, items)
        tasks = _tasks(db, row, lock=True)
        historical = _historical_edit(db, user, row, customer, tasks, lock=True)
        incoming, existing = _historical_items(row, payload, items) if historical else (payload.items, items)
        before = _snapshot(db, row)
        old_date = row.followup_date
        for name in EDIT_FIELDS:
            value = getattr(payload, name)
            if name == "raw_text":
                value = (value or "").strip() or None
            setattr(row, name, value)
        for name in followup_service.OUTCOME_FIELDS:
            if name in payload.model_fields_set:
                setattr(row, name, getattr(payload, name))
        pending = _attachments(db, row, payload.attachment_ids, visibility.uid(user))
        edit_item_service.reconcile(db, row, customer, incoming, existing, tasks, visibility.uid(user), old_date)
        if not managed:
            edit_task_service.sync_plan(db, row, customer, before, tasks, visibility.uid(user))
        db.flush()
        after = _snapshot(db, row)
        # Ignore the ORM's automatic timestamp for no-op detection.
        if {k: v for k, v in before.items() if k != "updated_at"} == {k: v for k, v in after.items() if k != "updated_at"}:
            raise ValueError("未修改任何内容，无需保存")
        if not historical:
            _urgent(db, row, customer, db.query(Item).filter(Item.followup_id == row.id).all(), before)
        row.version += 1
        db.flush()
        after = _snapshot(db, row)
        db.add(Revision(followup_id=row.id, editor_user_id=visibility.uid(user), version=row.version,
                        request_id=payload.request_id, request_hash=fingerprint, reason=payload.reason,
                        before_snapshot=before, after_snapshot=after))
        db.commit()
        return row, pending
    except IntegrityError:
        db.rollback()
        if _replay(db, user, record_id, payload, fingerprint):
            return _record(db, user, record_id), []
        raise
    except Exception:
        db.rollback()
        raise


def history(db, user, record_id):
    _record(db, user, record_id)
    rows = (db.query(Revision, ArkUser.real_name).join(ArkUser, ArkUser.id == Revision.editor_user_id)
            .filter(Revision.followup_id == record_id).order_by(Revision.version.desc()).all())
    return [{"id": r.id, "version": r.version, "editor_name": name, "editor_user_id": r.editor_user_id,
             "reason": r.reason, "created_at": r.created_at.isoformat(),
             "before": r.before_snapshot, "after": r.after_snapshot} for r, name in rows]
