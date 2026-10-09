"""Private receipt image storage; no static mount or public media URL."""
from dataclasses import dataclass, field
import hashlib
import io
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from app.receipt.models import Receipt, ReceiptAttachment, ReceiptIntent
from app.receipt.storage_proxy import origin
from app.core.storage import files as cloud_files

REPO_ROOT = Path(__file__).resolve().parents[3]
STORAGE_ROOT = REPO_ROOT / "backend" / "data" / "receipt-proofs"
MAX_BYTES = 10 * 1024 * 1024


def path_for(row):
    root = STORAGE_ROOT.resolve()
    path = (root / row.storage_key).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(404, "回款凭证不存在")
    return cloud_files.read_path('receipt-proofs', row.storage_key, root)


@dataclass(frozen=True)
class UploadData:
    id: str
    filename: str
    storage_key: str
    content_type: str
    content: bytes = field(repr=False)
    created_by: int


@dataclass(frozen=True)
class StoredUpload:
    data: UploadData
    local_path: Path | None = None
    cloud_store: object = field(default=None, repr=False, compare=False)


def prepare_upload(content, filename, actor):
    if not content or len(content) > MAX_BYTES:
        raise ValueError("图片为空或超过 10MB")
    try:
        with Image.open(io.BytesIO(content)) as image:
            fmt = image.format
            if fmt not in {"PNG", "JPEG", "WEBP"} or image.width * image.height > 40_000_000:
                raise ValueError("仅支持 PNG/JPEG/WebP，图片不能超过 4000 万像素")
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("图片损坏或格式不支持") from exc
    ext = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}[fmt]
    identity = uuid4().hex
    return UploadData(identity, Path(filename or "receipt").name[:255], f"{identity}.{ext}",
        f"image/{'jpeg' if ext == 'jpg' else ext}", bytes(content), actor)


def store_upload(data):
    """No DB session; freeze the actual backend for rejection cleanup."""
    from tempfile import TemporaryDirectory
    from app.core.config import get_settings
    from app.core.storage.cos import CosObjectStore, StorageError, enabled
    if enabled('receipt-proofs'):
        store = CosObjectStore('receipt-proofs')
        staged = StoredUpload(data, cloud_store=store)
        cache = Path(get_settings().COS_CACHE_ROOT)
        cache.mkdir(parents=True, exist_ok=True)
        with cloud_files.reserve_processing_bytes(len(data.content)), TemporaryDirectory(prefix='upload-', dir=cache) as temporary:
            source = Path(temporary) / 'object'
            source.write_bytes(data.content)
            store.put_file(data.storage_key, source, data.content_type)
        return staged
    if cloud_files.managed('receipt-proofs'):
        raise StorageError('New cloud uploads are paused for this domain')
    destination = cloud_files.local_path(STORAGE_ROOT, data.storage_key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as stream:
        stream.write(data.content)
    return StoredUpload(data, local_path=destination)


def discard_upload(staged):
    # Only called before registration begins, using this write's frozen backend.
    if staged.cloud_store is not None:
        staged.cloud_store.delete(staged.data.storage_key)
    elif staged.local_path is not None:
        staged.local_path.unlink(missing_ok=True)


def register_upload(db, staged, actor):
    data = staged.data
    if data.created_by != actor:
        raise HTTPException(403, "上传操作人已变化")
    row = ReceiptAttachment(id=data.id, filename=data.filename, storage_key=data.storage_key,
        content_type=data.content_type, size=len(data.content),
        sha256=hashlib.sha256(data.content).hexdigest(), created_by=actor)
    db.add(row)
    db.flush()
    return row


def describe(row):
    return {"id": row.id, "name": row.filename, "size": row.size, "content_type": row.content_type}


def _checked_rows(db, ids, actor, invoice_id, receipt_id=None, *, current=False):
    if len(ids) != len(set(ids)) or not 1 <= len(ids) <= 5:
        raise ValueError("请上传 1 至 5 张不重复的回款截图")
    from app.invoice.settlement_models import BatchAttachment
    # Current edit phases take Intent before attachments, matching final balance locks.
    if current and receipt_id:
        receipt = db.get(Receipt, receipt_id)
        intent = db.query(ReceiptIntent).filter(ReceiptIntent.invoice_id == invoice_id).populate_existing().with_for_update().first()
    rows = db.query(ReceiptAttachment).filter(ReceiptAttachment.id.in_(ids)).order_by(
        ReceiptAttachment.id).populate_existing().with_for_update().all()
    if db.query(BatchAttachment).filter(BatchAttachment.attachment_id.in_(ids)).with_for_update().first():
        raise ValueError("凭证属于汇总回款，请通过原批次读取")
    if len(rows) != len(ids):
        raise ValueError("回款凭证不存在或上传未完成")
    if receipt_id:
        if not current:
            receipt = db.get(Receipt, receipt_id)
            intent = db.query(ReceiptIntent).filter(ReceiptIntent.invoice_id == invoice_id).first()
        if receipt and receipt.source == "manual" and intent and intent.eligible and intent.status in {"draft", "armed", "ready"}:
            if set(ids).intersection(intent.attachment_ids):
                raise ValueError("该截图已用于库存单的自动回款，请上传本次回款凭证")
    for row in rows:
        # Unbound uploads belong only to their uploader. Once invoice-bound,
        # caller must already have passed invoice visibility/write checks.
        if row.invoice_id is None and row.created_by != actor:
            raise ValueError("无权使用他人的回款凭证")
        if row.invoice_id not in (None, invoice_id) or row.receipt_id not in (None, receipt_id):
            raise ValueError("凭证已关联其他回款，请上传本次凭证")
        if receipt_id and row.receipt_id == receipt_id and row.id not in receipt.attachment_ids:
            raise ValueError("该截图已从回款中移除，请重新上传")
    return rows


@dataclass(frozen=True)
class AttachmentBinding:
    id: str
    storage_key: str
    values: tuple


@dataclass(frozen=True)
class FileEvidence:
    bindings: tuple


def _bindings(rows):
    return tuple(AttachmentBinding(row.id, row.storage_key,
        tuple(getattr(row, column.name) for column in row.__table__.columns)) for row in rows)


def capture_binding(db, ids, actor, invoice_id, receipt_id):
    return _bindings(_checked_rows(db, ids, actor, invoice_id, receipt_id, current=True))


def verify_storage(bindings):
    # Only independent frozen file identities are inspected outside business locks.
    if not origin():
        for binding in bindings:
            if not path_for(binding).is_file():
                raise ValueError("回款凭证文件缺失，请重新上传")
    return FileEvidence(bindings)


def _apply(rows, invoice_id, receipt_id):
    for row in rows:
        row.invoice_id = invoice_id
        if receipt_id:
            row.receipt_id = receipt_id
    return rows


def bind_verified(db, ids, actor, invoice_id, receipt_id, evidence):
    rows = _checked_rows(db, ids, actor, invoice_id, receipt_id, current=True)
    if not isinstance(evidence, FileEvidence) or _bindings(rows) != evidence.bindings:
        from fastapi import HTTPException
        raise HTTPException(409, "回款凭证在核验期间已变化，请重新读取")
    return _apply(rows, invoice_id, receipt_id)


def bind(db, ids, actor, invoice_id, receipt_id=None):
    # Existing create/delivery callers retain the full DB + storage validation contract.
    rows = _checked_rows(db, ids, actor, invoice_id, receipt_id)
    verify_storage(_bindings(rows))
    return _apply(rows, invoice_id, receipt_id)
