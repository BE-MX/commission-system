"""Enable ordinary writers only after all original closing responsibilities match.

The existing invoice event journals the cutover. Future cash, shipments and
factory acceptance remain ordinary domain operations on the same identities.
"""
from decimal import Decimal
from sqlalchemy import select
from app.auth.models import ArkUser
from app.commerce_migration.models import MigrationBatch, MigrationRecord
from app.commerce_migration.service import _current, digest
from app.commerce_migration.finance_service import _query, _shared
from app.finance import service as finance
from app.finance.models import FinanceEvent
from app.invoice.models import Invoice, InvoiceItem, InvoiceCommerceEvent
from app.invoice.settlement_models import Receivable, ShipmentSettlement, ShipmentOutbound, SettlementApplication
from app.inventory.models import StockReservation, StockBalance
from app.inventory.service import _lock_warehouses
from app.inventory.reservation_service import reserve_line
from app.production.local_models import ProductionSupply
from app.stock.models import ProductionOrder, ProductionOrderItem
from app.semifinished.models import InvoiceAllocation

ZERO = Decimal('0')


def _request_key(body):
    key = f'opening-activate:{body.request_key}'
    return key if len(key) <= 64 else 'opening-activate:' + digest(body.request_key)[:47]


def prepare(db, selection):
    """Infer current versions from selected reviewed responsibilities, read-only."""
    from app.commerce_migration.activation_schemas import ActivationManifest
    records = _query(db, select(MigrationRecord).where(MigrationRecord.id.in_(selection.record_ids)).order_by(MigrationRecord.id), False)
    if len(records) != len(selection.record_ids) or any(row.role != 'opening' or row.object_type not in {
            'order_binding', 'production_opening'} for row in records):
        raise ValueError('仅可选择已承接的完整订单或生产责任进行放行核验')
    dates, orders, productions, descriptions = set(), [], [], []
    for record in records:
        batch = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == record.batch_key), False)
        if batch is None:
            raise ValueError('来源记录缺少核验批次')
        dates.add(batch.cutover_date)
        if record.object_type == 'order_binding':
            invoice = _current(db, select(Invoice).where(Invoice.id == record.local_invoice_id), False)
            if invoice is None or invoice.commerce_status != 'opening':
                raise ValueError('所选订单不存在或已经放行，请刷新记录')
            orders.append(dict(order_binding_record_id=record.id, expected_version=invoice.commerce_version))
            descriptions.append(dict(record_id=record.id, name=invoice.invoice_no, kind='order',
                target_id=invoice.id, source_status=record.snapshot['commerce_status']))
        else:
            order = _current(db, select(ProductionOrder).where(ProductionOrder.id == record.snapshot.get('_local_order_id')), False)
            if order is None or order.transaction_mode != 'opening':
                raise ValueError('所选生产不存在或已经放行，请刷新记录')
            items = _query(db, select(ProductionOrderItem).where(ProductionOrderItem.order_id == order.id).order_by(ProductionOrderItem.id), False)
            productions.append(dict(production_opening_record_id=record.id,
                items=[dict(production_item_id=row.id, expected_version=row.local_version) for row in items]))
            descriptions.append(dict(record_id=record.id, name=order.order_no, kind='production', target_id=order.id, source_status='local'))
    if len(dates) != 1:
        raise ValueError('联合放行须为同一切换日的责任')
    command = ActivationManifest(request_key=selection.request_key, business_date=next(iter(dates)), orders=orders, productions=productions)
    from app.commerce_migration import handover_service as handover
    from app.commerce_transition.service import policy
    if policy(db).phase == 'transition':
        preparation = handover.activation_preparation(db, command, lock=False)
        if preparation is not None:
            command = command.model_copy(update={'handover_preparation_id': preparation.id,
                'expected_authority_epochs': {int(k): v for k, v in preparation.manifest['epochs'].items()}})
    return dict(command=command.model_dump(mode='json'), descriptions=descriptions, report=preview(db, command))


def _load(db, command, date, lock):
    proof = _current(db, select(MigrationRecord).where(MigrationRecord.id == command.order_binding_record_id), lock)
    if proof is None or proof.role != 'opening' or proof.object_type != 'order_binding' or proof.local_invoice_id is None:
        raise ValueError('启用须关联已核验完整原订单')
    batch = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == proof.batch_key), lock)
    invoice = _current(db, select(Invoice).where(Invoice.id == proof.local_invoice_id), lock)
    from app.commerce_migration.handover_service import staged_invoice
    if batch is None or batch.cutover_date != date or not staged_invoice(db, invoice):
        raise ValueError('启用日、本地主账或核验批次不一致')
    if invoice.commerce_status != 'opening' or invoice.commerce_version != command.expected_version:
        raise ValueError('原订单启用状态或版本已变化，请刷新核验')
    mapping = next((row for row in batch.result.get('orders', []) if row['record_id'] == proof.id), None)
    if mapping is None or mapping['invoice_id'] != invoice.id or mapping['customer_order_id'] != proof.local_customer_order_id:
        raise ValueError('整单承接结果关联缺失')
    return proof, invoice, mapping


def _cash(db, proof, invoice, mapping, lock):
    targets = _query(db, select(Receivable).where(Receivable.invoice_id == invoice.id).order_by(Receivable.id), lock)
    by_id = {row.id: row for row in targets}
    if set(by_id) != {row['receivable_id'] for row in mapping['receivables']}:
        raise ValueError('整单原应收身份不完整，不能启用')
    by_source = {row['external_id']: by_id[row['receivable_id']] for row in mapping['receivables']}
    events = _query(db, select(FinanceEvent).where(FinanceEvent.receivable_id.in_(by_id)), lock)
    for source in proof.snapshot['receivables']:
        target = by_source[source['external_id']]
        adjusted = sum((Decimal(a['amount']) for a in source['adjustments']), ZERO)
        if (target.amount != Decimal(source['amount']) or target.adjustment_amount != adjusted
                or target.paid_amount != Decimal(source['paid_amount'])
                or target.currency != invoice.currency or target.attempt_token or target.lease_until):
            raise ValueError('原应收、贷项或已收期末责任尚未完整核验')
        paid = sum((e.amount for e in events if e.receivable_id == target.id and e.action == 'opening_allocation'), ZERO)
        credits = sum((e.amount for e in events if e.receivable_id == target.id and e.action == 'opening_adjustment'), ZERO)
        if paid != target.paid_amount or credits != target.adjustment_amount:
            raise ValueError('期初资金与原应收调整缺少完整不可变事件')
    if (invoice.internal_received != Decimal(proof.snapshot['source_received_amount'])
            or invoice.internal_balance != Decimal(proof.snapshot['source_balance_amount'])):
        raise ValueError('整单期末已收及剩余余额尚未完整承接')


def _shipments(db, proof, invoice, lock):
    source_ids = set(proof.snapshot['historical_shipment_ids'])
    record = _current(db, select(MigrationRecord).where(MigrationRecord.source == proof.source, MigrationRecord.tenant == proof.tenant,
        MigrationRecord.role == 'opening', MigrationRecord.object_type == 'shipment_opening', MigrationRecord.external_id == str(proof.id)), lock)
    if source_ids:
        if record is None or {row['source_settlement_id'] for row in record.snapshot['shipments']} != source_ids:
            raise ValueError('全部原已发货及已消费资金责任尚未承接')
        batch = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == record.batch_key), lock)
        mapping = next((row for row in batch.result['orders'] if row['record_id'] == record.id), None)
        if mapping is None or mapping['invoice_id'] != invoice.id:
            raise ValueError('原履约承接结果关联缺失')
        ids = {row['settlement_id'] for row in mapping['shipments']}
    else:
        ids = set()
    shipments = _query(db, select(ShipmentSettlement).where(ShipmentSettlement.invoice_id == invoice.id), lock)
    if {row.id for row in shipments if row.state == 'shipped'} != ids or any(row.state not in {'shipped', 'cancelled'} for row in shipments):
        raise ValueError('仍有未接管或未决发货批次，不能启用')
    outbounds = _query(db, select(ShipmentOutbound).where(ShipmentOutbound.settlement_id.in_(ids)), lock)
    if (len(outbounds) != len(ids) or any(row.status != 'local_shipped' or row.attempt_token or row.lease_until
            or row.payload.get('transaction_mode') != 'local' for row in outbounds)):
        raise ValueError('全部原出库须已核验本地状态及原始身份')


def _materials(db, proof, invoice, lock):
    rows = _query(db, select(InvoiceAllocation).where(InvoiceAllocation.invoice_id == invoice.id), lock)
    if {row.id for row in rows} != set(proof.snapshot['material_allocation_ids']):
        raise ValueError('原半成品扣量责任清单不完整')
    for row in rows:
        record = _current(db, select(MigrationRecord).where(MigrationRecord.source == proof.source, MigrationRecord.tenant == proof.tenant,
            MigrationRecord.role == 'opening', MigrationRecord.object_type == 'material_allocation', MigrationRecord.external_id == str(row.id)), lock)
        if (record is None or row.status != 'allocated' or row.pending_delta_grams or row.operation_key or row.pending_at
                or Decimal(record.snapshot['allocated_qty_grams']) != row.allocated_qty_grams):
            raise ValueError('原半成品已扣量或pending远端结果尚未核验')


def _production(db, loaded, body, lock):
    scope = {invoice.id for _, invoice, _ in loaded}
    orders = {}
    for command in body.productions:
        record = _current(db, select(MigrationRecord).where(MigrationRecord.id == command.production_opening_record_id), lock)
        if record is None or record.role != 'opening' or record.object_type != 'production_opening' or '_local_order_id' not in record.snapshot:
            raise ValueError('备货生产启用缺少完整已核验生产关联')
        batch = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == record.batch_key), lock)
        order = _current(db, select(ProductionOrder).where(ProductionOrder.id == record.snapshot['_local_order_id']), lock)
        if batch is None or batch.cutover_date != body.business_date or order is None or order.transaction_mode != 'opening' or order.deleted_flag:
            raise ValueError('备货生产启用日或当前状态不一致')
        if lock:
            from app.commerce_transition.service import require_resource_scope
            require_resource_scope(db, 'local', 'production', str(order.id), '*')
        else:
            from app.commerce_transition.models import ResourceScope
            resource = _current(db, select(ResourceScope).where(ResourceScope.resource_kind == 'production',
                ResourceScope.resource_key == str(order.id), ResourceScope.warehouse_key == '*'), False)
            if resource is None or resource.route != 'local' or resource.state != 'active':
                raise ValueError('原生产资源归属未核验或已冻结')
        items = _query(db, select(ProductionOrderItem).where(ProductionOrderItem.order_id == order.id), lock)
        versions = {row.production_item_id: row.expected_version for row in command.items}
        if set(versions) != {row.id for row in items} or any(row.local_version != versions[row.id] for row in items):
            raise ValueError('备货生产明细或版本已变化，须完整核验')
        orders[order.id] = order
    for proof, _, _ in loaded:
        for identity in proof.snapshot['production_ids']:
            record = _current(db, select(MigrationRecord).where(MigrationRecord.source == proof.source, MigrationRecord.tenant == proof.tenant,
                MigrationRecord.role == 'opening', MigrationRecord.object_type == 'production_opening', MigrationRecord.external_id == identity), lock)
            if record is None or '_local_order_id' not in record.snapshot:
                raise ValueError('全部原生产与供货责任尚未完整承接')
            order = _current(db, select(ProductionOrder).where(ProductionOrder.id == record.snapshot['_local_order_id']), lock)
            if order is None or order.transaction_mode not in {'opening', 'local'} or order.deleted_flag:
                raise ValueError('原生产主账关联或状态不一致')
            if order.transaction_mode == 'opening':
                orders[order.id] = order
    if orders:
        items = _query(db, select(ProductionOrderItem).where(ProductionOrderItem.order_id.in_(orders)), lock)
        for item in items:
            if item.received_qty:
                closings = _query(db, select(MigrationRecord).where(MigrationRecord.role == 'opening', MigrationRecord.object_type == 'stock_balance',
                    MigrationRecord.local_sku_id == item.local_sku_id), lock)
                batches = [_current(db, select(MigrationBatch).where(MigrationBatch.batch_key == record.batch_key), lock) for record in closings]
                if not any(batch and batch.cutover_date == body.business_date for batch in batches):
                    raise ValueError('原生产已入库商品须先核验同日物理库存期初')
        supplies = _query(db, select(ProductionSupply).where(ProductionSupply.production_item_id.in_([row.id for row in items])), lock)
        line_ids = {row.invoice_item_id for row in supplies}
        lines = _query(db, select(InvoiceItem).where(InvoiceItem.id.in_(line_ids)), lock)
        for identity in sorted({row.invoice_id for row in lines} - scope):
            invoice = _current(db, select(Invoice).where(Invoice.id == identity), lock)
            if invoice is None or invoice.transaction_mode != 'local' or invoice.commerce_status == 'opening':
                raise ValueError('同一生产单供货的原订单须共同完成承接后启用')
    return list(orders.values())


def _lines(db, proof, invoice, mapping, date, lock):
    lines = _query(db, select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id), lock)
    by_id = {row.id: row for row in lines}
    if set(by_id) != {row['invoice_item_id'] for row in mapping['items']}:
        raise ValueError('全部原合同商品关联已变化')
    by_source = {row['source_item_id']: by_id[row['invoice_item_id']] for row in mapping['items']}
    for source in proof.snapshot['items']:
        line = by_source[source['source_item_id']]
        if (line.quantity != source['quantity'] or line.local_sku_id != source['local_sku_id']
                or line.stock_shipped_quantity != source['shipped_quantity']
                or line.production_pending_quantity != source['production_pending_quantity'] or line.stock_reserved_quantity):
            raise ValueError('原合同、已发、在产或预占期末责任尚未完整承接')
        existing = _query(db, select(StockReservation).where(StockReservation.invoice_item_id == line.id), lock)
        if sum(row.shipped for row in existing) != line.stock_shipped_quantity or any(row.reserved for row in existing):
            raise ValueError('原跨仓已发或当前预占责任不一致')
        for reservation in source['reservations']:
            record = _current(db, select(MigrationRecord).where(MigrationRecord.role == 'opening', MigrationRecord.object_type == 'stock_balance',
                MigrationRecord.local_sku_id == line.local_sku_id,
                MigrationRecord.snapshot['warehouse_id'].as_integer() == reservation['warehouse_id'],
                MigrationRecord.snapshot['quality'].as_string() == 'sellable'), lock)
            batch = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == record.batch_key), lock) if record else None
            bucket = _current(db, select(StockBalance).where(StockBalance.warehouse_id == reservation['warehouse_id'],
                StockBalance.sku_id == line.local_sku_id, StockBalance.quality == 'sellable'), lock)
            if batch is None or batch.cutover_date != date or bucket is None or bucket.on_hand - bucket.reserved < reservation['quantity']:
                raise ValueError('原待发预占缺少同日库存期初或当前可售量不足')
    return by_source


def _check(db, body, lock):
    if lock:
        # Opening production is immutable to normal writers. Its reviewed
        # supply links identify every related invoice before parent locks.
        proofs = [_current(db, select(MigrationRecord).where(MigrationRecord.id == row.order_binding_record_id), True) for row in body.orders]
        identities = {p.local_invoice_id for p in proofs if p and p.local_invoice_id}
        production_proofs = [_current(db, select(MigrationRecord).where(MigrationRecord.id == row.production_opening_record_id), True) for row in body.productions]
        for proof in [p for p in proofs if p and p.object_type == 'order_binding']:
            for external_id in proof.snapshot['production_ids']:
                production = _current(db, select(MigrationRecord).where(MigrationRecord.source == proof.source, MigrationRecord.tenant == proof.tenant,
                    MigrationRecord.object_type == 'production_opening', MigrationRecord.role == 'opening', MigrationRecord.external_id == external_id), True)
                if production:
                    production_proofs.append(production)
        for production in [p for p in production_proofs if p and p.object_type == 'production_opening']:
            for item in production.snapshot['items']:
                for supply in item['supplies']:
                    related = _current(db, select(MigrationRecord).where(MigrationRecord.id == supply['order_binding_record_id']), True)
                    if related and related.local_invoice_id:
                        identities.add(related.local_invoice_id)
        for identity in sorted(identities):
            finance.lock(db, Invoice, identity)
    loaded = [_load(db, row, body.business_date, lock) for row in body.orders]
    productions = _production(db, loaded, body, lock)
    if lock:
        _lock_warehouses(db, [r['warehouse_id'] for p, _, _ in loaded for i in p.snapshot['items'] for r in i['reservations']])
    prepared = []
    for proof, invoice, mapping in loaded:
        _cash(db, proof, invoice, mapping, lock)
        _shipments(db, proof, invoice, lock)
        _materials(db, proof, invoice, lock)
        prepared.append((proof, invoice, _lines(db, proof, invoice, mapping, body.business_date, lock)))
    demand = {}
    for proof, _, lines in prepared:
        for source in proof.snapshot['items']:
            for reservation in source['reservations']:
                key = (reservation['warehouse_id'], lines[source['source_item_id']].local_sku_id)
                demand[key] = demand.get(key, 0) + reservation['quantity']
    for (warehouse_id, sku_id), amount in sorted(demand.items()):
        bucket = _current(db, select(StockBalance).where(StockBalance.warehouse_id == warehouse_id,
            StockBalance.sku_id == sku_id, StockBalance.quality == 'sellable'), lock)
        if bucket is None or bucket.on_hand - bucket.reserved < amount:
            raise ValueError('跨订单累计待发预占超过当前可售量')
    return prepared, productions


def preview(db, body):
    try:
        from app.commerce_transition import service as gates
        if gates.policy(db).phase == 'transition':
            from app.commerce_migration.handover_service import activation_preparation, pending_original_requests
            preparation = activation_preparation(db, body, lock=False)
            if preparation is not None:
                epochs = {int(k): v for k, v in preparation.manifest['epochs'].items()}
                if body.handover_preparation_id != preparation.id or body.expected_authority_epochs != epochs:
                    raise ValueError('移交准备身份或原办理权epoch不一致')
                if pending_original_requests(db, preparation.manifest['invoice_ids']):
                    raise ValueError('原在途或unknown尚未核清，不能放行')
        _check(db, body, False)
        return dict(can_activate=True, conflicts=[])
    except ValueError as exc:
        return dict(can_activate=False, conflicts=[dict(code='responsibility_incomplete', message=str(exc))])


def _activate_opening(db, body, user, *, preparation=None):
    with db.begin_nested():
        ledger = finance.book(db)
        actor_id = int(user['sub'])
        actor = _shared(db, select(ArkUser).where(ArkUser.id == actor_id), True)
        if actor is None or not actor.is_active or actor.deleted_at:
            raise ValueError('启用账号不可用')
        request_hash = digest({'body': body.model_dump(mode='json'), 'actor_id': actor_id})
        key = _request_key(body)
        prior = _current(db, select(InvoiceCommerceEvent).where(InvoiceCommerceEvent.request_key == key), True)
        if prior:
            if prior.request_hash != request_hash or prior.action != 'opening_activate':
                raise ValueError('启用请求身份已用于不同内容')
            return prior.payload['result']
        finance.open_date(ledger, body.business_date)
        prepared, productions = _check(db, body, True)
        result = dict(request_key=body.request_key, invoices=[], production_order_ids=[row.id for row in productions])
        for proof, invoice, lines in prepared:
            invoice.commerce_status = proof.snapshot['commerce_status']
            if preparation is None:
                from app.commerce_transition.service import ensure_authority
                ensure_authority(db, invoice, route='local', confirmed=True,
                    source_evidence={'opening_record_id': proof.id, 'source_hash': proof.content_hash})
            for source in proof.snapshot['items']:
                for reservation in source['reservations']:
                    if preparation is not None:
                        from app.commerce_migration.handover_service import reserve_opening_line
                        reserve_opening_line(db, proof, lines[source['source_item_id']], reservation['warehouse_id'],
                                             reservation['quantity'], actor_id, preparation)
                    else:
                        reserve_line(db, lines[source['source_item_id']].id, reservation['warehouse_id'], reservation['quantity'],
                            f'opening-reserve:{proof.id}:{lines[source["source_item_id"]].id}:{reservation["warehouse_id"]}', actor_id)
            invoice.transaction_mode = 'local'
            invoice.commerce_version += 1
            invoice.updated_by = actor_id
            result['invoices'].append(dict(order_binding_record_id=proof.id, invoice_id=invoice.id,
                commerce_status=invoice.commerce_status, commerce_version=invoice.commerce_version))
        for order in productions:
            order.transaction_mode = 'local'
        from app.commerce_migration.handover_service import finish_bank_openings
        finish_bank_openings(db, [invoice.id for _, invoice, _ in prepared], preparation.id if preparation else None)
        db.flush()
        from app.trade.snapshot_service import build_snapshot
        for proof, invoice, _ in prepared:
            snapshot = build_snapshot(db, invoice.id)
            if (snapshot is None or Decimal(snapshot['amount_original']) != Decimal(proof.snapshot['business_amount_original'])
                    or Decimal(snapshot['amount_usd']) != Decimal(proof.snapshot['business_amount_usd'])):
                raise ValueError('原经营金额承接不一致，不能启用')
        db.add(InvoiceCommerceEvent(invoice_id=prepared[0][1].id if prepared else None, request_key=key, request_hash=request_hash,
            action='opening_activate', created_by=actor_id, payload={'body': body.model_dump(mode='json'), 'result': result}))
        db.flush()
        return result


def activate(db, body, user):
    from app.commerce_migration import handover_service as handover
    from app.commerce_transition import transfer_service
    current = handover.opening_policy(db)
    # Replaying an already completed command verifies its exact request hash in
    # the original activation journal; no old responsibility is applied again.
    prior = db.scalar(select(InvoiceCommerceEvent.id).where(
        InvoiceCommerceEvent.request_key == _request_key(body)).with_for_update())
    if current.phase != 'transition' or prior:
        return _activate_opening(db, body, user)
    with db.begin_nested():
        preparation = handover.activation_preparation(db, body)
        if preparation is None:
            if body.handover_preparation_id is not None or body.expected_authority_epochs:
                raise ValueError('独立备货不得拼接不存在的订单办理权')
            result = _activate_opening(db, body, user)
            current.local_ever_effective = True
            return result
        epochs = {int(k): v for k, v in preparation.manifest['epochs'].items()}
        if body.handover_preparation_id != preparation.id or body.expected_authority_epochs != epochs:
            raise ValueError('移交准备身份或原办理权epoch不一致，请重新核对完整闭包')
        if handover.pending_original_requests(db, preparation.manifest['invoice_ids']):
            raise ValueError('原在途或unknown尚未核清，不能放行')
        prepared, productions = _check(db, body, True)
        verification = handover.verification_receipt(db, prepared, productions)
        def apply_opening(session, frozen, checked):
            result = _activate_opening(session, body, user, preparation=frozen)
            event = session.scalar(select(InvoiceCommerceEvent).where(
                InvoiceCommerceEvent.request_key == _request_key(body)))
            return {'invoice_commerce_event_id': event.id, 'manifest_hash': digest(body.model_dump(mode='json')),
                    'result': result}
        completed = transfer_service.complete_transfer(db, preparation.id,
            verification=verification, apply_opening=apply_opening)
        return completed.verification['opening_receipt']['result']
