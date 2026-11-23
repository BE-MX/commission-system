"""Each file commits independently. All domain mutations serialize before taking a snapshot."""
from contextlib import contextmanager
from hashlib import sha256
from sqlalchemy.exc import OperationalError

from fastapi import HTTPException
from sqlalchemy import select, update

from app.auth.models import ArkPermission
from app.cross_border.models import Declaration, ImportBatch, Receipt
from app.cross_border.parser import parse


@contextmanager
def write_transaction(db, *, freeze_sources=False):
    try:
        # MySQL SERIALIZABLE makes source reads shared locking reads until commit. This
        # also protects invoice cancellation, outbound edits and waybill rebinds in other domains.
        if freeze_sources and db.get_bind().dialect.name == "mysql":
            db.connection(execution_options={"isolation_level": "SERIALIZABLE"})
        # The seeded permission is a stable domain-wide lock even before the first import.
        # No authentication reads share this session. Lock before the first consistent read.
        condition = ArkPermission.code == "cross_border:write"
        if db.get_bind().dialect.name == "sqlite":
            db.execute(update(ArkPermission).where(condition).values(id=ArkPermission.id))
        elif db.scalar(select(ArkPermission.id).where(condition).with_for_update()) is None:
            raise HTTPException(503, "跨境申报权限尚未初始化")
        yield
        db.commit()
    except OperationalError as exc:
        db.rollback()
        if exc.orig.args and exc.orig.args[0] in (1205, 1213):
            raise HTTPException(409, "相关业务正在更新，请刷新后再操作") from exc
        raise
    except Exception:
        db.rollback()
        raise


def batch_info(batch):
    return dict(id=batch.id, file_name=batch.file_name, file_kind=batch.file_kind, row_count=batch.row_count,
                imported_by=batch.imported_by, imported_at=batch.imported_at, added=batch.added,
                existed=batch.row_count - batch.added, suspected=batch.suspected)


def import_file(db, file_name, content, actor):
    kind, entries = parse(file_name, content)
    digest = sha256(content).hexdigest()
    with write_transaction(db):
        existing = db.scalar(select(ImportBatch).where(ImportBatch.file_sha256 == digest))
        if existing:
            return {**batch_info(existing), "status": "duplicate", "message": "已导入过"}
        batch = ImportBatch(file_kind=kind, file_name=file_name[:255], file_sha256=digest,
                            row_count=len(entries), content_hashes=[e.content_hash for e in entries], imported_by=actor)
        db.add(batch)
        db.flush()
        model = Declaration if kind == "order" else Receipt
        orders = {e.head["orderNo"] for e in entries}
        previous = {row.content_hash: row for row in db.scalars(select(model).where(model.order_no.in_(orders)))}
        for entry in entries:
            row = previous.pop(entry.content_hash, None)
            if row is None:
                batch.added += 1
                row = model(content_hash=entry.content_hash, order_no=entry.head["orderNo"], occurrence=entry.occurrence,
                            first_import_id=batch.id, first_row_no=entry.row_no)
                db.add(row)
            row.last_import_id = batch.id
            row.base_json = entry.base
            if kind == "order":
                row.head_json, row.line_json, row.suspected_changed = entry.head, entry.line, False
            else:
                row.receipt_json = entry.head
        if kind == "order":
            for row in previous.values():
                if row.status == "active":
                    row.suspected_changed = True
                    batch.suspected += 1
        result = batch_info(batch)
    return {**result, "status": "imported"}


def list_batches(db):
    return [batch_info(row) for row in db.scalars(select(ImportBatch).order_by(ImportBatch.id.desc()))]
