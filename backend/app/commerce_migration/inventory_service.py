"""Initialize empty ledgers or acknowledge existing facts without replay.

Importers take book -> actor -> warehouses -> catalog -> materials, the normal
inventory lock order after book. A durable source record also owns each target
opening, including zero balances. Caller commits; a batch is savepoint atomic.
"""
from sqlalchemy import select
from app.auth.models import ArkUser
from app.catalog.models import CatalogSku
from app.commerce_migration.models import MigrationBatch, MigrationRecord
from app.commerce_migration.service import _current, _record, _assert_record, digest
from app.finance import service as finance
from app.inventory import service as stock
from app.inventory.models import StockBalance, StockDocument, StockLedger, StockReservation, Warehouse
from app.semifinished.models import InventoryBalance, InventoryLedger, SemifinishedMaterial


def _entries(body):
    for index, row in enumerate(body.stocks):
        yield 'stocks', index, 'stock_balance', row, row.model_dump(mode='json')
    for index, row in enumerate(body.materials):
        yield 'materials', index, 'material_balance', row, row.model_dump(mode='json')


def _target_record(db, kind, row, lock):
    query = select(MigrationRecord).where(MigrationRecord.role == 'opening', MigrationRecord.object_type == kind)
    if kind == 'stock_balance':
        query = query.where(MigrationRecord.local_sku_id == row.local_sku_id,
            MigrationRecord.snapshot['warehouse_id'].as_integer() == row.warehouse_id,
            MigrationRecord.snapshot['quality'].as_string() == row.quality)
    else:
        query = query.where(MigrationRecord.snapshot['material_id'].as_integer() == row.material_id)
    return _current(db, query, lock)


def _check_target(db, kind, row, lock):
    if _target_record(db, kind, row, lock) is not None:
        raise ValueError('该目标余额已登记期初来源，不允许换来源再次承接')
    if kind == 'stock_balance':
        warehouse = db.get(Warehouse, row.warehouse_id)
        sku = db.get(CatalogSku, row.local_sku_id)
        if warehouse is None or sku is None or sku.unit != 'piece':
            raise ValueError('仓库或件数SKU不存在')
        if row.mode == 'initialize' and (not warehouse.active or not sku.active):
            raise ValueError('新期初仓库或SKU已停用')
        bucket = _current(db, select(StockBalance).where(StockBalance.warehouse_id == row.warehouse_id,
            StockBalance.sku_id == row.local_sku_id, StockBalance.quality == row.quality), lock)
        statement = select(StockLedger).where(StockLedger.warehouse_id == row.warehouse_id,
            StockLedger.sku_id == row.local_sku_id, StockLedger.quality == row.quality)
        statement = statement.order_by(StockLedger.id)
        # Immutable history needs no range lock. The current locked balance
        # version proves the RR snapshot contains every movement; stale views
        # fail closed instead of taking an empty gap before a first insertion.
        ledgers = db.scalars(statement).all()
        if row.mode == 'initialize':
            if ledgers or (bucket and (bucket.on_hand or bucket.reserved or bucket.version)):
                raise ValueError('该库存已有事实，须核对现有账而非重复写入期初')
        elif (bucket is None or (bucket.on_hand, bucket.reserved) != (row.on_hand, row.reserved)
              or sum(r.on_hand_delta for r in ledgers) != row.on_hand
              or sum(r.reserved_delta for r in ledgers) != row.reserved):
            raise ValueError('库存核验数量、余额与流水不一致')
        elif bucket.version != len(ledgers):
            raise ValueError('库存快照已过期或流水版本不一致，请结束当前事务后重新核验')
        if row.reserved:
            reservations = select(StockReservation).where(StockReservation.warehouse_id == row.warehouse_id,
                StockReservation.sku_id == row.local_sku_id)
            if lock:
                reservations = reservations.with_for_update().execution_options(populate_existing=True)
            reserved = sum(r.reserved for r in db.scalars(reservations))
            if reserved != row.reserved:
                raise ValueError('库存预占缺少完整销售责任关联')
    else:
        master_query = select(SemifinishedMaterial).where(SemifinishedMaterial.id == row.material_id)
        if lock:
            master_query = master_query.with_for_update(read=True).execution_options(populate_existing=True)
        master = db.scalar(master_query)
        balance = _current(db, select(InventoryBalance).where(InventoryBalance.material_id == row.material_id), lock)
        if master is None or balance is None:
            raise ValueError('物料或库存余额不存在，请先完成主数据映射')
        statement = select(InventoryLedger).where(InventoryLedger.material_id == row.material_id).order_by(InventoryLedger.id)
        ledgers = db.scalars(statement).all()
        if row.mode == 'initialize':
            if master.status != 'active' or ledgers or balance.on_hand_grams or balance.reserved_grams or balance.version:
                raise ValueError('物料已停用或已有库存事实，禁止重复扣加期初')
        elif ((balance.on_hand_grams, balance.reserved_grams) != (row.on_hand_grams, row.reserved_grams)
              or sum((r.quantity_grams for r in ledgers if r.movement_type not in {'reserve', 'release'}), 0) != row.on_hand_grams
              or (ledgers and ledgers[-1].reserved_after != row.reserved_grams)
              or (not ledgers and row.reserved_grams)):
            raise ValueError('物料核验数量、余额与流水不一致，历史已领量不能再扣')
        elif balance.version != len(ledgers):
            raise ValueError('物料快照已过期或流水版本不一致，请结束当前事务后重新核验')


def preview(db, body, *, lock=False):
    conflicts = []
    batch = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == body.batch_key), lock)
    if batch and batch.manifest_hash != digest(body.model_dump(mode='json')):
        conflicts.append(dict(section='batch', record_index=None, code='batch_content_changed', message='批次身份已用于不同内容'))
    for section, index, kind, row, snapshot in _entries(body):
        try:
            existing = _record(db, body, kind, row.external_id, lock)
            if existing:
                _assert_record(existing, body, 'opening', kind, row.external_id, snapshot)
            else:
                _check_target(db, kind, row, lock)
        except ValueError as exc:
            conflicts.append(dict(section=section, record_index=index, code='opening_conflict', message=str(exc)))
    return dict(manifest_hash=digest(body.model_dump(mode='json')), can_apply=not conflicts,
                stock_count=len(body.stocks), material_count=len(body.materials), conflicts=conflicts)


def apply_manifest(db, body, user):
    from app.commerce_migration.handover_service import opening_policy, register_opening_resources
    opening_policy(db, body)
    with db.begin_nested():
        ledger = finance.book(db)
        actor_id = int(user['sub'])
        actor = db.scalar(select(ArkUser).where(ArkUser.id == actor_id)
            .with_for_update(read=True).execution_options(populate_existing=True))
        if actor is None or not actor.is_active or actor.deleted_at is not None:
            raise ValueError('导入账号不可用')
        previous = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == body.batch_key), True)
        manifest_hash = digest(body.model_dump(mode='json'))
        if previous:
            if previous.manifest_hash != manifest_hash:
                raise ValueError('批次身份已用于不同内容')
            return previous.result
        finance.open_date(ledger, body.cutover_date)
        stock._lock_warehouses(db, [row.warehouse_id for row in body.stocks], allow_inactive=True)
        # Lock current masters in normal stock order before bucket range reads.
        fresh_stocks = [row for row in body.stocks if _record(db, body, 'stock_balance', row.external_id, True) is None]
        stock._validate_skus(db, [row.local_sku_id for row in fresh_stocks if row.mode == 'initialize'])
        for material_id in sorted({row.material_id for row in body.materials}):
            db.scalar(select(SemifinishedMaterial).where(SemifinishedMaterial.id == material_id)
                .with_for_update(read=True).execution_options(populate_existing=True))
        report = preview(db, body, lock=True)
        if not report['can_apply']:
            raise ValueError(f'期初清单存在{len(report["conflicts"])}项冲突，请先核对预览')
        register_opening_resources(db, body)
        batch = MigrationBatch(batch_key=body.batch_key, source=body.source, tenant=body.tenant,
            manifest_hash=manifest_hash, evidence_sha256=body.evidence_sha256,
            review_reference=body.review_reference, cutover_date=body.cutover_date, result={}, created_by=actor_id)
        db.add(batch); db.flush()
        result = dict(batch_key=body.batch_key, manifest_hash=manifest_hash, stocks=[], materials=[])
        for section, index, kind, row, snapshot in _entries(body):
            record = _record(db, body, kind, row.external_id, True)
            if record:
                _assert_record(record, body, 'opening', kind, row.external_id, snapshot)
            else:
                _check_target(db, kind, row, True)
                record = MigrationRecord(batch_key=body.batch_key, source=body.source, tenant=body.tenant,
                    object_type=kind, external_id=row.external_id, role='opening', content_hash=digest(snapshot),
                    snapshot=snapshot, local_sku_id=row.local_sku_id if kind == 'stock_balance' else None)
                db.add(record); db.flush()
                if row.mode == 'initialize':
                    if kind == 'stock_balance':
                        document, fresh = stock._claim_document(db, f'migration-stock:{record.id}',
                            dict(record_id=record.id, cutover_date=body.cutover_date.isoformat(), opening=snapshot),
                            kind='opening', reason=body.review_reference, source_type='commerce_opening', source_id=str(record.id), created_by=actor_id)
                        if not fresh:
                            raise ValueError('期初单据身份已被占用')
                        bucket = stock._bucket(db, row.warehouse_id, row.local_sku_id, row.quality)
                        stock._move(db, document, 1, bucket, row.on_hand)
                    else:
                        balance = _current(db, select(InventoryBalance).where(InventoryBalance.material_id == row.material_id), True)
                        balance.on_hand_grams, balance.version = row.on_hand_grams, balance.version + 1
                        db.add(InventoryLedger(material_id=row.material_id, movement_type='inbound', quantity_grams=row.on_hand_grams,
                            on_hand_after=row.on_hand_grams, reserved_after=0, business_type='commerce_opening', business_id=record.id,
                            idempotency_key=f'migration-material:{record.id}', created_by=actor_id, remark=body.review_reference))
                        db.flush()
            result[section].append(dict(record_id=record.id, mode=row.mode, external_id=row.external_id))
        batch.result = result
        db.flush()
        return result
