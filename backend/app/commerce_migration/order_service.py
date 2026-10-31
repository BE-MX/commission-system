"""Prepare complete historical contracts in the existing order ledger.

Preparation freezes reviewed source facts and preserves original identities.
The order remains unavailable to ordinary writers until all closing balances
and fulfillment responsibilities have been checked by activation.
"""
from datetime import datetime, time
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from app.auth.models import ArkUser
from app.catalog.models import CatalogSku
from app.commerce_migration.models import MigrationBatch, MigrationRecord
from app.commerce_migration.service import _current, _record, _assert_record, digest
from app.commerce_migration.finance_service import _customer_proof, _shared, _query
from app.customer.models import CustomerAccount, CustomerOrder, CustomerOrderItem, CustomerObjectOwnership
from app.customer.projection_common import append_raw, bind_source
from app.core.time import beijing_now
from app.finance import service as finance
from app.finance.models import FinanceEvent
from app.invoice.models import Invoice, InvoiceItem, InvoiceCommerceEvent
from app.invoice.settlement_models import Receivable
from app.system.models import SysDict

HEADER_FIELDS = ('invoice_no', 'order_type', 'customer_name', 'customer_grade', 'contact_name', 'contact_phone',
    'contact_email', 'delivery_address', 'sales_user_id', 'sales_user_name', 'merchandiser_id', 'merchandiser_name',
    'invoice_date', 'currency', 'express_channel', 'shipping_fee', 'surcharge_name', 'surcharge_amount',
    'packaging_quantity', 'internal_accessory', 'internal_discount', 'internal_payment_method',
    'internal_shipping_type', 'product_amount', 'total_amount', 'payment_term', 'remark')
ITEM_FIELDS = ('product_kind', 'item_type', 'custom_product_id', 'product_name', 'product_display',
    'net_weight_grams', 'model', 'color', 'length', 'curl', 'quantity', 'price_per_piece', 'standard_price',
    'customer_price', 'discount_amount', 'total_price', 'price_source')
ORDER_FIELDS = {'order_no': 'source_order_no', 'order_name': 'source_order_name', 'order_status': 'source_order_status',
    'account_date': 'account_date', 'currency': 'currency', 'amount_original': 'business_amount_original',
    'amount_usd': 'business_amount_usd', 'source_category': 'commercial_source', 'is_new_deal': 'is_new_deal',
    'is_first_return': 'is_first_return', 'is_valid_business_order': 'is_valid_business_order',
    'owner_user_id': 'sales_user_id', 'owner_external_user_id': 'owner_external_user_id'}
ZERO = Decimal('0')
ALIAS_FIELDS = ('id', 'order_id', 'external_item_id', 'external_product_id', 'external_sku_id',
    'product_name', 'product_family', 'model', 'color', 'length', 'quantity', 'quantity_unit',
    'unit_price', 'line_amount', 'item_type', 'source_record_id', 'item_fingerprint', 'created_at', 'updated_at')


def alias_snapshot(entity):
    """Canonical original values; the reviewed hash must come from this exact row."""
    result = {}
    for key in ALIAS_FIELDS:
        value = getattr(entity, key)
        if isinstance(value, Decimal):
            value = format(value.normalize(), 'f')
        elif isinstance(value, datetime):
            value = value.isoformat()
        result[key] = value
    return result


def _assert_values(entity, expected, message):
    if any(getattr(entity, key) != value for key, value in expected.items()):
        raise ValueError(message)


def _check_order(db, body, row, lock):
    customer = _current(db, select(CustomerAccount).where(CustomerAccount.id == row.local_customer_id), lock)
    if customer is None or customer.record_status != 'active' or customer.identity_status == 'disputed':
        raise ValueError('整单承接须明确有效方舟客户')
    _customer_proof(db, body, row, lock)
    for identity in {row.sales_user_id, row.merchandiser_id} - {None}:
        if _shared(db, select(ArkUser).where(ArkUser.id == identity), lock) is None:
            raise ValueError('原业务员或跟单员缺少本地身份关联')
    for department in row.departments:
        target = _current(db, select(SysDict).where(SysDict.id == department.department_id), lock)
        if target is None or target.type != 'sales_department':
            raise ValueError('原部门缺少本地身份关联')
    invoice = _current(db, select(Invoice).where(Invoice.id == row.existing_invoice_id), lock) if row.existing_invoice_id else None
    duplicates = _query(db, select(Invoice.id).where(
        (Invoice.xiaoman_order_id == row.source_order_id) | (Invoice.invoice_no == row.invoice_no)), lock)
    if any(identity != row.existing_invoice_id for identity in duplicates):
        raise ValueError('原订单或发票已存在，必须明确复用原主账ID')
    if row.existing_invoice_id:
        if invoice is None or invoice.transaction_mode != 'legacy':
            raise ValueError('原发票不存在或已由本地管理，禁止再次承接')
        _assert_values(invoice, {**{key: getattr(row, key) for key in HEADER_FIELDS},
            'customer_id': row.source_customer_id, 'xiaoman_order_id': row.source_order_id,
            'xiaoman_order_no': row.legacy_invoice_order_no}, '原完整发票头与核验快照不一致')
        if ((invoice.internal_received is not None and invoice.internal_received != row.source_received_amount)
                or (invoice.internal_balance is not None and invoice.internal_balance != row.source_balance_amount)
                or invoice.linked_sync_id or invoice.sync_attempt
                or invoice.cancellation and invoice.cancellation.get('status') not in {'remote_deleted', 'retained', 'aborted'}
                or invoice.sync_status in {'sync_failed', 'sync_uncertain'}):
            raise ValueError('原收款余额或远端未决动作须先核验，不能覆盖承接')
        if invoice.status == 'cancelled' and row.commerce_status != 'cancelled':
            raise ValueError('原已取消主账不能承接为有效待发订单')
        if (_query(db, select(InvoiceCommerceEvent.id).where(InvoiceCommerceEvent.invoice_id == invoice.id), lock)
                or _query(db, select(FinanceEvent.id).join(Receivable, Receivable.id == FinanceEvent.receivable_id)
                    .where(Receivable.invoice_id == invoice.id), lock)):
            raise ValueError('整单已有在线经济事实，禁止重新建立期初')
        items = _query(db, select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id).order_by(InvoiceItem.id), lock)
        if {item.id for item in items} != {item.existing_invoice_item_id for item in row.items}:
            raise ValueError('必须一对一复用全部原发票明细，不能遗漏或仅导入未发部分')
        by_id = {item.id: item for item in items}
        for item in row.items:
            original = by_id[item.existing_invoice_item_id]
            _assert_values(original, {**{key: getattr(item, key) for key in ITEM_FIELDS},
                'product_id': item.legacy_product_id, 'sku_id': item.legacy_sku_id,
                'xiaoman_unique_id': item.legacy_unique_id}, '原完整发票明细与核验快照不一致')
            if (original.stock_reserved_quantity or original.production_pending_quantity or original.stock_shipped_quantity
                    or original.local_sku_id not in {None, item.local_sku_id}):
                raise ValueError('原明细已有本地供货责任或不同SKU关联，禁止覆盖')
        targets = _query(db, select(Receivable).where(Receivable.invoice_id == invoice.id), lock)
        if {target.id for target in targets} != {target.existing_receivable_id for target in row.receivables if target.existing_receivable_id}:
            raise ValueError('必须明确复用全部原应收，不能遗漏独立运费')
        by_target = {target.id: target for target in targets}
        for source in row.receivables:
            if source.existing_receivable_id:
                target = by_target[source.existing_receivable_id]
                _assert_values(target, dict(kind=source.kind, amount=source.amount, currency=row.currency,
                    customer_id=row.source_customer_id, handling_amount=source.handling_amount), '原应收面额、费用或客户身份不一致')
                if target.paid_amount or target.adjustment_amount or target.attempt_token or target.lease_until:
                    raise ValueError('原应收已有本地变更或未决外部动作，须先核验')
        # Existing shipments are adopted by the separate fulfillment opening;
        # preserving them here cannot authorize them as local shipped facts.
    elif any(item.existing_invoice_item_id for item in row.items) or any(a.existing_receivable_id for a in row.receivables):
        raise ValueError('原发票不存在时不能拼接其他主账的明细或应收')
    for item in row.items:
        proof = _current(db, select(MigrationRecord).where(MigrationRecord.id == item.catalog_record_id), lock)
        sku = _current(db, select(CatalogSku).where(CatalogSku.id == item.local_sku_id), lock)
        if (proof is None or proof.role != 'catalog' or proof.object_type != 'sku'
                or (proof.source, proof.tenant, proof.local_sku_id) != (body.source, body.tenant, item.local_sku_id)
                or sku is None or sku.unit != 'piece'):
            raise ValueError('原明细缺少同来源已核验的本地SKU映射')
        if (item.legacy_product_id is not None and proof.snapshot.get('external_product_id') != str(item.legacy_product_id)
                or item.legacy_sku_id is not None and proof.snapshot.get('external_sku_id') != str(item.legacy_sku_id)):
            raise ValueError('原外部产品或SKU与核验目录映射不一致')
    order = _current(db, select(CustomerOrder).where(CustomerOrder.id == row.existing_customer_order_id), lock) if row.existing_customer_order_id else None
    same = _query(db, select(CustomerOrder.id).where(CustomerOrder.source_system == body.source,
        CustomerOrder.source_account_key == body.tenant, CustomerOrder.external_order_id == row.source_order_id), lock)
    if any(identity != row.existing_customer_order_id for identity in same):
        raise ValueError('原经营订单已存在，必须复用原经营投影ID')
    if row.existing_customer_order_id:
        if order is None or order.local_invoice_id is not None:
            raise ValueError('原经营订单不存在或已绑定本地主账')
        _assert_values(order, {**{key: getattr(row, source) for key, source in ORDER_FIELDS.items()},
            'source_system': body.source, 'source_account_key': body.tenant,
            'external_order_id': row.source_order_id}, '原经营订单来源、金额或商业标记与核验事实不一致')
        ownership = _current(db, select(CustomerObjectOwnership).where(CustomerObjectOwnership.object_type == 'order',
            CustomerObjectOwnership.object_id == order.id), lock)
        current_customer = ownership.current_customer_id if ownership else order.customer_id
        visited = set()
        while current_customer not in visited:
            visited.add(current_customer)
            account = _current(db, select(CustomerAccount).where(CustomerAccount.id == current_customer), lock)
            if account is None or account.record_status != 'merged':
                break
            current_customer = account.merged_into_customer_id
        if current_customer != row.local_customer_id:
            raise ValueError('原经营订单当前逻辑客户与整单承接客户不一致')
        items = _query(db, select(CustomerOrderItem).where(CustomerOrderItem.order_id == order.id), lock)
        originals = {item.existing_customer_order_item_id for item in row.items if item.existing_customer_order_item_id}
        originals.update(alias.existing_customer_order_item_id for alias in row.customer_item_aliases)
        if {item.id for item in items} != originals:
            raise ValueError('须明确关联全部原经营明细或核验聚合别名，不能遗漏或猜测拆分')
        by_id = {item.id: item for item in items}
        grouped = {identity for alias in row.customer_item_aliases for identity in alias.source_item_ids}
        for alias in row.customer_item_aliases:
            original = by_id[alias.existing_customer_order_item_id]
            if (original.local_invoice_item_id is not None or original.projection_role != 'active'
                    or original.historical_alias_id is not None
                    or original.source_record_id != alias.source_record_id
                    or original.item_fingerprint != alias.item_fingerprint
                    or original.external_item_id != alias.external_item_id
                    or digest(alias_snapshot(original)) != alias.original_snapshot_sha256
                    or original.line_amount != sum((item.total_price for item in row.items
                        if item.source_item_id in alias.source_item_ids), ZERO)):
                raise ValueError('原聚合行身份、完整原值指纹或全部成员金额与核验凭证不一致')
        for item in row.items:
            if item.source_item_id in grouped:
                continue
            if item.existing_customer_order_item_id is None:
                raise ValueError('未归组的原真实明细必须明确原经营行ID')
            original = by_id[item.existing_customer_order_item_id]
            if (original.local_invoice_item_id is not None or original.projection_role != 'active'
                    or original.historical_alias_id is not None or original.quantity_unit not in {'piece', 'pcs', 'pieces'}):
                raise ValueError('原经营明细已绑定或计量单位不能确认按件')
            _assert_values(original, dict(external_item_id=item.legacy_unique_id, quantity=item.quantity,
                unit_price=item.price_per_piece, line_amount=item.total_price, item_type=item.commercial_kind),
                '原经营明细原身份、金额、件数或商业类型不一致')
    elif any(item.existing_customer_order_item_id for item in row.items):
        raise ValueError('原经营订单不存在时不能拼接其他订单明细')
    return invoice, order


def preview(db, body, *, lock=False):
    conflicts = []
    prior = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == body.batch_key), lock)
    if prior and prior.manifest_hash != digest(body.model_dump(mode='json')):
        conflicts.append(dict(section='batch', record_index=None, code='content_changed', message='批次身份已用于不同内容'))
    for index, row in enumerate(body.orders):
        try:
            record = _record(db, body, 'order_binding', row.source_order_id, lock)
            if record:
                _assert_record(record, body, 'opening', 'order_binding', row.source_order_id, row.model_dump(mode='json'))
            else:
                _check_order(db, body, row, lock)
        except ValueError as exc:
            conflicts.append(dict(section='orders', record_index=index, code='order_conflict', message=str(exc)))
    return dict(manifest_hash=digest(body.model_dump(mode='json')), can_apply=not conflicts,
        order_count=len(body.orders), conflicts=conflicts)


def _source(db, body, row, entity, identity, snapshot, customer_id):
    source = append_raw(db, source_system=body.source, source_account_key=body.tenant,
        source_entity_type=entity, external_record_id=identity, schema_version='reviewed_order_opening_v1',
        payload=snapshot, occurred_at=datetime.combine(row.account_date, time.min), captured_at=beijing_now(), sync_cursor=None)
    bind_source(source, customer_id)
    source.processing_status = 'processed'
    return source


def _post_order(db, body, row, record, actor_id):
    invoice = finance.lock(db, Invoice, row.existing_invoice_id) if row.existing_invoice_id else Invoice(
        **{key: getattr(row, key) for key in HEADER_FIELDS}, customer_id=row.source_customer_id,
        xiaoman_order_id=row.source_order_id, xiaoman_order_no=row.legacy_invoice_order_no, source_type='commerce_opening',
        source_order_id=row.source_order_id, created_by=actor_id)
    if invoice.id is None:
        db.add(invoice); db.flush()
    originals = dict(invoice_id=invoice.id, invoice_received=str(invoice.internal_received) if invoice.internal_received is not None else None,
        invoice_balance=str(invoice.internal_balance) if invoice.internal_balance is not None else None,
        invoice_status=invoice.status, sync_status=invoice.sync_status)
    from app.commerce_transition.service import policy
    invoice.transaction_mode, invoice.commerce_status = ('legacy' if policy(db).phase == 'transition' else 'local'), 'opening'
    invoice.local_customer_id, invoice.local_rate_to_usd = row.local_customer_id, row.rate_to_usd
    invoice.local_deposit_amount, invoice.local_deposit_charge = row.local_deposit_amount, row.local_deposit_charge
    invoice.local_commercial = {key: getattr(row, key) for key in ('commercial_source', 'is_new_deal', 'is_first_return', 'is_private_order', 'country')}
    invoice.local_commercial = {**invoice.local_commercial, 'customer_name': row.customer_name,
        'account_date': row.account_date.isoformat(), 'departments': [d.model_dump(mode='json') for d in row.departments],
        'opening_valid_business_order': row.is_valid_business_order,
        'opening_business_amount_original': str(row.business_amount_original)}
    invoice.commerce_version += 1
    invoice.internal_received, invoice.internal_balance = ZERO, row.source_received_amount + row.source_balance_amount
    invoice.updated_by = actor_id
    event = InvoiceCommerceEvent(invoice_id=invoice.id, request_key=f'opening-order:{record.id}',
        request_hash=record.content_hash, action='opening_order', payload={'migration_record_id': record.id}, created_by=actor_id)
    db.add(event); db.flush()
    source = _source(db, body, row, 'order', row.source_order_id, row.model_dump(mode='json'), row.local_customer_id)
    order = finance.lock(db, CustomerOrder, row.existing_customer_order_id) if row.existing_customer_order_id else CustomerOrder(
        customer_id=row.local_customer_id, source_system=body.source, source_account_key=body.tenant,
        external_order_id=row.source_order_id, **{key: getattr(row, source) for key, source in ORDER_FIELDS.items()},
        invalid_reason=None if row.is_valid_business_order else 'source_invalid', source_record_id=source.id,
        source_hash=source.content_hash, synced_at=beijing_now())
    if order.id is None:
        db.add(order); db.flush()
    originals.update(customer_order_id=order.id, source_record_id=order.source_record_id, source_hash=order.source_hash,
        storage_customer_id=order.customer_id, items=[], aliases=[])
    order.local_invoice_id = invoice.id
    mapping = dict(record_id=record.id, invoice_id=invoice.id, customer_order_id=order.id, items=[], receivables=[])
    aliases = {}
    for alias in row.customer_item_aliases:
        original = finance.lock(db, CustomerOrderItem, alias.existing_customer_order_item_id)
        snapshot = alias_snapshot(original)
        # Preserve every historical field and timestamp; only its projection role changes.
        original.projection_role, original.updated_at = 'historical_alias', original.updated_at
        flag_modified(original, 'updated_at')
        originals['aliases'].append(dict(snapshot=snapshot, source_item_ids=alias.source_item_ids))
        aliases.update({identity: original.id for identity in alias.source_item_ids})
    for index, item in enumerate(row.items):
        line = finance.lock(db, InvoiceItem, item.existing_invoice_item_id) if item.existing_invoice_item_id else InvoiceItem(
            invoice_id=invoice.id, sort_order=index, **{key: getattr(item, key) for key in ITEM_FIELDS},
            product_id=item.legacy_product_id, sku_id=item.legacy_sku_id, xiaoman_unique_id=item.legacy_unique_id)
        if line.id is None:
            db.add(line); db.flush()
        line.local_sku_id, line.commercial_kind = item.local_sku_id, item.commercial_kind
        # Physical and in-production counters are installed by their reviewed
        # responsibility imports; no stock issue or factory receipt is replayed.
        item_source = _source(db, body, row, 'order_item', f'{row.source_order_id}:{item.source_item_id}',
            item.model_dump(mode='json'), row.local_customer_id)
        projected = finance.lock(db, CustomerOrderItem, item.existing_customer_order_item_id) if item.existing_customer_order_item_id else CustomerOrderItem(
            order_id=order.id, external_item_id=f'ark:line:{line.id}' if item.source_item_id in aliases else item.source_item_id,
            historical_alias_id=aliases.get(item.source_item_id), projection_role='active',
            external_product_id=str(item.legacy_product_id) if item.legacy_product_id is not None else None,
            external_sku_id=str(item.legacy_sku_id) if item.legacy_sku_id is not None else None,
            product_name=item.product_name, product_family=item.product_family, model=item.model, color=item.color,
            length=item.length, quantity=item.quantity, quantity_unit='piece', unit_price=item.price_per_piece,
            line_amount=item.total_price, item_type=item.commercial_kind, source_record_id=item_source.id,
            item_fingerprint=digest([body.source, body.tenant, row.source_order_id, item.source_item_id]))
        if projected.id is None:
            db.add(projected); db.flush()
        projected.local_invoice_item_id = line.id
        originals['items'].append(dict(invoice_item_id=line.id, customer_order_item_id=projected.id,
            source_record_id=projected.source_record_id, item_fingerprint=projected.item_fingerprint,
            historical_alias_id=projected.historical_alias_id))
        mapping['items'].append(dict(source_item_id=item.source_item_id, invoice_item_id=line.id, customer_order_item_id=projected.id))
    for index, source_ar in enumerate(row.receivables):
        target = finance.lock(db, Receivable, source_ar.existing_receivable_id) if source_ar.existing_receivable_id else Receivable(
            invoice_id=invoice.id, business_key=f'opening-ar:{record.id}:{index}', kind=source_ar.kind,
            amount=source_ar.amount, currency=row.currency, customer_id=row.source_customer_id)
        if target.id is None:
            db.add(target); db.flush()
        target.customer_id, target.remote_status = f'ark:{row.local_customer_id}', 'not_applicable'
        target.due_date, target.paid_amount = source_ar.due_date, ZERO
        target.adjustment_amount = sum((a.amount for a in source_ar.adjustments), ZERO)
        target.handling_amount = source_ar.handling_amount - sum((a.released_bank_charge for a in source_ar.adjustments), ZERO)
        if source_ar.existing_receivable_id:
            target.version += 1
        for adjustment_index, adjustment in enumerate(source_ar.adjustments):
            db.add(FinanceEvent(request_key=f'opening-ar:{record.id}:{index}:{adjustment_index}',
                request_hash=digest(adjustment.model_dump(mode='json')), action='opening_adjustment',
                receivable_id=target.id, amount=adjustment.amount, business_date=body.cutover_date, created_by=actor_id,
                payload={'migration_record_id': record.id, 'historical_adjustment': adjustment.model_dump(mode='json'),
                    'released_bank_charge': str(adjustment.released_bank_charge),
                    **({'contract_change_event_id': event.id} if adjustment.kind == 'contract_change' else {})}))
        mapping['receivables'].append(dict(external_id=source_ar.external_id, receivable_id=target.id))
    record.local_invoice_id, record.local_customer_order_id = invoice.id, order.id
    record.snapshot = {**record.snapshot, '_original_links': originals}
    db.flush()
    return mapping


def apply_manifest(db, body, user):
    from app.commerce_migration import handover_service as handover
    preparation_id = handover.begin_orders(db, body)
    if preparation_id is not None:
        from app.commerce_transition.models import TransferPreparation
        prepared = db.get(TransferPreparation, preparation_id)
        if handover.pending_original_requests(db, prepared.manifest['invoice_ids']):
            return dict(batch_key=body.batch_key, status='waiting', orders=[],
                        handover_preparation_id=preparation_id, message='原在途或unknown须先核对，冻结已保留')
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
        for identity in sorted({row.existing_invoice_id for row in body.orders if row.existing_invoice_id}):
            finance.lock(db, Invoice, identity)
        for row in body.orders:
            record = _record(db, body, 'order_binding', row.source_order_id, True)
            if record:
                _assert_record(record, body, 'opening', 'order_binding', row.source_order_id, row.model_dump(mode='json'))
            else:
                _check_order(db, body, row, True)
        batch = MigrationBatch(batch_key=body.batch_key, source=body.source, tenant=body.tenant,
            manifest_hash=manifest_hash, evidence_sha256=body.evidence_sha256, review_reference=body.review_reference,
            cutover_date=body.cutover_date, result={}, created_by=actor_id)
        db.add(batch); db.flush()
        result = dict(batch_key=body.batch_key, manifest_hash=manifest_hash, orders=[])
        if preparation_id is not None:
            result['handover_preparation_id'] = preparation_id
        for row in body.orders:
            record = _record(db, body, 'order_binding', row.source_order_id, True)
            if record:
                original = _current(db, select(MigrationBatch).where(MigrationBatch.batch_key == record.batch_key), True)
                mapping = next((m for m in original.result.get('orders', []) if m['record_id'] == record.id), None) if original else None
                if mapping is None:
                    raise ValueError('整单承接缺少原结果关联，须核验恢复')
            else:
                snapshot = row.model_dump(mode='json')
                record = MigrationRecord(batch_key=body.batch_key, source=body.source, tenant=body.tenant,
                    object_type='order_binding', external_id=row.source_order_id, role='opening',
                    content_hash=digest(snapshot), snapshot=snapshot)
                db.add(record); db.flush()
                mapping = _post_order(db, body, row, record, actor_id)
            result['orders'].append(mapping)
        batch.result = result
        db.flush()
        return result
