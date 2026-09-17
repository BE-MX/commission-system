"""Private receipt image storage; no static mount or public media URL."""
import hashlib
import io
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from app.receipt.models import Receipt, ReceiptAttachment, ReceiptIntent
from app.receipt.storage_proxy import origin

REPO_ROOT = Path(__file__).resolve().parents[3]
STORAGE_ROOT = REPO_ROOT / "backend" / "data" / "receipt-proofs"
MAX_BYTES = 10 * 1024 * 1024


def path_for(row):
    root = STORAGE_ROOT.resolve()
    path = (root / row.storage_key).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(404, "回款凭证不存在")
    return path


def upload(db, content, filename, actor):
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
    row = ReceiptAttachment(id=identity, filename=Path(filename or "receipt").name[:255],
                            storage_key=f"{identity}.{ext}", content_type=f"image/{'jpeg' if ext == 'jpg' else ext}",
                            size=len(content), sha256=hashlib.sha256(content).hexdigest(), created_by=actor)
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    path_for(row).write_bytes(content)
    db.add(row)
    db.flush()
    return row


def describe(row):
    return {"id": row.id, "name": row.filename, "size": row.size, "content_type": row.content_type}


def bind(db, ids, actor, invoice_id, receipt_id=None):
    if len(ids) != len(set(ids)) or not 1 <= len(ids) <= 5:
        raise ValueError("请上传 1 至 5 张不重复的回款截图")
    rows = db.query(ReceiptAttachment).filter(ReceiptAttachment.id.in_(ids)).with_for_update().all()
    if len(rows) != len(ids):
        raise ValueError("回款凭证不存在或上传未完成")
    if receipt_id:
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
        if not origin() and not path_for(row).is_file():
            raise ValueError("回款凭证文件缺失，请重新上传")
        row.invoice_id = invoice_id
        if receipt_id:
            row.receipt_id = receipt_id
    return rows
