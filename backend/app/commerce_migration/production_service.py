"""Adopt factory counters and verified supplied/issued responsibilities once.

Historical acceptance is already part of the warehouse opening. Historical
material issues are already absent from its closing stock. Neither is replayed.
"""
from decimal import Decimal
from sqlalchemy import select
from app.auth.models import ArkUser
from app.catalog.models import CatalogSku
from app.commerce_migration.models import MigrationBatch, MigrationRecord
from app.commerce_migration.service import _current, _record, _assert_record, digest
from app.commerce_migration.finance_service import _query, _shared
from app.finance import service as finance
from app.invoice.models import Invoice, InvoiceItem
from app.production.models import Process, ProcessRoute, ProcessRouteStep, OrderProductProcessProgress
from app.production.local_models import ProductionEvent, ProductionSupply, ProductionMaterial
from app.stock.models import ProductionOrder, ProductionOrderItem
from app.semifinished.models import SemifinishedMaterial


def _line(db, body, production, supply, lock):
    proof = _current(db, select(MigrationRecord).where(MigrationRecord.id == supply.order_binding_record_id), lock)
    if (proof is None or proof.role != 'opening' or proof.object_type != 'order_binding'
            or (proof.source, proof.tenant) != (body.source, body.tenant) or proof.local_invoice_id is None
            or production.source_production_id not in proof.snapshot['production_ids']):
        raise ValueError('原供货缺少同来源整单与生产责任关联')
    invoice = _current(db, select(Invoice).where(Invoice.id == proof.local_invoice_id), lock)
    batch = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == proof.batch_key), lock)
    if invoice is None or invoice.commerce_status != 'opening' or batch.cutover_date != body.cutover_date:
        raise ValueError('原供货仅可写入同切换日未激活整单')
    links = proof.snapshot.get('_original_links', {}).get('items', [])
    index = next((i for i, item in enumerate(proof.snapshot['items']) if item['source_item_id'] == supply.source_item_id), None)
    if index is None or index >= len(links):
        raise ValueError('原供货商品未完整关联原销售行')
    line = _current(db, select(InvoiceItem).where(InvoiceItem.id == links[index]['invoice_item_id']), lock)
    if line is None or line.invoice_id != invoice.id:
        raise ValueError('原供货销售行身份不一致')
    return proof, line, proof.snapshot['items'][index]


def _material_proof(db, body, row, item, material, lock):
    proof = _current(db, select(MigrationRecord).where(MigrationRecord.id == material.source_material_record_id), lock)
    expected = dict(source_production_id=row.source_production_id, source_item_id=item.source_item_id, material_id=material.material_id)
    if (proof is None or proof.role != 'archive' or proof.object_type != 'material'
            or (proof.source, proof.tenant) != (body.source, body.tenant)
            or any(proof.snapshot.get(key) != value for key, value in expected.items())):
        raise ValueError('原实际领料缺少同来源不可变核验凭证，不能制造已领材料')
    for key in ('issued_grams', 'returned_grams', 'loss_grams'):
        try:
            amount = Decimal(str(proof.snapshot[key]))
        except (KeyError, ArithmeticError) as exc:
            raise ValueError('原领退料核验凭证缺少完整克数') from exc
        if amount != getattr(material, key):
            raise ValueError('原领退料或已确认损耗与核验凭证不一致')
    master = _shared(db, select(SemifinishedMaterial).where(SemifinishedMaterial.id == material.material_id), lock)
    balance = _current(db, select(MigrationRecord).where(MigrationRecord.role == 'opening', MigrationRecord.object_type == 'material_balance',
        MigrationRecord.snapshot['material_id'].as_integer() == material.material_id), lock)
    opening_batch = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == balance.batch_key), lock) if balance else None
    if master is None or balance is None or opening_batch.cutover_date != body.cutover_date:
        raise ValueError('已领料须先核验同切换日物料期末实存，禁止重复扣料')


def _check(db, body, row, lock):
    order = _current(db, select(ProductionOrder).where(ProductionOrder.id == row.existing_order_id), lock) if row.existing_order_id else None
    same = _query(db, select(ProductionOrder.id).where((ProductionOrder.order_no == row.order_no) | (ProductionOrder.batch_no == row.batch_no)), lock)
    if any(identity != row.existing_order_id for identity in same):
        raise ValueError('原生产单号或批次已存在，须明确复用原生产主账')
    originals = []
    if row.existing_order_id:
        if (order is None or order.transaction_mode != 'legacy' or order.deleted_flag
                or (order.order_no, order.batch_no, order.remark, order.status) != (row.order_no, row.batch_no, row.remark, row.source_status)):
            raise ValueError('原生产主账身份、状态或完整快照不一致')
        originals = _query(db, select(ProductionOrderItem).where(ProductionOrderItem.order_id == order.id), lock)
        if {i.id for i in originals} != {i.existing_item_id for i in row.items}:
            raise ValueError('原生产明细须全部一对一复用，不能只导入未入库部分')
        if _query(db, select(ProductionEvent.id).where(ProductionEvent.order_id == order.id), lock):
            raise ValueError('原生产已存在本地操作事实，不能重建期初')
    elif any(item.existing_item_id for item in row.items):
        raise ValueError('原生产主账不存在时不能拼接其他生产明细')
    for item in row.items:
        catalog = _current(db, select(MigrationRecord).where(MigrationRecord.id == item.catalog_record_id), lock)
        sku = _current(db, select(CatalogSku).where(CatalogSku.id == item.local_sku_id), lock)
        if (catalog is None or catalog.role != 'catalog' or catalog.object_type != 'sku'
                or (catalog.source, catalog.tenant, catalog.local_sku_id) != (body.source, body.tenant, item.local_sku_id)
                or sku is None or sku.unit != 'piece'
                or item.legacy_product_id is not None and catalog.snapshot.get('external_product_id') != str(item.legacy_product_id)):
            raise ValueError('原生产产品缺少同来源已核验本地SKU映射')
        if item.process_route_id and _current(db, select(ProcessRoute).where(ProcessRoute.id == item.process_route_id), lock) is None:
            raise ValueError('原生产路线不存在，不能猜测报工流程')
        original = next((r for r in originals if r.id == item.existing_item_id), None)
        progress = _query(db, select(OrderProductProcessProgress).where(OrderProductProcessProgress.order_product_id == original.id), lock) if original else []
        if {p.id for p in progress} != {p.existing_progress_id for p in item.progress if p.existing_progress_id}:
            raise ValueError('原工序报工须完整复用全部原进度ID及完成证据')
        steps = _query(db, select(ProcessRouteStep).where(ProcessRouteStep.route_id == item.process_route_id), lock) if item.process_route_id else []
        if not original and item.process_route_id and {(p.process_id, p.step_order) for p in item.progress} != {(p.process_id, p.step_order) for p in steps}:
            raise ValueError('原工序须完整核验路线步骤，不能把历史完工重建为待完成')
        for source_progress in item.progress:
            if (_current(db, select(Process).where(Process.id == source_progress.process_id), lock) is None
                    or source_progress.completed_at and source_progress.completed_at.date() > body.cutover_date
                    or source_progress.completed_by_user_id and _shared(db, select(ArkUser).where(ArkUser.id == source_progress.completed_by_user_id), lock) is None):
                raise ValueError('原工序、报工人员或历史完成时间不能核验')
            if source_progress.existing_progress_id:
                old = next(p for p in progress if p.id == source_progress.existing_progress_id)
                expected = source_progress.model_dump(exclude={'existing_progress_id'})
                if old.route_id != item.process_route_id or any(getattr(old, key) != value for key, value in expected.items()):
                    raise ValueError('原工序进度、时间及操作人快照不一致')
        if original:
            expected = dict(product_id=item.legacy_product_id, product_name=item.product_name, model=item.model,
                spec_info=item.spec_info, process_route_id=item.process_route_id, order_qty=item.order_quantity,
                received_qty=item.received_quantity, status=item.source_status, is_urgent=int(item.is_urgent),
                expected_delivery_date=item.expected_delivery_date, remark=item.remark)
            if (any(getattr(original, key) != value for key, value in expected.items())
                    or original.local_sku_id not in {None, item.local_sku_id}
                    or (original.completed_qty and original.completed_qty != item.completed_quantity)
                    or (original.supplied_qty and original.supplied_qty != sum(s.quantity - s.released_quantity for s in item.supplies))
                    or (original.supplied_received_qty and original.supplied_received_qty != sum(s.received_quantity for s in item.supplies))):
                raise ValueError('原生产明细数量、工序或已知本地责任与核验事实不一致')
        supplies = _query(db, select(ProductionSupply).where(ProductionSupply.production_item_id == original.id), lock) if original else []
        materials = _query(db, select(ProductionMaterial).where(ProductionMaterial.production_item_id == original.id), lock) if original else []
        if {s.id for s in supplies} != {s.existing_supply_id for s in item.supplies if s.existing_supply_id}:
            raise ValueError('必须明确复用全部原生产供货身份')
        if {m.id for m in materials} != {m.existing_material_id for m in item.materials if m.existing_material_id}:
            raise ValueError('必须明确复用全部原生产领料身份')
        for supply in item.supplies:
            proof, line, source = _line(db, body, row, supply, lock)
            if line.local_sku_id != item.local_sku_id:
                raise ValueError('原生产供货与原销售SKU不一致')
            if supply.quantity - supply.received_quantity - supply.released_quantity > source['production_pending_quantity']:
                raise ValueError('原生产未交付供货超过原销售在产责任')
            if supply.existing_supply_id:
                existing = next(s for s in supplies if s.id == supply.existing_supply_id)
                if (existing.invoice_item_id != line.id or any(getattr(existing, key) != getattr(supply, key) for key in
                        ('quantity', 'received_quantity', 'released_quantity'))):
                    raise ValueError('原供货销售关联或累计责任不一致')
        for material in item.materials:
            _material_proof(db, body, row, item, material, lock)
            if material.existing_material_id:
                existing = next(m for m in materials if m.id == material.existing_material_id)
                if any(getattr(existing, key) != getattr(material, key) for key in ('material_id', 'issued_grams', 'returned_grams', 'loss_grams')):
                    raise ValueError('原生产领料身份或实际克数不一致')
    return order


def _aggregate_supplies(db, body, lock):
    totals, expected = {}, {}
    for production in body.productions:
        if _record(db, body, 'production_opening', production.source_production_id, lock):
            continue
        for item in production.items:
            for supply in item.supplies:
                proof, line, source = _line(db, body, production, supply, lock)
                totals[line.id] = totals.get(line.id, 0) + supply.quantity - supply.received_quantity - supply.released_quantity
                expected[line.id] = source['production_pending_quantity']
    for identity, amount in totals.items():
        line = _current(db, select(InvoiceItem).where(InvoiceItem.id == identity), lock)
        if line.production_pending_quantity + amount > expected[identity]:
            raise ValueError('跨生产累计未交付供货超过原销售在产责任')


def preview(db, body, *, lock=False):
    conflicts = []
    prior = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == body.batch_key), lock)
    if prior and prior.manifest_hash != digest(body.model_dump(mode='json')):
        conflicts.append(dict(section='batch', record_index=None, code='content_changed', message='批次身份已用于不同内容'))
    for index, row in enumerate(body.productions):
        try:
            record = _record(db, body, 'production_opening', row.source_production_id, lock)
            if record:
                _assert_record(record, body, 'opening', 'production_opening', row.source_production_id, row.model_dump(mode='json'))
            else:
                _check(db, body, row, lock)
        except ValueError as exc:
            conflicts.append(dict(section='productions', record_index=index, code='production_conflict', message=str(exc)))
    try:
        _aggregate_supplies(db, body, lock)
    except ValueError as exc:
        conflicts.append(dict(section='supplies', record_index=None, code='supply_excess', message=str(exc)))
    return dict(manifest_hash=digest(body.model_dump(mode='json')), can_apply=not conflicts, production_count=len(body.productions), conflicts=conflicts)


def _post(db, body, row, record, actor_id):
    order = finance.lock(db, ProductionOrder, row.existing_order_id) if row.existing_order_id else ProductionOrder(
        order_no=row.order_no, batch_no=row.batch_no, remark=row.remark, created_by=actor_id)
    if order.id is None:
        db.add(order); db.flush()
    order.transaction_mode = 'opening'
    record.snapshot = {**record.snapshot, '_local_order_id': order.id}
    from app.commerce_transition.service import register_resource_scope
    register_resource_scope(db, route='local', resource_kind='production', resource_key=str(order.id), warehouse_key='*',
        evidence={'checkpoint': f'{body.cutover_date}:{body.evidence_sha256}',
                  'old_responsibilities_cleared': {'record_id': record.id, 'source_hash': record.content_hash},
                  'writers_enforced': {'review_reference': body.review_reference}})
    result = dict(record_id=record.id, source_production_id=row.source_production_id, production_order_id=order.id, items=[])
    for source in row.items:
        item = finance.lock(db, ProductionOrderItem, source.existing_item_id) if source.existing_item_id else ProductionOrderItem(
            order_id=order.id, product_id=source.legacy_product_id, product_name=source.product_name, model=source.model,
            spec_info=source.spec_info, order_qty=source.order_quantity, received_qty=source.received_quantity,
            process_route_id=source.process_route_id, is_urgent=int(source.is_urgent),
            expected_delivery_date=source.expected_delivery_date, remark=source.remark)
        if item.id is None:
            db.add(item); db.flush()
        item.local_sku_id, item.completed_qty = source.local_sku_id, source.completed_quantity
        item.supplied_qty = sum(s.quantity - s.released_quantity for s in source.supplies)
        item.supplied_received_qty = sum(s.received_quantity for s in source.supplies)
        item.status = 1 if source.terminated else 2 if item.completed_qty == item.order_qty else 0
        item.local_version += 1 if source.existing_item_id else 0
        supplies = []
        for original in source.supplies:
            proof, line, _ = _line(db, body, row, original, True)
            supply = finance.lock(db, ProductionSupply, original.existing_supply_id) if original.existing_supply_id else ProductionSupply(
                production_item_id=item.id, invoice_item_id=line.id, quantity=original.quantity,
                received_quantity=original.received_quantity, released_quantity=original.released_quantity)
            if supply.id is None:
                db.add(supply); db.flush()
            line.production_pending_quantity += supply.quantity - supply.received_quantity - supply.released_quantity
            supplies.append(dict(supply_id=supply.id, invoice_item_id=line.id, order_binding_record_id=proof.id))
        for original in source.materials:
            if original.existing_material_id is None:
                db.add(ProductionMaterial(production_item_id=item.id, **{key: getattr(original, key) for key in
                    ('material_id', 'issued_grams', 'returned_grams', 'loss_grams')}))
        for progress in source.progress:
            if progress.existing_progress_id is None:
                db.add(OrderProductProcessProgress(order_product_id=item.id, route_id=source.process_route_id,
                    **progress.model_dump(exclude={'existing_progress_id'})))
        event = ProductionEvent(request_key=f'opening-production:{record.id}:{item.id}', request_hash=record.content_hash,
            action='opening', order_id=order.id, item_id=item.id, created_by=actor_id,
            payload={'migration_record_id': record.id, 'source_item_id': source.source_item_id,
                'historical_received_quantity': source.received_quantity, 'historical_completed_quantity': source.completed_quantity})
        db.add(event)
        result['items'].append(dict(source_item_id=source.source_item_id, production_item_id=item.id,
            local_version=item.local_version, supplies=supplies))
    from app.production.local_service import _sync_status
    db.flush(); _sync_status(db, order)
    return result


def apply_manifest(db, body, user):
    from app.commerce_migration.handover_service import opening_policy, stage_invoices
    opening_policy(db, body)
    proof_ids = {s.order_binding_record_id for p in body.productions for i in p.items for s in i.supplies}
    proofs = [db.get(MigrationRecord, identity) for identity in proof_ids]
    stage_invoices(db, [p.local_invoice_id for p in proofs if p and p.local_invoice_id], body)
    with db.begin_nested():
        ledger = finance.book(db)
        actor_id = int(user['sub'])
        actor = _shared(db, select(ArkUser).where(ArkUser.id == actor_id), True)
        if actor is None or not actor.is_active or actor.deleted_at:
            raise ValueError('导入账号不可用')
        manifest_hash = digest(body.model_dump(mode='json'))
        prior = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == body.batch_key), True)
        if prior:
            if prior.manifest_hash != manifest_hash:
                raise ValueError('批次身份已用于不同内容')
            return prior.result
        finance.open_date(ledger, body.cutover_date)
        proofs = [_current(db, select(MigrationRecord).where(MigrationRecord.id == s.order_binding_record_id), True)
            for p in body.productions for i in p.items for s in i.supplies]
        for identity in sorted({p.local_invoice_id for p in proofs if p and p.local_invoice_id}):
            finance.lock(db, Invoice, identity)
        for identity in sorted({p.existing_order_id for p in body.productions if p.existing_order_id}):
            finance.lock(db, ProductionOrder, identity)
        for row in body.productions:
            existing = _record(db, body, 'production_opening', row.source_production_id, True)
            if existing:
                _assert_record(existing, body, 'opening', 'production_opening', row.source_production_id, row.model_dump(mode='json'))
            else:
                _check(db, body, row, True)
        _aggregate_supplies(db, body, True)
        batch = MigrationBatch(batch_key=body.batch_key, source=body.source, tenant=body.tenant, manifest_hash=manifest_hash,
            evidence_sha256=body.evidence_sha256, review_reference=body.review_reference, cutover_date=body.cutover_date,
            result={}, created_by=actor_id)
        db.add(batch); db.flush()
        result = dict(batch_key=body.batch_key, manifest_hash=manifest_hash, productions=[])
        for row in body.productions:
            record = _record(db, body, 'production_opening', row.source_production_id, True)
            if record:
                original = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == record.batch_key), True)
                mapping = next((m for m in original.result.get('productions', []) if m['record_id'] == record.id), None) if original else None
                if mapping is None:
                    raise ValueError('原生产承接结果缺少关联，须核验恢复')
            else:
                snapshot = row.model_dump(mode='json')
                record = MigrationRecord(batch_key=body.batch_key, source=body.source, tenant=body.tenant,
                    object_type='production_opening', external_id=row.source_production_id, role='opening',
                    content_hash=digest(snapshot), snapshot=snapshot)
                db.add(record); db.flush()
                mapping = _post(db, body, row, record, actor_id)
            result['productions'].append(mapping)
        batch.result = result
        db.flush()
        return result
