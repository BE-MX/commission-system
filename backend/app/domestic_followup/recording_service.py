"""跟进录音：上传进 domestic 存储（必须是共享 COS），办公室 worker 转写为 txt。

上传端（北京或办公室）只写对象和一行 queued 记录；转写由 recording_worker 在
ASR_WORKER_ENABLED 的实例上完成。录音转写成功、txt 回读校验后删除原音频。
"""
import hashlib
import logging
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.storage import files as cloud_files
from app.core.storage.cos import StorageError
from app.core.time import beijing_now
from app.domestic import file_service
from app.domestic.models import DomesticCustomer
from app.domestic_followup import visibility
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupRecording

logger = logging.getLogger("commission")

STORAGE_DOMAIN = "domestic"
MAX_BYTES = 200 * 1024 * 1024
MAX_PER_FOLLOWUP = 3
MAX_UNBOUND_PER_DAY = 20
AUDIO_TYPES = {
    ".m4a": {"audio/mp4", "audio/x-m4a", "audio/m4a", "audio/aac"},
    ".mp3": {"audio/mpeg", "audio/mp3"},
    ".wav": {"audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"},
    ".aac": {"audio/aac", "audio/x-aac"},
    ".amr": {"audio/amr"},
    ".ogg": {"audio/ogg", "application/ogg"},
    ".opus": {"audio/opus", "audio/ogg"},
    ".flac": {"audio/flac", "audio/x-flac"},
    ".webm": {"audio/webm", "video/webm"},
}
# 浏览器对 m4a/amr 常报空或 octet-stream，按后缀判定；内容由 ASR 解码兜底
_GENERIC_MIMES = {"", "application/octet-stream", "binary/octet-stream"}


def _validate(filename: str, mime_type: str, size: int) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in AUDIO_TYPES:
        raise ValueError("只支持录音文件：" + " ".join(sorted(AUDIO_TYPES)))
    if size <= 0:
        raise ValueError("录音文件为空")
    if size > MAX_BYTES:
        raise ValueError("录音不能超过 200MB")
    mime = (mime_type or "").split(";")[0].strip().lower()
    if mime not in _GENERIC_MIMES and mime not in AUDIO_TYPES[ext]:
        raise ValueError(f"文件类型 {mime} 与后缀 {ext} 不匹配")
    return ext


def _visible_followup(db: Session, current_user: dict, followup_id: int) -> DomesticFollowup:
    query = db.query(DomesticFollowup).filter(DomesticFollowup.id == followup_id,
                                               DomesticFollowup.status != "discarded")
    condition = visibility.followup_filter(current_user)
    if condition is not None:
        query = query.filter(condition)
    row = query.first()
    if row is None:
        raise LookupError("跟进记录不存在或无权查看")
    return row


def _attachable(db: Session, current_user: dict, followup_id: int) -> DomesticFollowup:
    """直接挂到已有记录：草稿仅作者；已确认记录需能修改（作者或超管）。"""
    from app.domestic_followup.edit_service import can_edit

    row = (db.query(DomesticFollowup).filter(DomesticFollowup.id == followup_id)
           .populate_existing().with_for_update().first())
    if row is None or row.status == "discarded":
        raise LookupError("跟进记录不存在")
    if row.status == "draft" and row.author_user_id != visibility.uid(current_user):
        raise PermissionError("只能给自己的草稿添加录音")
    if row.status == "confirmed" and not can_edit(current_user, row):
        raise PermissionError("只能给本人录入的跟进记录添加录音")
    active = db.query(func.count(DomesticFollowupRecording.id)).filter(
        DomesticFollowupRecording.followup_id == followup_id,
        DomesticFollowupRecording.archived_at.is_(None)).scalar()
    if active >= MAX_PER_FOLLOWUP:
        raise ValueError(f"每条跟进最多 {MAX_PER_FOLLOWUP} 段录音")
    return row


def _store(ext: str, content: bytes, mime: str) -> str:
    name = f"{uuid.uuid4().hex}{ext}"
    key = f"audio/{name[:2]}/{name}"
    # 录音必须进共享 COS：落本地盘另一台机器（转写在办公室）读不到
    try:
        stored = cloud_files.put_bytes(STORAGE_DOMAIN, key, content, mime or None)
    except StorageError as exc:
        raise ValueError("录音存储暂时不可用，请稍后重试") from exc
    if not stored:
        raise ValueError("录音存储未接入共享云存储，请联系管理员")
    return key


def upload(db: Session, current_user: dict, filename: str, mime_type: str, content: bytes, *,
           followup_id: int | None = None, hotwords: str | None = None) -> DomesticFollowupRecording:
    user_id = visibility.uid(current_user)
    ext = _validate(filename, mime_type, len(content))
    target = _attachable(db, current_user, followup_id) if followup_id else None
    digest = hashlib.sha256(content).hexdigest()
    since = beijing_now() - timedelta(days=1)
    duplicate = (db.query(DomesticFollowupRecording)
                 .filter(DomesticFollowupRecording.uploader_user_id == user_id,
                         DomesticFollowupRecording.sha256 == digest,
                         DomesticFollowupRecording.followup_id.is_(None),
                         DomesticFollowupRecording.archived_at.is_(None),
                         DomesticFollowupRecording.asr_status != "failed",
                         DomesticFollowupRecording.created_at >= since)
                 .order_by(DomesticFollowupRecording.id.desc()).first())
    if duplicate is not None and target is None:
        return duplicate
    if target is None:
        unbound = db.query(func.count(DomesticFollowupRecording.id)).filter(
            DomesticFollowupRecording.uploader_user_id == user_id,
            DomesticFollowupRecording.followup_id.is_(None),
            DomesticFollowupRecording.created_at >= since).scalar()
        if unbound >= MAX_UNBOUND_PER_DAY:
            raise ValueError("今天还有很多录音没保存到跟进，请先保存或作废手上的草稿")
    key = _store(ext, content, (mime_type or "").split(";")[0].strip())
    row = DomesticFollowupRecording(
        followup_id=target.id if target else None, uploader_user_id=user_id,
        seq=_next_seq(db, target.id) if target else 0, file_key=key,
        file_name=(filename or "")[:255], mime_type=(mime_type or "")[:64], file_size=len(content),
        sha256=digest, hotwords=_clean_hotwords(hotwords), asr_status="queued", next_attempt_at=beijing_now(),
    )
    db.add(row)
    db.flush()
    return row


def _next_seq(db: Session, followup_id: int) -> int:
    current = db.query(func.max(DomesticFollowupRecording.seq)).filter(
        DomesticFollowupRecording.followup_id == followup_id).scalar()
    return int(current or 0) + 1


def _clean_hotwords(value: str | None) -> str | None:
    words = [w.strip() for w in (value or "").replace("，", ",").split(",") if w.strip()]
    return ",".join(dict.fromkeys(words))[:500] or None


def lock_rows(db: Session, followup_id: int, ids: list[int]) -> list[DomesticFollowupRecording]:
    existing = db.query(DomesticFollowupRecording.id).filter(
        DomesticFollowupRecording.followup_id == followup_id).all()
    rows = []
    for rid in sorted(set(ids) | {r[0] for r in existing}):
        row = (db.query(DomesticFollowupRecording).filter(DomesticFollowupRecording.id == rid)
               .populate_existing().with_for_update().first())
        if row is not None:
            rows.append(row)
    return rows


def bind(db: Session, user_id: int, followup_id: int, recording_ids: list[int]) -> None:
    """新建草稿/直接保存时绑定本人未用的录音；调用方已持有父记录。"""
    ids = list(dict.fromkeys(recording_ids or []))
    if len(ids) > MAX_PER_FOLLOWUP:
        raise ValueError(f"每条跟进最多 {MAX_PER_FOLLOWUP} 段录音")
    by_id = {r.id: r for r in lock_rows(db, followup_id, ids)}
    for seq, rid in enumerate(ids, start=1):
        row = by_id.get(rid)
        if row is None or row.archived_at is not None:
            raise LookupError("录音不存在或已失效，请重新上传")
        if row.uploader_user_id != user_id:
            raise PermissionError("不能使用他人上传的录音")
        if row.followup_id not in (None, followup_id):
            raise PermissionError("该录音已用于另一条记录，请重新上传")
        row.followup_id, row.seq = followup_id, seq
    db.flush()


def reconcile_on_edit(db: Session, followup_id: int, recording_ids: list[int] | None, actor_id: int) -> None:
    """修改已确认记录：None 表示前端未传，保持不变；列表外的录音归档留痕。"""
    if recording_ids is None:
        return
    ids = list(dict.fromkeys(recording_ids))
    if len(ids) > MAX_PER_FOLLOWUP:
        raise ValueError(f"每条跟进最多 {MAX_PER_FOLLOWUP} 段录音")
    rows = lock_rows(db, followup_id, ids)
    by_id = {r.id: r for r in rows}
    for rid in ids:
        row = by_id.get(rid)
        if row is None:
            raise LookupError("录音不存在，请重新上传")
        if row.followup_id != followup_id and (row.followup_id is not None or row.uploader_user_id != actor_id):
            raise PermissionError("只能保留本记录的录音或添加本人上传且未使用的录音")
    for row in rows:
        if row.id in ids:
            row.followup_id, row.archived_at, row.seq = followup_id, None, ids.index(row.id) + 1
        elif row.archived_at is None:
            row.archived_at = beijing_now()


def serialize(row: DomesticFollowupRecording, *, queue_position: int | None = None) -> dict:
    return {
        "id": row.id, "followup_id": row.followup_id, "seq": row.seq, "file_name": row.file_name,
        "file_size": row.file_size, "asr_status": row.asr_status, "attempts": row.attempts,
        "duration_sec": row.duration_sec, "transcript_chars": row.transcript_chars,
        "error_message": row.error_message if row.asr_status != "done" else None,
        "audio_available": bool(row.file_key) and row.audio_deleted_at is None,
        "organize_status": row.organize_status, "organize_error": row.organize_error,
        "queue_position": queue_position,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def queue_position(db: Session, row: DomesticFollowupRecording) -> int | None:
    if row.asr_status != "queued":
        return None
    ahead = db.query(func.count(DomesticFollowupRecording.id)).filter(
        DomesticFollowupRecording.asr_status.in_(("queued", "running")),
        DomesticFollowupRecording.archived_at.is_(None),
        DomesticFollowupRecording.id < row.id).scalar()
    return int(ahead or 0) + 1


def list_for(db: Session, followup_ids: list[int]) -> dict[int, list[dict]]:
    rows = (db.query(DomesticFollowupRecording)
            .filter(DomesticFollowupRecording.followup_id.in_(followup_ids or [0]),
                    DomesticFollowupRecording.archived_at.is_(None))
            .order_by(DomesticFollowupRecording.followup_id, DomesticFollowupRecording.seq).all())
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row.followup_id, []).append(serialize(row))
    return grouped


def get_readable(db: Session, current_user: dict, recording_id: int) -> DomesticFollowupRecording:
    """上传人本人，或能看到所属记录的人（与截图同口径）。"""
    row = db.get(DomesticFollowupRecording, recording_id)
    if row is None:
        raise LookupError("录音不存在")
    if row.uploader_user_id != visibility.uid(current_user):
        if row.followup_id is None:
            raise PermissionError("无权查看该录音")
        followup = _visible_followup(db, current_user, row.followup_id)
        if followup.status != "confirmed" and followup.author_user_id != visibility.uid(current_user):
            raise PermissionError("无权查看该录音")
    return row


def detail(db: Session, current_user: dict, recording_id: int) -> dict:
    row = get_readable(db, current_user, recording_id)
    data = serialize(row, queue_position=queue_position(db, row))
    if row.asr_status == "done":
        data["segments"] = row.segments or []
        data["transcript_text"] = row.transcript_text
    if row.organize_status == "done":
        data["organize_result"] = row.organize_result
    return data


def transcript_download(db: Session, current_user: dict, recording_id: int) -> tuple[bytes, str]:
    row = get_readable(db, current_user, recording_id)
    if row.asr_status != "done" or not row.transcript_key:
        raise LookupError("转写尚未完成")
    try:
        path = file_service.resolve_path(row.transcript_key)
    except file_service.FileValidationError as exc:
        raise ValueError(str(exc)) from exc
    content = Path(path).read_bytes()
    return content, _download_name(db, row)


def _download_name(db: Session, row: DomesticFollowupRecording) -> str:
    parts = []
    followup = db.get(DomesticFollowup, row.followup_id) if row.followup_id else None
    if followup is not None:
        customer = db.get(DomesticCustomer, followup.customer_id) if followup.customer_id else None
        if customer is not None:
            parts.append(customer.shop_name)
        parts.append(followup.followup_date.isoformat())
    parts.append(Path(row.file_name or f"录音{row.id}").stem)
    name = "_".join(p for p in parts if p)
    return "".join(c for c in name if c not in '\\/:*?"<>|\r\n')[:120] + "_转写.txt"


def retry(db: Session, current_user: dict, recording_id: int) -> DomesticFollowupRecording:
    row = (db.query(DomesticFollowupRecording).filter(DomesticFollowupRecording.id == recording_id)
           .populate_existing().with_for_update().first())
    if row is None:
        raise LookupError("录音不存在")
    if row.uploader_user_id != visibility.uid(current_user) and not visibility.is_super_admin(current_user):
        raise PermissionError("只有上传人可以重试")
    if row.asr_status != "failed":
        raise ValueError("只有失败的录音可以重试")
    if not row.file_key:
        raise ValueError("原音频已不存在，请重新上传")
    row.asr_status, row.attempts, row.error_message = "queued", 0, None
    row.next_attempt_at = beijing_now()
    db.flush()
    return row
