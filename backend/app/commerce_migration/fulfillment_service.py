"""Adopt historical dispatched facts without replaying cash or stock issues."""
from decimal import Decimal
from sqlalchemy import select
from app.auth.models import ArkUser
from app.commerce_migration.models import MigrationBatch, MigrationRecord
from app.commerce_migration.service import _current, _record, _assert_record, digest
from app.commerce_migration.finance_service import _query, _shared
from app.finance import service as finance
from app.finance.models import FinanceEvent
from app.invoice.models import Invoice, InvoiceItem, InvoiceCommerceEvent
from app.invoice.settlement_models import ShipmentSettlement, SettlementItem, SettlementApplication, ShipmentOutbound, Receivable
from app.inventory.models import Warehouse, StockReservation
from app.inventory.service import _lock_warehouses
from app.receipt.models import Receipt
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto, ShippingOperationEvent

ZERO = Decimal('0')
QUOTE_MONEY = ('goods_amount', 'packaging_amount', 'handling_amount', 'freight_amount', 'deposit_applied',
    'deposit_charge_applied', 'goods_payment_due', 'goods_payment_charge', 'new_payment_due')


def _proof(db, body, row, lock):
    proof = _current(db, select(MigrationRecord).where(MigrationRecord.id == row.order_binding_record_id), lock)
    if (proof is None or proof.role != 'opening' or proof.object_type != 'order_binding'
            or (proof.source, proof.tenant) != (body.source, body.tenant) or proof.local_invoice_id is None):
        raise ValueError('历史履约缺少同来源完整订单承接关联')
    batch = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == proof.batch_key), lock)
    invoice = _current(db, select(Invoice).where(Invoice.id == proof.local_invoice_id), lock)
    from app.commerce_migration.handover_service import staged_invoice
    if (not staged_invoice(db, invoice) or invoice.commerce_status != 'opening'
            or batch is None or batch.cutover_date != body.cutover_date):
        raise ValueError('历史履约仅可写入同切换日未激活的整单')
    links = proof.snapshot.get('_original_links', {}).get('items', [])
    mapped = {item['source_item_id']: link['invoice_item_id'] for item, link in zip(proof.snapshot['items'], links, strict=True)}
    lines = {item.id: item for item in _query(db, select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id), lock)}
    if set(lines) != set(mapped.values()):
        raise ValueError('整单原明细关联已改变，禁止承接历史履约')
    return proof, invoice, mapped, lines


def _receipts(db, invoice, row, lock, proof):
    receipts = _query(db, select(Receipt).where(Receipt.invoice_id == invoice.id), lock)
    by_source = {}
    for receipt in receipts:
        if receipt.xiaoman_receipt_id in by_source:
            raise ValueError('原回款身份重复，不能猜测已消费资金')
        by_source[receipt.xiaoman_receipt_id] = receipt
    target_ids = {receipt.receivable_id for receipt in receipts}
    targets = {target.id: target for target in _query(db, select(Receivable).where(Receivable.id.in_(target_ids)), lock)}
    order_batch = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == proof.batch_key), lock)
    order_mapping = next(m for m in order_batch.result['orders'] if m['record_id'] == proof.id)
    ar_ids = {m['external_id']: m['receivable_id'] for m in order_mapping['receivables']}
    original_settlements = {ar_ids[a['external_id']]: a['source_settlement_id'] for a in proof.snapshot['receivables']}
    totals, gross_totals, releases = {}, {}, {}
    for ship in row.shipments:
        for app in ship.applications:
            receipt = by_source.get(app.original_receipt_id)
            target = targets.get(receipt.receivable_id) if receipt else None
            opening = _current(db, select(FinanceEvent).where(FinanceEvent.receipt_id == receipt.id,
                FinanceEvent.action == 'opening_allocation'), lock) if receipt else None
            component = 'freight' if target and target.kind == 'freight' else 'deposit' if receipt and receipt.purpose == 'presale_deposit' else 'goods'
            if (receipt is None or receipt.source != 'local' or target is None or target.invoice_id != invoice.id
                    or opening is None or receipt.currency != invoice.currency or component != app.component
                    or receipt.collection_date > ship.business_date):
                raise ValueError('原发货资金缺少已承接回款或组成、币种、日期不一致')
            if component == 'freight' and original_settlements.get(target.id) != ship.source_settlement_id:
                raise ValueError('原独立运费核销不属于该原发货批次')
            amount, fee = totals.get(receipt.id, (ZERO, ZERO))
            totals[receipt.id] = (amount + app.amount - app.released_amount, fee + app.bank_charge - app.released_bank_charge)
            amount, fee = gross_totals.get(receipt.id, (ZERO, ZERO))
            gross_totals[receipt.id] = (amount + app.amount, fee + app.bank_charge)
            amount, fee = releases.get(receipt.id, (ZERO, ZERO))
            releases[receipt.id] = (amount + app.released_amount, fee + app.released_bank_charge)
    for identity, (amount, fee) in totals.items():
        receipt = next(r for r in receipts if r.id == identity)
        if (fee > receipt.effective_bank_charge or amount > receipt.effective_amount
                or amount - fee > receipt.effective_amount - receipt.effective_bank_charge):
            raise ValueError('全部原发货资金占用超过原核销有效本金或费用')
        gross, gross_fee = gross_totals[identity]
        released, released_fee = releases[identity]
        if (gross > receipt.amount or gross_fee > receipt.bank_charge
                or gross - gross_fee > receipt.amount - receipt.bank_charge
                or released > receipt.reversed_amount or released_fee > receipt.reversed_bank_charge
                or released - released_fee > receipt.reversed_amount - receipt.reversed_bank_charge):
            raise ValueError('原发货总占用或释放缺少原核销及已核验冲回依据')
    return by_source


def _check(db, body, row, lock):
    proof, invoice, mapped, lines = _proof(db, body, row, lock)
    expected = proof.snapshot
    if {ship.source_settlement_id for ship in row.shipments} != set(expected['historical_shipment_ids']):
        raise ValueError('必须完整承接全部原发货批次，不能遗漏已消费资金')
    totals, amounts = {}, {}
    for ship in row.shipments:
        if not invoice.invoice_date <= ship.business_date <= body.cutover_date:
            raise ValueError('原发货日期须在原订单与切换日之间')
        if _current(db, select(Warehouse).where(Warehouse.id == ship.warehouse_id), lock) is None:
            raise ValueError('原发货缺少本地仓库身份关联')
        for item in ship.items:
            if item.source_item_id not in mapped:
                raise ValueError('原发货商品不属于完整原订单')
            totals[item.source_item_id] = totals.get(item.source_item_id, 0) + item.quantity
            amounts[item.source_item_id] = amounts.get(item.source_item_id, ZERO) + item.line_amount
    if any(totals.get(item['source_item_id'], 0) != item['shipped_quantity']
            or amounts.get(item['source_item_id'], ZERO) > Decimal(item['total_price'])
            or (item['shipped_quantity'] == item['quantity'] and amounts.get(item['source_item_id'], ZERO) != Decimal(item['total_price']))
            for item in expected['items']):
        raise ValueError('全部原批次件数或商品金额与整单已发责任不一致')
    for key, cap in (('packaging_amount', Decimal(expected['internal_accessory'] or 0)),
                     ('handling_amount', Decimal(expected['surcharge_amount'])),
                     ('deposit_applied', Decimal(expected['local_deposit_amount'])),
                     ('deposit_charge_applied', Decimal(expected['local_deposit_charge']))):
        if sum((getattr(ship, key) for ship in row.shipments), ZERO) > cap:
            raise ValueError('全部原批次包装、费用或首款超出完整合同')
    ordered = sorted(row.shipments, key=lambda ship: ship.sequence)
    if any(ship.is_final for ship in ordered[:-1]) or (ordered[-1].is_final and
            any(item['shipped_quantity'] != item['quantity'] for item in expected['items'])):
        raise ValueError('原最终发货标记与全部已发数量不一致')
    existing = _query(db, select(ShipmentSettlement).where(ShipmentSettlement.invoice_id == invoice.id), lock)
    cancelled = [ship for ship in existing if ship.state == 'cancelled']
    for old in cancelled:
        apps = _query(db, select(SettlementApplication).where(SettlementApplication.settlement_id == old.id), lock)
        outbounds = _query(db, select(ShipmentOutbound).where(ShipmentOutbound.settlement_id == old.id), lock)
        if (any(app.status != 'released' or app.effective_amount or app.effective_bank_charge for app in apps)
                or any(outbound.status not in {'cancelled', 'local_cancelled'} or outbound.attempt_token or outbound.lease_until for outbound in outbounds)):
            raise ValueError('原已取消结算仍有资金占用或未决出库，须先核验')
    if {ship.id for ship in existing if ship.state != 'cancelled'} != {ship.existing_settlement_id for ship in row.shipments if ship.existing_settlement_id}:
        raise ValueError('既有发货结算须全部明确复用，不能遗漏或再次创建')
    receipts = _receipts(db, invoice, row, lock, proof)
    for ship in row.shipments:
        settlement = _current(db, select(ShipmentSettlement).where(ShipmentSettlement.id == ship.existing_settlement_id), lock) if ship.existing_settlement_id else None
        same_no = _query(db, select(ShipmentSettlement.id).where(ShipmentSettlement.settlement_no == ship.settlement_no), lock)
        if any(identity != ship.existing_settlement_id for identity in same_no):
            raise ValueError('原发货结算编号已存在，须明确复用原ID')
        if settlement:
            if (settlement.invoice_id != invoice.id or settlement.sequence != ship.sequence
                    or settlement.settlement_no != ship.settlement_no or settlement.state != 'shipped'
                    or bool(settlement.is_final) != ship.is_final
                    or any(Decimal(settlement.quote.get(key, '-1')) != getattr(ship, key) for key in QUOTE_MONEY)):
                raise ValueError('原发货结算状态、序号或冻结金额与核验事实不一致')
            originals = _query(db, select(SettlementItem).where(SettlementItem.settlement_id == settlement.id), lock)
            if {item.id for item in originals} != {item.existing_settlement_item_id for item in ship.items}:
                raise ValueError('必须复用原发货结算全部明细ID')
            for item in ship.items:
                original = next(r for r in originals if r.id == item.existing_settlement_item_id)
                if (original.invoice_item_id, original.quantity, original.line_amount) != (mapped[item.source_item_id], item.quantity, item.line_amount):
                    raise ValueError('原发货明细身份或已发金额不一致')
            applications = _query(db, select(SettlementApplication).where(SettlementApplication.settlement_id == settlement.id), lock)
            if {app.id for app in applications} != {app.existing_application_id for app in ship.applications if app.existing_application_id}:
                raise ValueError('必须复用原发货全部资金占用ID')
            for app in ship.applications:
                if app.existing_application_id:
                    original = next(a for a in applications if a.id == app.existing_application_id)
                    if (original.receipt_id != receipts[app.original_receipt_id].id or original.component != app.component
                            or any(getattr(original, key) != getattr(app, key) for key in
                                ('amount', 'bank_charge', 'released_amount', 'released_bank_charge'))):
                        raise ValueError('原发货资金占用事实不一致')
        elif ship.existing_settlement_id or any(item.existing_settlement_item_id for item in ship.items) or any(app.existing_application_id for app in ship.applications):
            raise ValueError('原结算不存在，不能拼接其他结算明细或资金应用')
        outbound = _current(db, select(ShipmentOutbound).where(ShipmentOutbound.id == ship.existing_outbound_id), lock) if ship.existing_outbound_id else None
        aliases = [identity for identity in (ship.outbound_record_id, ship.outbound_invoice_id) if identity]
        duplicates = _query(db, select(ShipmentOutbound.id).where((ShipmentOutbound.outbound_no == ship.outbound_no)
            | (ShipmentOutbound.remote_id.in_(aliases))
            | (ShipmentOutbound.payload['original_outbound_record_id'].as_string().in_(aliases))
            | (ShipmentOutbound.payload['original_outbound_invoice_id'].as_string().in_(aliases))), lock)
        if any(identity != ship.existing_outbound_id for identity in duplicates):
            raise ValueError('原出库身份已存在，须明确复用且核验租户冲突')
        if outbound:
            if (settlement is None or outbound.settlement_id != settlement.id or outbound.invoice_id != invoice.id
                    or outbound.outbound_no != ship.outbound_no or outbound.status not in {'shipped', 'verified', 'synced'}
                    or outbound.remote_id not in {ship.outbound_invoice_id, ship.outbound_record_id}
                    or outbound.attempt_token or outbound.lease_until):
                raise ValueError('原出库关联、编号、状态或外部未决动作不一致')
        elif ship.existing_outbound_id:
            raise ValueError('原出库记录不存在')
        if settlement:
            linked = _query(db, select(ShipmentOutbound.id).where(ShipmentOutbound.settlement_id == settlement.id), lock)
            if set(linked) != ({ship.existing_outbound_id} if ship.existing_outbound_id else set()):
                raise ValueError('原结算已有出库记录，必须明确复用原身份')
        inspections = _query(db, select(ShippingInspection).where(ShippingInspection.outbound_record_id == ship.outbound_record_id), lock)
        if {item.id for item in inspections} != ({ship.inspection_id} if ship.inspection_id else set()):
            raise ValueError('原检验资料须明确复用原ID，不得遗漏照片视频')
        if ship.inspection_id:
            inspection = next(iter(inspections), None)
            if (inspection is None or inspection.local_outbound_id is not None or inspection.outbound_no != ship.outbound_no
                    or inspection.status != 'submitted' or inspection.submitted_at is None
                    or inspection.submitted_at > ship.shipped_at):
                raise ValueError('原检验关联、状态或提交时间与原已发事实不一致')
            media = _query(db, select(ShippingInspectionPhoto).where(ShippingInspectionPhoto.inspection_id == inspection.id), lock)
            if any(photo.item_id is not None and photo.item_id not in {i.outbound_item_id for i in ship.items} for photo in media):
                raise ValueError('原照片或视频明细身份不属于核验出库清单')
        pending = _query(db, select(ShippingOperationEvent.id).where(ShippingOperationEvent.scope == 'outbound-invoice-sync',
            ShippingOperationEvent.request_id == ship.outbound_record_id,
            ShippingOperationEvent.action.in_(['sync_pending', 'sync_sending', 'sync_uncertain', 'recheck_required'])), lock)
        if pending:
            raise ValueError('原出库存在未完成远端同步，须先核验')
    return proof, invoice, mapped, lines, receipts


def preview(db, body, *, lock=False):
    conflicts = []
    prior = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == body.batch_key), lock)
    if prior and prior.manifest_hash != digest(body.model_dump(mode='json')):
        conflicts.append(dict(section='batch', record_index=None, code='content_changed', message='批次身份已用于不同内容'))
    for index, row in enumerate(body.orders):
        try:
            record = _record(db, body, 'shipment_opening', str(row.order_binding_record_id), lock)
            if record:
                _assert_record(record, body, 'opening', 'shipment_opening', str(row.order_binding_record_id), row.model_dump(mode='json'))
            else:
                _check(db, body, row, lock)
        except ValueError as exc:
            conflicts.append(dict(section='orders', record_index=index, code='fulfillment_conflict', message=str(exc)))
    return dict(manifest_hash=digest(body.model_dump(mode='json')), can_apply=not conflicts, order_count=len(body.orders), conflicts=conflicts)


def _post(db, body, row, record, actor_id):
    proof, invoice, mapped, lines, receipts = _check(db, body, row, True)
    parent_batch = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == proof.batch_key), True)
    order_mapping = next(m for m in parent_batch.result['orders'] if m['record_id'] == proof.id)
    ar_ids = {m['external_id']: m['receivable_id'] for m in order_mapping['receivables']}
    result = dict(record_id=record.id, order_binding_record_id=proof.id, invoice_id=invoice.id, shipments=[])
    for ship in sorted(row.shipments, key=lambda s: s.sequence):
        quote = {key: str(getattr(ship, key)) for key in QUOTE_MONEY}
        quote.update(invoice_id=invoice.id, invoice_no=invoice.invoice_no, is_final=ship.is_final,
            business_date=ship.business_date.isoformat(), warehouse_id=ship.warehouse_id, currency=invoice.currency,
            customer_id=f'ark:{invoice.local_customer_id}', opening_record_id=record.id,
            items=[dict(invoice_item_id=mapped[i.source_item_id], quantity=i.quantity, line_amount=str(i.line_amount)) for i in ship.items])
        settlement = finance.lock(db, ShipmentSettlement, ship.existing_settlement_id) if ship.existing_settlement_id else ShipmentSettlement(
            invoice_id=invoice.id, sequence=ship.sequence, settlement_no=ship.settlement_no, state='shipped',
            is_final=int(ship.is_final), quote=quote, quote_hash=digest(quote),
            request_key=f'opening-shipment:{record.id}:{ship.sequence}', request_hash=record.content_hash,
            created_by=actor_id, created_at=ship.shipped_at)
        if settlement.id is None:
            db.add(settlement); db.flush()
        else:
            settlement.quote, settlement.quote_hash = quote, digest(quote)
            settlement.version += 1
        items = []
        for source in ship.items:
            item = finance.lock(db, SettlementItem, source.existing_settlement_item_id) if source.existing_settlement_item_id else SettlementItem(
                settlement_id=settlement.id, invoice_item_id=mapped[source.source_item_id], quantity=source.quantity,
                line_amount=source.line_amount, snapshot={'historical_item': source.model_dump(mode='json'), 'migration_record_id': record.id})
            if item.id is None:
                db.add(item); db.flush()
            items.append(dict(settlement_item_id=item.id, source_item_id=source.source_item_id, outbound_item_id=source.outbound_item_id))
            line = lines[item.invoice_item_id]
            reservation = _current(db, select(StockReservation).where(StockReservation.invoice_item_id == line.id,
                StockReservation.warehouse_id == ship.warehouse_id), True)
            if reservation is None:
                reservation = StockReservation(invoice_item_id=line.id, warehouse_id=ship.warehouse_id,
                    sku_id=line.local_sku_id, reserved=0, shipped=0)
                db.add(reservation)
            if reservation.sku_id != line.local_sku_id or reservation.reserved:
                raise ValueError('原发货仓库责任已有不同本地预占，不能覆盖')
            reservation.shipped += item.quantity
            line.stock_shipped_quantity += item.quantity
        for source in ship.applications:
            app = finance.lock(db, SettlementApplication, source.existing_application_id) if source.existing_application_id else SettlementApplication(
                settlement_id=settlement.id, receipt_id=receipts[source.original_receipt_id].id, component=source.component,
                amount=source.amount, bank_charge=source.bank_charge, released_amount=source.released_amount,
                released_bank_charge=source.released_bank_charge)
            app.status = 'released' if source.released_amount == source.amount else 'applied'
            if app.id is None:
                db.add(app)
        payload_items = [dict(invoice_item_id=mapped[i.source_item_id], local_sku_id=lines[mapped[i.source_item_id]].local_sku_id,
            product_name=lines[mapped[i.source_item_id]].product_name, model=lines[mapped[i.source_item_id]].model,
            color=lines[mapped[i.source_item_id]].color, size=lines[mapped[i.source_item_id]].length,
            product_kind=lines[mapped[i.source_item_id]].product_kind,
            unit='piece', qty=i.quantity, original_outbound_item_id=i.outbound_item_id) for i in ship.items]
        payload = dict(transaction_mode='local', opening_record_id=record.id, original_outbound_record_id=ship.outbound_record_id,
            original_outbound_invoice_id=ship.outbound_invoice_id, items=payload_items, outbound_version=1,
            customer_name=invoice.customer_name, owner_name=invoice.sales_user_name, historical_business_date=ship.business_date.isoformat())
        outbound = finance.lock(db, ShipmentOutbound, ship.existing_outbound_id) if ship.existing_outbound_id else ShipmentOutbound(
            settlement_id=settlement.id, invoice_id=invoice.id, outbound_no=ship.outbound_no, remote_id=ship.outbound_invoice_id or ship.outbound_record_id,
            status='local_shipped', payload=payload, payload_hash=digest(payload), created_at=ship.shipped_at, verified_at=ship.shipped_at)
        if outbound.id is None:
            db.add(outbound); db.flush()
        else:
            payload['outbound_version'] = outbound.version + 1
            outbound.payload, outbound.payload_hash, outbound.status = payload, digest(payload), 'local_shipped'
            outbound.version += 1
        if ship.inspection_id:
            inspection = finance.lock(db, ShippingInspection, ship.inspection_id)
            inspection.local_outbound_id, inspection.local_outbound_version = outbound.id, payload['outbound_version']
        for source_ar in proof.snapshot['receivables']:
            if source_ar['source_settlement_id'] == ship.source_settlement_id:
                target = finance.lock(db, Receivable, ar_ids[source_ar['external_id']])
                if target.settlement_id not in {None, settlement.id}:
                    raise ValueError('原运费应收已有不同发货关联')
                target.settlement_id = settlement.id
        db.add(InvoiceCommerceEvent(invoice_id=invoice.id, action='opening_shipment',
            request_key=f'opening-shipment-event:{record.id}:{ship.sequence}', request_hash=record.content_hash,
            created_by=actor_id, payload={'migration_record_id': record.id, 'settlement_id': settlement.id,
                'body': {'business_date': ship.business_date.isoformat()}}))
        result['shipments'].append(dict(source_settlement_id=ship.source_settlement_id, settlement_id=settlement.id,
            outbound_id=outbound.id, outbound_record_id=ship.outbound_record_id, items=items))
    db.flush()
    return result


def apply_manifest(db, body, user):
    from app.commerce_migration.handover_service import stage_invoices
    ids = [db.get(MigrationRecord, row.order_binding_record_id).local_invoice_id for row in body.orders
           if db.get(MigrationRecord, row.order_binding_record_id) is not None]
    stage_invoices(db, ids, body)
    with db.begin_nested():
        ledger = finance.book(db)
        actor_id = int(user['sub'])
        actor = _shared(db, select(ArkUser).where(ArkUser.id == actor_id), True)
        if actor is None or not actor.is_active or actor.deleted_at:
            raise ValueError('导入账号不可用')
        prior = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == body.batch_key), True)
        manifest_hash = digest(body.model_dump(mode='json'))
        if prior:
            if prior.manifest_hash != manifest_hash:
                raise ValueError('批次身份已用于不同内容')
            return prior.result
        finance.open_date(ledger, body.cutover_date)
        proofs = [_current(db, select(MigrationRecord).where(MigrationRecord.id == row.order_binding_record_id), True) for row in body.orders]
        for identity in sorted({proof.local_invoice_id for proof in proofs if proof and proof.local_invoice_id}):
            finance.lock(db, Invoice, identity)
        _lock_warehouses(db, [ship.warehouse_id for row in body.orders for ship in row.shipments], allow_inactive=True)
        for row in body.orders:
            if _record(db, body, 'shipment_opening', str(row.order_binding_record_id), True) is None:
                _check(db, body, row, True)
        batch = MigrationBatch(batch_key=body.batch_key, source=body.source, tenant=body.tenant, manifest_hash=manifest_hash,
            evidence_sha256=body.evidence_sha256, review_reference=body.review_reference, cutover_date=body.cutover_date,
            result={}, created_by=actor_id)
        db.add(batch); db.flush()
        result = dict(batch_key=body.batch_key, manifest_hash=manifest_hash, orders=[])
        for row in body.orders:
            record = _record(db, body, 'shipment_opening', str(row.order_binding_record_id), True)
            if record:
                _assert_record(record, body, 'opening', 'shipment_opening', str(row.order_binding_record_id), row.model_dump(mode='json'))
                original = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == record.batch_key), True)
                mapping = next((m for m in original.result.get('orders', []) if m['record_id'] == record.id), None) if original else None
                if mapping is None:
                    raise ValueError('原履约承接结果关联缺失，须核验恢复')
            else:
                snapshot = row.model_dump(mode='json')
                record = MigrationRecord(batch_key=body.batch_key, source=body.source, tenant=body.tenant,
                    object_type='shipment_opening', external_id=str(row.order_binding_record_id), role='opening',
                    content_hash=digest(snapshot), snapshot=snapshot)
                db.add(record); db.flush()
                mapping = _post(db, body, row, record, actor_id)
            result['orders'].append(mapping)
        batch.result = result
        db.flush()
        return result
