"""Stock posting primitives. Caller owns commit; every command is savepoint atomic.

Warehouse rows are ordered mutexes, including empty balances. All stock writers
must use this service; this also serializes first receipt into a new bucket.
"""

import hashlib
import json
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.catalog.models import CatalogProduct, CatalogSku
from app.inventory.models import StockBalance, StockDocument, StockLedger, Warehouse
from app.inventory.schemas import DocumentCreate

logger = logging.getLogger(__name__)


def _hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _claim_document(db, key, payload, **fields):
    digest = _hash(payload)
    # Insert first: locking an absent unique key takes a gap lock under MySQL
    # REPEATABLE READ, so two first writers could deadlock before either inserts.
    doc = StockDocument(idempotency_key=key, payload_hash=digest, payload=payload, **fields)
    try:
        with db.begin_nested():
            db.add(doc)
            db.flush()
    except IntegrityError:
        logger.warning("Stock document uniqueness conflict; checking committed command identity")
        print("Stock document uniqueness conflict; checking committed command identity", flush=True)
        existing = db.scalar(select(StockDocument).where(StockDocument.idempotency_key == key)
                             .with_for_update().execution_options(populate_existing=True))
        if existing is None:
            raise
        if existing.payload_hash != digest:
            raise ValueError("幂等键已用于不同的库存操作") from None
        return existing, False
    return doc, True


def _lock_warehouses(db, ids, *, allow_inactive=False):
    # Separate primary-key reads impose the same lock order on every DB plan.
    for warehouse_id in sorted(set(ids)):
        row = db.scalar(select(Warehouse).where(Warehouse.id == warehouse_id)
                        .with_for_update().execution_options(populate_existing=True))
        if row is None:
            raise ValueError("仓库不存在")
        if not row.active and not allow_inactive:
            raise ValueError("仓库已停用")


def _validate_skus(db, ids):
    product_ids = db.scalars(select(CatalogSku.product_id).where(CatalogSku.id.in_(set(ids)))).all()
    for product_id in sorted(set(product_ids)):
        product = db.scalar(select(CatalogProduct).where(CatalogProduct.id == product_id)
                            .with_for_update().execution_options(populate_existing=True))
        if product is None or not product.active:
            raise ValueError("产品已停用或不存在")
    for sku_id in sorted(set(ids)):
        sku = db.scalar(select(CatalogSku).where(CatalogSku.id == sku_id)
                        .with_for_update().execution_options(populate_existing=True))
        if sku is None:
            raise ValueError("SKU 不存在")
        if not sku.active:
            raise ValueError("产品或 SKU 已停用")
        if sku.unit != "piece":
            raise ValueError("成品库存只接受件数；克数通过半成品账管理")


def _bucket(db, warehouse_id, sku_id, quality, *, create=True):
    from app.commerce_transition.service import require_resource_scope
    require_resource_scope(db, 'local', 'sku', str(sku_id), str(warehouse_id))
    query = select(StockBalance).where(
        StockBalance.warehouse_id == warehouse_id,
        StockBalance.sku_id == sku_id, StockBalance.quality == quality,
    )
    # Never take a locking range read before inserting an absent bucket. Even
    # distinct warehouses/products can share an empty secondary-index gap.
    existing_id = db.scalar(query.with_only_columns(StockBalance.id))
    if existing_id is not None:
        return db.scalar(select(StockBalance).where(StockBalance.id == existing_id)
                         .with_for_update().execution_options(populate_existing=True))
    if create:
        row = StockBalance(warehouse_id=warehouse_id, sku_id=sku_id, quality=quality,
                           on_hand=0, reserved=0, version=0)
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
            return row
        except IntegrityError:
            logger.warning("Stock bucket identity exists beyond prior snapshot; reading current balance")
            print("Stock bucket identity exists beyond prior snapshot; reading current balance", flush=True)
            row = db.scalar(query.with_for_update().execution_options(populate_existing=True))
            if row is None:
                raise
            return row
    # A stale RR snapshot may have missed a just-committed receipt. This current
    # read may hold an absent gap, but never inserts into that gap afterwards.
    row = db.scalar(query.with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise ValueError("库存不足：该仓库尚无此产品的可售库存")
    return row


def _move(db, doc, line_no, bucket, on_hand, reserved=0):
    after_hand = bucket.on_hand + on_hand
    after_reserved = bucket.reserved + reserved
    if after_hand < 0 or after_reserved < 0 or after_hand < after_reserved:
        raise ValueError("库存不足或已被订单预占，不能执行该操作")
    if after_hand > 2147483647 or after_reserved > 2147483647:
        raise ValueError("库存数量超过可存储范围")
    bucket.on_hand, bucket.reserved = after_hand, after_reserved
    bucket.version += 1
    db.add(StockLedger(document_id=doc.id, line_no=line_no, warehouse_id=bucket.warehouse_id,
                       sku_id=bucket.sku_id, quality=bucket.quality, on_hand_delta=on_hand,
                       reserved_delta=reserved, on_hand_after=after_hand, reserved_after=after_reserved))
    db.flush()


def post_document(db: Session, body: DocumentCreate, *, actor_id: int | None) -> StockDocument:
    from app.commerce_transition.service import require_phase, require_resource_scope
    require_phase(db, 'local')
    for line in sorted(body.lines, key=lambda row: (row.sku_id, row.warehouse_id)):
        for warehouse_id in sorted({line.warehouse_id, line.destination_warehouse_id} - {None}):
            require_resource_scope(db, 'local', 'sku', str(line.sku_id), str(warehouse_id))
    with db.begin_nested():
        doc, fresh = _claim_document(db, body.idempotency_key, body.model_dump(mode="json"),
                                    kind=body.kind, reason=body.reason, created_by=actor_id,
                                    source_type=body.source_type, source_id=body.source_id)
        if not fresh:
            return doc
        _lock_warehouses(db, [wid for line in body.lines for wid in
                             (line.warehouse_id, line.destination_warehouse_id) if wid is not None])
        _validate_skus(db, [line.sku_id for line in body.lines])
        line_no = 0
        for line in body.lines:
            bucket = _bucket(db, line.warehouse_id, line.sku_id, line.quality)
            if line.expected_version is not None and bucket.version != line.expected_version:
                raise ValueError("库存版本已变化，请刷新盘点数据后重试")
            if body.kind == "opening" and bucket.version:
                raise ValueError("已有库存流水，不能重复建立期初")
            delta = line.quantity
            if body.kind == "count":
                delta -= bucket.on_hand
            if body.kind == "transfer":
                delta = -delta
            line_no += 1
            _move(db, doc, line_no, bucket, delta)
            if body.kind == "transfer":
                destination = _bucket(db, line.destination_warehouse_id, line.sku_id, line.quality)
                line_no += 1
                _move(db, doc, line_no, destination, line.quantity)
        db.flush()
        return doc


def reverse_document(db: Session, document_id: int, key: str, reason: str, actor_id: int | None) -> StockDocument:
    from app.commerce_transition.service import require_phase
    require_phase(db, 'local')
    if not reason.strip():
        raise ValueError("冲销必须填写原因")
    with db.begin_nested():
        original = db.scalar(select(StockDocument).where(StockDocument.id == document_id)
                             .with_for_update().execution_options(populate_existing=True))
        if original is None:
            raise ValueError("原库存单据不存在")
        payload = {"reversal_of_id": document_id, "reason": reason}
        if original.reversed_by_id:
            existing = db.get(StockDocument, original.reversed_by_id)
            if existing.idempotency_key == key and existing.payload_hash == _hash(payload):
                return existing
            raise ValueError("该单据不允许再次冲销")
        if original.reversal_of_id:
            raise ValueError("该单据不允许再次冲销")
        if original.kind not in {"opening", "receipt", "adjustment", "count", "transfer"}:
            raise ValueError("该业务单据必须通过对应业务办理冲销")
        doc, fresh = _claim_document(db, key, payload, kind="reversal", reason=reason,
                                    reversal_of_id=document_id, created_by=actor_id)
        if not fresh:
            return doc
        facts = db.scalars(select(StockLedger).where(StockLedger.document_id == document_id)
                           .order_by(StockLedger.line_no)).all()
        _lock_warehouses(db, [f.warehouse_id for f in facts], allow_inactive=True)
        # Reverse ordering also supports a bucket appearing as both source and destination.
        for i, fact in enumerate(reversed(facts), start=1):
            bucket = _bucket(db, fact.warehouse_id, fact.sku_id, fact.quality)
            _move(db, doc, i, bucket, -fact.on_hand_delta, -fact.reserved_delta)
        original.reversed_by_id = doc.id
        db.flush()
        return doc


def list_balances(db, *, warehouse_id=None, sku_id=None, offset=0, limit=50):
    query = _named_stock_query(StockBalance)
    if warehouse_id is not None:
        query = query.where(StockBalance.warehouse_id == warehouse_id)
    if sku_id is not None:
        query = query.where(StockBalance.sku_id == sku_id)
    rows = db.execute(query.order_by(StockBalance.id).offset(offset).limit(limit)).all()
    return [{"id": row.id, "warehouse_id": row.warehouse_id, "sku_id": row.sku_id,
             "quality": row.quality, "on_hand": row.on_hand, "reserved": row.reserved,
             "available": row.on_hand - row.reserved if row.quality == "sellable" else 0,
             "version": row.version, "warehouse_name": warehouse_name, "sku_code": sku_code,
             "product_name": product_name} for row, warehouse_name, sku_code, product_name in rows]


def _named_stock_query(model):
    # Historical facts remain readable after any referenced master is disabled.
    return (select(model, Warehouse.name, CatalogSku.code, CatalogProduct.name).select_from(model)
            .join(Warehouse, Warehouse.id == model.warehouse_id)
            .join(CatalogSku, CatalogSku.id == model.sku_id)
            .join(CatalogProduct, CatalogProduct.id == CatalogSku.product_id))


def list_ledger(db, *, warehouse_id=None, sku_id=None, offset=0, limit=50):
    query = _named_stock_query(StockLedger).add_columns(StockDocument.kind, StockDocument.reason)
    query = query.join(StockDocument, StockDocument.id == StockLedger.document_id)
    if warehouse_id is not None:
        query = query.where(StockLedger.warehouse_id == warehouse_id)
    if sku_id is not None:
        query = query.where(StockLedger.sku_id == sku_id)
    rows = db.execute(query.order_by(StockLedger.id.desc()).offset(offset).limit(limit)).all()
    return [{**{key: getattr(row, key) for key in (
        "id", "document_id", "line_no", "warehouse_id", "sku_id", "quality", "on_hand_delta",
        "reserved_delta", "on_hand_after", "reserved_after", "created_at")},
        "warehouse_name": warehouse_name, "sku_code": sku_code, "product_name": product_name,
        "kind": kind, "reason": reason}
        for row, warehouse_name, sku_code, product_name, kind, reason in rows]


def document_dict(doc):
    return {key: getattr(doc, key) for key in ("id", "idempotency_key", "kind", "reason", "source_type",
            "source_id", "payload", "reversal_of_id", "reversed_by_id", "created_by", "created_at")}


def get_document(db, document_id):
    doc = db.get(StockDocument, document_id)
    if doc is None:
        raise ValueError("库存单据不存在")
    facts = db.execute(_named_stock_query(StockLedger).where(StockLedger.document_id == doc.id).order_by(StockLedger.line_no)).all()
    return {**document_dict(doc), "movements": [{**{key: getattr(row, key) for key in
            ("id", "line_no", "warehouse_id", "sku_id", "quality", "on_hand_delta", "reserved_delta",
             "on_hand_after", "reserved_after")}, "warehouse_name": warehouse_name,
             "sku_code": sku_code, "product_name": product_name}
             for row, warehouse_name, sku_code, product_name in facts]}


def list_documents(db, offset=0, limit=50):
    return [document_dict(row) for row in db.scalars(select(StockDocument).order_by(StockDocument.id.desc())
                                                   .offset(offset).limit(limit)).all()]


def list_warehouses(db):
    return [{"id": row.id, "code": row.code, "name": row.name, "active": row.active}
            for row in db.scalars(select(Warehouse).order_by(Warehouse.id)).all()]


def create_warehouse(db, body):
    if not body.code.strip() or not body.name.strip():
        raise ValueError("仓库编码和名称不能为空")
    row = Warehouse(code=body.code.strip(), name=body.name.strip())
    db.add(row)
    db.flush()
    return {"id": row.id, "code": row.code, "name": row.name, "active": row.active}
