"""Atomic, content-addressed master import and read-only historical archives.

An archive does not create an invoice, receipt, commission or stock movement.
Unfinished responsibilities require the separate, explicit opening contract.
"""
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import select, func
from app.auth.models import ArkUser
from app.catalog.models import CatalogExternalIdentity, CatalogProduct, CatalogSku
from app.commerce_migration.models import MigrationBatch, MigrationRecord
from app.finance.service import book


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _current(db, statement, lock):
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return db.scalar(statement)


def _entries(body):
    for index, row in enumerate(body.catalog):
        yield 'catalog', index, 'sku', f'sku:{digest([row.external_product_id, row.external_sku_id])}', row.model_dump(mode='json'), row
    for index, row in enumerate(body.archives):
        yield 'archive', index, row.object_type, row.external_id, row.snapshot, row


def _record(db, body, object_type, external_id, lock=False):
    return _current(db, select(MigrationRecord).where(MigrationRecord.source == body.source,
        MigrationRecord.tenant == body.tenant, MigrationRecord.object_type == object_type,
        MigrationRecord.external_id == external_id), lock)


def _alias(db, body, row, lock=False):
    return _current(db, select(CatalogExternalIdentity).where(CatalogExternalIdentity.source == body.source,
        CatalogExternalIdentity.tenant == body.tenant, CatalogExternalIdentity.external_product_id == row.external_product_id,
        CatalogExternalIdentity.external_sku_id == row.external_sku_id), lock)


def _matches(entity, expected):
    return all(getattr(entity, key) == value for key, value in expected.items())


def _same_alias(alias, body, row):
    return (alias.source, alias.tenant, alias.external_product_id, alias.external_sku_id) == (
        body.source, body.tenant, row.external_product_id, row.external_sku_id)


def _product_siblings(db, body, row, lock):
    statement = select(CatalogSku.product_id).join(CatalogExternalIdentity,
        CatalogExternalIdentity.sku_id == CatalogSku.id).where(
        CatalogExternalIdentity.source == body.source,
        CatalogExternalIdentity.tenant == body.tenant,
        CatalogExternalIdentity.external_product_id == row.external_product_id)
    if lock:
        statement = statement.with_for_update()
    return set(db.scalars(statement))


def _assert_record(record, body, role, object_type, external_id, snapshot):
    if ((record.source, record.tenant, record.object_type, record.external_id) !=
            (body.source, body.tenant, object_type, external_id) or
            record.content_hash != digest(snapshot) or record.role != role):
        raise ValueError('来源身份或核验内容冲突，不允许复用不同事实')


def preview(db, body, *, lock=False):
    conflicts = []
    def conflict(index, code, message, role='catalog'):
        conflicts.append({'section': role, 'record_index': index, 'code': code, 'message': message})
    batch = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == body.batch_key), lock)
    if batch is not None and batch.manifest_hash != digest(body.model_dump(mode='json')):
        conflict(None, 'batch_content_changed', '批次身份已用于不同内容，请核对原始清单', 'batch')
    products, skus, external_products = {}, {}, {}
    for role, index, object_type, external_id, snapshot, row in _entries(body):
        record = _record(db, body, object_type, external_id, lock)
        if role == 'catalog':
            product_values = {**row.product.model_dump(), 'active': row.product_active}
            sku_values = {**row.sku.model_dump(), 'unit': 'piece', 'active': row.sku_active}
            product_code, sku_code = row.product.code.lower(), row.sku.code.lower()
            if product_code in products and products[product_code] != product_values:
                conflict(index, 'manifest_product_conflict', '清单同一产品编码包含不同快照')
            if sku_code in skus and skus[sku_code] != (product_code, sku_values):
                conflict(index, 'manifest_sku_conflict', '清单同一SKU编码包含不同产品或规格')
            if row.external_product_id in external_products and external_products[row.external_product_id] != product_code:
                conflict(index, 'manifest_external_product_conflict', '同一外部产品指向多个本地产品')
            products[product_code], skus[sku_code] = product_values, (product_code, sku_values)
            external_products[row.external_product_id] = product_code
            product = _current(db, select(CatalogProduct).where(CatalogProduct.code == row.product.code), lock)
            mapped_sku = _current(db, select(CatalogSku).where(CatalogSku.id == record.local_sku_id), lock) if record else None
            expected_product_id = mapped_sku.product_id if mapped_sku else (product.id if product else None)
            siblings = _product_siblings(db, body, row, lock)
            if siblings and siblings != {expected_product_id}:
                conflict(index, 'external_product_conflict', '外部产品已关联不同本地产品，不允许拆分来源身份')
        if record is not None:
            if (record.source, record.tenant, record.object_type, record.external_id) != (body.source, body.tenant, object_type, external_id):
                conflict(index, 'source_identity_collision', '数据库排序规则将不同来源身份视为相同，请核对大小写及字符', role)
                continue
            if record.content_hash != digest(snapshot) or record.role != role:
                conflict(index, 'source_content_changed', '同一来源身份已有不同核验内容，不允许覆盖', role)
            elif role == 'catalog':
                alias = _alias(db, body, row, lock)
                if alias is None or not _same_alias(alias, body, row) or alias.sku_id != record.local_sku_id:
                    conflict(index, 'alias_conflict', '已导入来源映射与原稳定SKU不一致')
            continue
        if role == 'archive':
            continue
        sku = _current(db, select(CatalogSku).where(CatalogSku.code == row.sku.code), lock)
        alias = _alias(db, body, row, lock)
        if alias is not None and (not _same_alias(alias, body, row) or sku is None or alias.sku_id != sku.id):
            conflict(index, 'alias_conflict', '外部身份已关联其他SKU，不允许重新分配')
        if product is not None and not _matches(product, product_values):
            conflict(index, 'product_conflict', '现有产品与核验快照不同，不允许覆盖在线维护')
        if sku is not None and (product is None or sku.product_id != product.id or not _matches(sku, sku_values)):
            conflict(index, 'sku_conflict', '现有SKU所属产品或规格与核验快照不同')
    return {'manifest_hash': digest(body.model_dump(mode='json')), 'can_apply': not conflicts,
            'catalog_count': len(body.catalog), 'archive_count': len(body.archives), 'conflicts': conflicts}


def apply_manifest(db, body, user):
    # The same lock order will cover cash/AR responsibility openings. Importing
    # reference evidence never generates finance events or confirms receipts.
    with db.begin_nested():
        book(db)
        actor_id = int(user['sub'])
        actor = _current(db, select(ArkUser).where(ArkUser.id == actor_id), True)
        if actor is None or not actor.is_active or actor.deleted_at is not None:
            raise ValueError('导入账号不可用')
        existing = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == body.batch_key), True)
        manifest_hash = digest(body.model_dump(mode='json'))
        if existing is not None:
            if existing.manifest_hash != manifest_hash:
                raise ValueError('批次身份已用于不同内容，请核对原始清单')
            return existing.result
        report = preview(db, body, lock=True)
        if not report['can_apply']:
            raise ValueError(f'清单存在{len(report["conflicts"])}项冲突，请先查看预览差异')
        result = {'batch_key': body.batch_key, 'manifest_hash': manifest_hash, 'catalog': [], 'archives': []}
        batch = MigrationBatch(batch_key=body.batch_key, source=body.source, tenant=body.tenant,
            manifest_hash=manifest_hash, evidence_sha256=body.evidence_sha256,
            review_reference=body.review_reference, cutover_date=body.cutover_date,
            result={}, created_by=actor_id)
        db.add(batch); db.flush()
        for role, index, object_type, external_id, snapshot, row in _entries(body):
            record = _record(db, body, object_type, external_id, True)
            if record is not None:
                _assert_record(record, body, role, object_type, external_id, snapshot)
                if role == 'catalog':
                    alias = _alias(db, body, row, True)
                    sku = _current(db, select(CatalogSku).where(CatalogSku.id == record.local_sku_id), True)
                    if (alias is None or not _same_alias(alias, body, row) or sku is None or
                            alias.sku_id != sku.id or _product_siblings(db, body, row, True) != {sku.product_id}):
                        raise ValueError('已导入来源映射与原稳定SKU不一致')
            if record is None:
                sku = None
                if role == 'catalog':
                    product = _current(db, select(CatalogProduct).where(CatalogProduct.code == row.product.code), True)
                    if product is None:
                        product = CatalogProduct(**row.product.model_dump(), active=row.product_active)
                        db.add(product); db.flush()
                    elif not _matches(product, {**row.product.model_dump(), 'active': row.product_active}):
                        raise ValueError('现有产品与核验快照冲突')
                    sku = _current(db, select(CatalogSku).where(CatalogSku.code == row.sku.code), True)
                    if sku is None:
                        sku = CatalogSku(product_id=product.id, unit='piece', **row.sku.model_dump(), active=row.sku_active)
                        db.add(sku); db.flush()
                    elif sku.product_id != product.id or not _matches(sku, {**row.sku.model_dump(), 'unit': 'piece', 'active': row.sku_active}):
                        raise ValueError('现有SKU所属产品或规格与核验快照冲突')
                    siblings = _product_siblings(db, body, row, True)
                    if siblings and siblings != {product.id}:
                        raise ValueError('外部产品已关联不同本地产品')
                    alias = _alias(db, body, row, True)
                    if alias is None:
                        db.add(CatalogExternalIdentity(source=body.source, tenant=body.tenant,
                            external_product_id=row.external_product_id, external_sku_id=row.external_sku_id, sku_id=sku.id))
                    elif not _same_alias(alias, body, row) or alias.sku_id != sku.id:
                        raise ValueError('外部身份已关联其他SKU')
                record = MigrationRecord(batch_key=body.batch_key, source=body.source, tenant=body.tenant,
                    object_type=object_type, external_id=external_id, role=role, content_hash=digest(snapshot),
                    snapshot=snapshot, local_sku_id=sku.id if sku else None)
                db.add(record); db.flush()
            result['catalog' if role == 'catalog' else 'archives'].append({'record_id': record.id,
                'sku_id': record.local_sku_id} if role == 'catalog' else {'record_id': record.id, 'object_type': object_type, 'external_id': external_id})
        batch.result = result
        db.flush()
        return result


def describe_batch(db, batch_key):
    batch = db.get(MigrationBatch, batch_key)
    if batch is None:
        raise HTTPException(404, '导入批次不存在')
    return {**batch.result, 'source': batch.source, 'tenant': batch.tenant, 'evidence_sha256': batch.evidence_sha256,
        'review_reference': batch.review_reference, 'cutover_date': batch.cutover_date,
        'created_at': batch.created_at, 'created_by': batch.created_by}


def list_records(db, *, source=None, tenant=None, object_type=None, after_id=0, limit=50):
    query = select(MigrationRecord).where(MigrationRecord.id > after_id)
    for column, value in ((MigrationRecord.source, source), (MigrationRecord.tenant, tenant), (MigrationRecord.object_type, object_type)):
        if value is not None:
            query = query.where(column == value)
    rows = db.scalars(query.order_by(MigrationRecord.id).limit(limit)).all()
    return [{'id': row.id, 'batch_key': row.batch_key, 'source': row.source, 'tenant': row.tenant,
        'object_type': row.object_type, 'external_id': row.external_id, 'role': row.role,
        'content_hash': row.content_hash, 'snapshot': row.snapshot, 'local_sku_id': row.local_sku_id,
        'local_invoice_id': row.local_invoice_id, 'local_customer_order_id': row.local_customer_order_id,
        'created_at': row.created_at} for row in rows]


def record_page(db, *, source=None, tenant=None, object_type=None, role=None, page=1, page_size=20):
    query = select(MigrationRecord)
    for column, value in ((MigrationRecord.source, source), (MigrationRecord.tenant, tenant),
                          (MigrationRecord.object_type, object_type), (MigrationRecord.role, role)):
        if value is not None:
            query = query.where(column == value)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(MigrationRecord.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    keys = ('id', 'batch_key', 'source', 'tenant', 'object_type', 'external_id', 'role',
            'local_sku_id', 'local_invoice_id', 'local_customer_order_id', 'created_at')
    from app.invoice.models import Invoice
    from app.stock.models import ProductionOrder
    invoice_ids = [row.local_invoice_id for row in rows if row.local_invoice_id]
    production_ids = [row.snapshot.get('_local_order_id') for row in rows if row.object_type == 'production_opening']
    invoices = dict(db.execute(select(Invoice.id, Invoice.commerce_status).where(Invoice.id.in_(invoice_ids))).all())
    productions = dict(db.execute(select(ProductionOrder.id, ProductionOrder.transaction_mode).where(ProductionOrder.id.in_(production_ids))).all())
    items = []
    for row in rows:
        state = invoices.get(row.local_invoice_id) if row.object_type == 'order_binding' else (
            productions.get(row.snapshot.get('_local_order_id')) if row.object_type == 'production_opening' else None)
        items.append(dict({key: getattr(row, key) for key in keys}, current_state=state))
    return dict(items=items, total=total)


def describe_record(db, record_id):
    row = db.get(MigrationRecord, record_id)
    if row is None:
        raise HTTPException(404, '核验来源记录不存在')
    records = list_records(db, after_id=row.id - 1, limit=1)
    return dict(record=records[0], batch=describe_batch(db, row.batch_key))
