"""Current-authorized automatic receipt proof updates with unlocked file reads."""
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.storage.cos import StorageError
from app.receipt import access, attachments, authority, retry_service, service
from app.receipt.models import ReceiptIntent


def _intent(db, row, invoice, body):
    if row.batch_id or row.source != "auto" or row.status != "active":
        raise ValueError("仅订单自动生成的有效回款可在订单发票中修改截图")
    if row.sync_status == "syncing":
        raise ValueError("回款正在处理，请稍后刷新再修改截图")
    if row.version != body.version:
        raise HTTPException(409, "回款已被修改，请刷新后重试")
    intent = db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id == invoice.id)
        .with_for_update().execution_options(populate_existing=True))
    if not intent or intent.status != "converted" or intent.receipt_id != row.id:
        raise ValueError("订单回款记录已变化，请刷新后重试")
    return intent


def _binding(row, invoice, intent):
    data = [[getattr(value, column.name) for column in value.__table__.columns]
        for value in (row, invoice, intent)]
    return hashlib.sha256(json.dumps(data, default=str).encode()).hexdigest()


def update(db, identity, body, user):
    row, invoice, current, _, _ = authority.local_group(db, identity, user)
    intent = _intent(db, row, invoice, body)
    expected = _binding(row, invoice, intent)
    files = attachments.capture_binding(db, body.attachment_ids, access.user_id(current), invoice.id, row.id)
    db.commit()  # No commercial mutation; release business locks before file IO.
    try:
        evidence = attachments.verify_storage(files)
    except (ValueError, OSError, StorageError, HTTPException) as error:
        retry_service._unavailable(error, message="回款截图证据暂不可用，请核对原单")
    finally:
        # File evidence has no provider token/cache work or phase-two commit.
        db.rollback()
        db.expire_all()
    row, invoice, current, _, _ = authority.local_group(db, identity, user)
    intent = _intent(db, row, invoice, body)
    if _binding(row, invoice, intent) != expected:
        raise HTTPException(409, "回款、订单或自动意图在核验期间已变化，请重新读取")
    service._change_proofs(db, row, invoice, body, access.user_id(current), evidence)
    return row, invoice


def result_unavailable(error):
    retry_service._unavailable(error, message="回款截图修改结果暂不能确认，请刷新原单核对")
