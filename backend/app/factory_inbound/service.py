"""Factory note lifecycle. This phase only changes draft records."""

from datetime import datetime, time, timedelta
import logging

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from app.auth.models import ArkUser
from app.core.config import get_settings
from app.core.response import page_result
from app.core.time import beijing_now
from app.factory_inbound import jobs, presentation, recognition_service, storage
from app.factory_inbound.batch_models import Batch
from app.factory_inbound.matching_rules import color_key, compact, normalize_ref
from app.factory_inbound.matching_service import MatchingContext
from app.factory_inbound.models import Alias, AliasSuggestion, EditLog, Line, LineType, Note, NoteSequence

logger = logging.getLogger(__name__)


def _note(db, note_id, user, *, edit=False, version=None):
    stmt = select(Note).where(Note.id == note_id)
    if edit:
        stmt = stmt.with_for_update()
    note = db.scalars(stmt).first()
    if not note:
        raise HTTPException(404, "工厂到货单不存在")
    if edit:
        if not presentation.can_edit(note, user):
            raise HTTPException(403, "仅创建人或管理员可修改到货单")
        if note.status != "draft":
            raise HTTPException(409, "当前单据不可修改")
        if note.version != version:
            raise HTTPException(409, "单据已更新，请刷新后重试")
    elif not (presentation.has(user, "factory_inbound:read") or presentation.can_edit(note, user)):
        raise HTTPException(404, "工厂到货单不存在")
    return note


def _log(db, note, user, action, before=None, after=None, line_id=None):
    actor = presentation.actor_id(user)
    note.updated_by = actor
    note.version += 1
    db.add(EditLog(note_id=note.id, line_id=line_id, action=action, before_data=before, after_data=after,
                   created_by=actor))


def _next_number(db, today):
    values = dict(business_date=today, last_number=1)
    if db.bind.dialect.name == "sqlite":
        stmt = sqlite_insert(NoteSequence).values(**values).on_conflict_do_update(
            index_elements=[NoteSequence.business_date], set_={"last_number": NoteSequence.last_number + 1},
        )
    else:
        stmt = mysql_insert(NoteSequence).values(**values).on_duplicate_key_update(
            last_number=NoteSequence.last_number + 1,
        )
    db.execute(stmt)
    number = db.scalar(select(NoteSequence.last_number).where(NoteSequence.business_date == today).with_for_update())
    return f"FI{today:%Y%m%d}-{number:03d}"


def create_note(db, scan, original, user):
    settings = get_settings()
    if len(scan) + len(original or b"") > settings.FACTORY_INBOUND_MAX_UPLOAD_BYTES:
        raise HTTPException(413, "照片超出上传大小限制")
    storage.validate_jpeg(scan)
    if original is not None:
        storage.validate_jpeg(original)
    stored = []
    committing = False
    try:
        stored.append(storage.save_image(scan))
        if original is not None:
            stored.append(storage.save_image(original))
        timestamp = beijing_now()
        note = Note(
            inbound_no=_next_number(db, timestamp.date()), factory_code=settings.FACTORY_INBOUND_FACTORY_CODE,
            created_at=timestamp, updated_at=timestamp,
            scan_path=stored[0], original_path=stored[1] if original is not None else None,
            created_by=presentation.actor_id(user), **recognition_service.queue_values(),
        )
        db.add(note)
        db.flush()
        result = presentation.card(note)
        attempt = note.recognition_attempt_id
        committing = True
        db.commit()
    except Exception as error:
        logger.warning("Factory inbound upload failed: %s", type(error).__name__)
        print(f"[FactoryInbound] Upload failed: {type(error).__name__}", flush=True)
        db.rollback()
        # Preserve images when the database commit outcome may be uncertain.
        if not committing:
            for relative in stored:
                storage.remove_image(relative)
        raise
    jobs.submit(result["id"], attempt)
    return result


def list_notes(db, user, *, mine, status, keyword, date_from, date_to, created_by, creator, page, page_size):
    query = select(Note)
    if mine or not (presentation.has(user, "factory_inbound:read") or presentation.is_admin(user)):
        query = query.where(Note.created_by == presentation.actor_id(user))
    if status:
        query = query.where(Note.status == status)
    if keyword:
        query = query.where(or_(Note.inbound_no.contains(keyword, autoescape=True),
                                Note.delivery_no == keyword, Note.recognized_delivery_no == keyword))
    if date_from:
        query = query.where(Note.created_at >= date_from)
    if date_to:
        query = query.where(Note.created_at <= datetime.combine(date_to, time.max))
    if created_by:
        query = query.where(Note.created_by == created_by)
    if creator:
        query = query.where(Note.created_by.in_(select(ArkUser.id).where(ArkUser.real_name.contains(creator, autoescape=True))))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    notes = db.execute(query.add_columns(ArkUser.real_name).outerjoin(
        ArkUser, ArkUser.id == Note.created_by,
    ).order_by(Note.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return page_result([presentation.card(note, name) for note, name in notes], total, page, page_size)


def _detail(db, note, user):
    return presentation.detail(db, note, user, _current_duplicate(db, note))


def _current_duplicate(db, note):
    if note.duplicate_suspected_note_id:
        existing = db.get(Note, note.duplicate_suspected_note_id)
        if existing and existing.status != "voided":
            return existing
    if not note.delivery_no and note.status == "draft":
        return recognition_service.duplicate_note(db, note, note.recognized_delivery_no)
    return None


def get_note(db, note_id, user):
    note = _note(db, note_id, user)
    if note.recognition_status in {"queued", "running"}:
        now = beijing_now()
        origin = note.recognition_started_at or note.recognition_queued_at
        if now - origin > timedelta(minutes=10 if note.recognition_status == "running" else 30):
            recognition_service.recover_stale(db, note_id)
            note = _note(db, note_id, user)
    return _detail(db, note, user)


def get_image(db, note_id, user, original):
    note = _note(db, note_id, user)
    path = storage.image_path(note.original_path if original else note.scan_path)
    if not path.is_file():
        raise HTTPException(404, "照片不存在")
    return path


def _check_draft_only(db, note):
    if db.scalar(select(Batch.id).where(
        Batch.note_id == note.id, Batch.sync_status != "voided",
    ).limit(1).with_for_update()):
        raise HTTPException(409, "单据已有未作废的入库批次")


def recognize(db, note_id, user, body):
    note = _note(db, note_id, user, edit=True, version=body.version)
    _check_draft_only(db, note)
    if note.recognition_status in {"queued", "running"}:
        raise HTTPException(409, "已有识别任务在运行")
    if body.original and not note.original_path:
        raise HTTPException(422, "此单没有原图")
    for key, value in recognition_service.queue_values().items():
        setattr(note, key, value)
    _log(db, note, user, "recognize", after={"original": body.original})
    attempt = note.recognition_attempt_id
    db.commit()
    jobs.submit(note_id, attempt, body.original)
    return get_note(db, note_id, user)


def confirm_delivery(db, note_id, user, body):
    note = _note(db, note_id, user, edit=True, version=body.version)
    if note.recognition_status != "done":
        raise HTTPException(409, "请先完成识别或手工录入")
    number = body.delivery_no
    if number == note.delivery_no and note.duplicate_suspected_note_id is None:
        return _detail(db, note, user)
    _check_draft_only(db, note)
    duplicate = recognition_service.duplicate_note(db, note, number)
    if duplicate:
        note.duplicate_suspected_note_id = duplicate.id
        _log(db, note, user, "duplicate_check", after={"delivery_no": number})
    else:
        _log(db, note, user, "confirm_delivery", {"delivery_no": note.delivery_no}, {"delivery_no": number})
        note.delivery_no = number
        note.duplicate_suspected_note_id = None
    try:
        db.commit()
    except IntegrityError:
        logger.warning("Factory inbound delivery number collision for note %s", note_id)
        print(f"[FactoryInbound] Delivery number collision note={note_id}", flush=True)
        db.rollback()
        note = _note(db, note_id, user, edit=True, version=body.version)
        duplicate = recognition_service.duplicate_note(db, note, number)
        if not duplicate:
            raise
        note.duplicate_suspected_note_id = duplicate.id
        _log(db, note, user, "duplicate_check", after={"delivery_no": number})
        db.commit()
    return _detail(db, note, user)


def void_note(db, note_id, user, body):
    note = _note(db, note_id, user, edit=True, version=body.version)
    _check_draft_only(db, note)
    duplicate = _current_duplicate(db, note) if body.duplicate else None
    if body.duplicate and not duplicate:
        raise HTTPException(409, "当前没有待核对的重复单据")
    if duplicate:
        note.duplicate_of_note_id = duplicate.id
    note.status = "voided"
    _log(db, note, user, "void", after={"reason": body.reason.strip(), "duplicate": body.duplicate})
    db.commit()
    return presentation.card(note)


def _matching(db, values):
    ref = normalize_ref(values.get("order_ref_raw"))
    return MatchingContext(db, [ref])


def _suggest_color(db, values, product, user):
    term = color_key(values.get("color_raw"))
    target = product["color"]
    if not term or not target or term == color_key(target):
        raise HTTPException(422, "该颜色无需添加别名")
    existing = db.scalar(select(Alias).where(Alias.kind == "color", Alias.factory_term == term))
    if existing:
        raise HTTPException(409, "该颜色已有词条，请到词表核对")
    actor = presentation.actor_id(user)
    if presentation.is_admin(user):
        db.add(Alias(kind="color", factory_term=term, target=target, source="manual", updated_by=actor))
    else:
        prior = db.scalar(select(AliasSuggestion.id).where(
            AliasSuggestion.factory_term == term, AliasSuggestion.target == target, AliasSuggestion.status == "pending",
        ).limit(1))
        if not prior:
            db.add(AliasSuggestion(factory_term=term, target=target, suggested_by=actor))


def _validate_choice(db, status, match, choice, user):
    if choice.order:
        selected = next((row for row in match["orders"] if row["id"] == choice.order.id
                         and row["kind"] == choice.order.kind), None)
        if not selected:
            raise HTTPException(409, "订单候选已变化，请刷新后选择")
        if selected["kind"] == "invoice":
            signature = presentation.order_signatures(selected)
            same = sum(presentation.order_signatures(row) == signature for row in match["orders"])
            if same > 1 and not presentation.visible_invoices(db, user, {selected["id"]}):
                raise HTTPException(403, "重号发票需由拥有该发票查看权限的人员处理")
    if choice.route and (status != "decide" or choice.route not in match.get("allowed_routes", [])):
        raise HTTPException(409, "当前订单状态不允许选择此办理方式")
    if choice.confirm_conversion and status != "confirm":
        raise HTTPException(409, "当前明细无需确认换算")


def patch_line(db, note_id, line_id, body, user):
    note = _note(db, note_id, user, edit=True, version=body.version)
    if note.recognition_status != "done":
        raise HTTPException(409, "识别期间不能修改明细")
    line = db.scalar(select(Line).where(Line.note_id == note_id, Line.id == line_id).with_for_update())
    if not line:
        raise HTTPException(404, "明细不存在")
    if line.batch_id is not None:
        raise HTTPException(409, "已确认的批次明细不可改动")
    before = {"values": line.values, "decision": line.decision, "selected": line.selected,
              "writeback_enabled": line.writeback_enabled}
    edits = body.patch.model_dump(exclude_unset=True) if body.patch else {}
    values = {**line.values, **edits}
    if "grade_raw" in edits:
        values["grade_source"] = "explicit" if edits["grade_raw"] else "none"
    decision = {} if edits or body.refresh else dict(line.decision or {})
    status, match = line.match_status, line.match_data
    if edits or body.refresh or body.select:
        context = _matching(db, values)
        status, match = context.match(values, decision)
        if body.select:
            _validate_choice(db, status, match, body.select, user)
            choice = body.select
            changes = choice.model_dump(exclude_defaults=True, exclude={"suggest_color_alias", "sku_id"})
            if choice.order or choice.route:
                decision = {}
            decision.update(changes, by=presentation.actor_id(user), at=beijing_now().isoformat(),
                            candidates=[{"id": row["id"], "kind": row["kind"]} for row in match["orders"]])
            status, match = context.match(values, decision)
            if choice.sku_id:
                if not any(row["sku_id"] == choice.sku_id and not row["issue"] for row in match["candidates"]):
                    raise HTTPException(409, "产品候选已变化，请刷新后选择")
                decision["sku_id"] = choice.sku_id
                status, match = context.match(values, decision)
            if body.select.suggest_color_alias:
                if status != "matched":
                    raise HTTPException(422, "请先核对并选定颜色")
                _suggest_color(db, values, match["product"], user)
    if body.selected and status != "matched":
        raise HTTPException(422, "只有已匹配行可勾选")
    selected = line.selected if body.selected is None else body.selected
    if edits or body.refresh or body.select:
        selected = status == "matched" if body.selected is None else body.selected
    line.values, line.decision, line.match_status, line.match_data = values, decision, status, match
    line.selected = selected and status == "matched"
    if body.writeback_enabled is not None:
        line.writeback_enabled = body.writeback_enabled
    line.updated_by = presentation.actor_id(user)
    _log(db, note, user, "line_edit", before, {
        "values": values, "decision": decision, "selected": line.selected,
        "writeback_enabled": line.writeback_enabled,
    }, line.id)
    db.commit()
    return _detail(db, note, user)


def create_line(db, note_id, body, user):
    note = _note(db, note_id, user, edit=True, version=body.version)
    if note.recognition_status in {"queued", "running"}:
        raise HTTPException(409, "识别期间不能添加明细")
    number = db.scalar(select(func.max(Line.line_no)).where(Line.note_id == note_id)) or 0
    if number >= 150:
        raise HTTPException(422, "每张单最多核对 150 行")
    values = body.values.model_dump()
    values["grade_source"] = "explicit" if values["grade_raw"] else "none"
    status, match = _matching(db, values).match(values, {})
    if not db.scalar(select(LineType.code).where(LineType.code == values["line_type"], LineType.enabled)):
        raise HTTPException(422, "请选择有效的行类型")
    actor = presentation.actor_id(user)
    line = Line(note_id=note_id, line_no=number + 1, raw={"raw": "手工录入", "doubts": [], "inherited": []},
                values=values, match_status=status, match_data=match, selected=status == "matched", created_by=actor)
    db.add(line)
    db.flush()
    note.recognition_status = "done"
    note.recognition_error = None
    _log(db, note, user, "line_create", after=values, line_id=line.id)
    db.commit()
    return _detail(db, note, user)
