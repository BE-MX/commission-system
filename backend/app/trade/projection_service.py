"""Project native invoices into the shared customer order read model.

The checkpoint is saved only after every dependent customer update succeeds.
Callers commit; failure rolls this invoice back to the prior complete projection.
"""
from datetime import date, datetime, time
from decimal import Decimal
from sqlalchemy import select
from app.core.time import beijing_now
from app.customer.models import CustomerAccount, CustomerObjectOwnership, CustomerOrder, CustomerOrderItem
from app.commerce_migration.models import MigrationRecord
from app.commerce_migration.order_service import alias_snapshot
from app.customer.fact_service import DirectFactEvidence, append_fact
from app.customer.projection_common import append_raw, bind_source, sha256
from app.customer.projection_okki_order import _sync_order_items
from app.customer.workflow_service import activate_customer_from_order, reconcile_invalidated_order
from app.customer.pcw_order_service import on_order_projected
from app.finance.service import lock
from app.trade.models import TradeProjection
from app.trade.snapshot_service import build_snapshot, _current


def _active_customer(db, customer_id):
    visited = set()
    while customer_id and customer_id not in visited:
        visited.add(customer_id)
        account = lock(db, CustomerAccount, customer_id)
        if account is None:
            break
        if account.record_status == "active":
            return account
        if account.record_status != "merged":
            break
        customer_id = account.merged_into_customer_id
    raise ValueError("订单客户无法解析到有效客户")


def _source(db, payload, entity, identity, customer_id, occurred_at, captured):
    row = append_raw(db, source_system="ark", source_account_key="local", source_entity_type=entity,
        external_record_id=identity, schema_version=f"local_{entity}_v1", payload=payload,
        occurred_at=occurred_at, captured_at=captured, sync_cursor=None)
    bind_source(row, customer_id)
    row.processing_status = "processed"
    row.processing_error_code = row.processing_error_message = None
    return row


def _opening_proof(db, order, invoice_id):
    proof = db.scalar(_current(select(MigrationRecord).where(MigrationRecord.local_invoice_id == invoice_id,
        MigrationRecord.local_customer_order_id == order.id, MigrationRecord.object_type == 'order_binding',
        MigrationRecord.role == 'opening')))
    if (proof is None or (proof.source, proof.tenant, proof.external_id) !=
            (order.source_system, order.source_account_key, order.external_order_id)):
        raise ValueError('历史订单须先完成经营事实承接核验')
    return proof


def _sync_opening_items(db, order, snapshot, sources, proof, captured):
    current = db.scalars(_current(select(CustomerOrderItem).where(CustomerOrderItem.order_id == order.id))).all()
    aliases = {row.id: row for row in current if row.projection_role == 'historical_alias'}
    originals = proof.snapshot['_original_links']
    if set(aliases) != {link['snapshot']['id'] for link in originals['aliases']}:
        raise ValueError('历史聚合别名集合已改变，须先核验')
    for link in originals['aliases']:
        alias = aliases[link['snapshot']['id']]
        if (alias.local_invoice_item_id is not None or alias.historical_alias_id is not None
                or alias_snapshot(alias) != link['snapshot']):
            raise ValueError('历史聚合别名原值或稳定身份已改变，不能覆盖投影')
    current = [row for row in current if row.projection_role == 'active']
    by_line = {row.local_invoice_item_id: row for row in current}
    original = proof.snapshot['_original_links']['items']
    if any(by_line.get(link['invoice_item_id']) is None
            or by_line[link['invoice_item_id']].id != link['customer_order_item_id']
            or by_line[link['invoice_item_id']].historical_alias_id != link['historical_alias_id'] for link in original):
        raise ValueError('历史经营明细稳定关联已改变，不能重建或删除原身份')
    line_ids = {int(item['item_id']) for item in snapshot['items']}
    if any(row.local_invoice_item_id not in line_ids for row in current):
        raise ValueError('历史经营明细不能通过全量投影删除，须先核验合同变更')
    for item, source in zip(snapshot['items'], sources, strict=True):
        identity = int(item['item_id'])
        row = by_line.get(identity)
        if row is None:
            # An explicitly amended new local line has no old external identity.
            row = CustomerOrderItem(order_id=order.id, local_invoice_item_id=identity,
                external_item_id=f'ark:{identity}', item_fingerprint=sha256('opening_native_line', order.id, identity))
            db.add(row)
        for key in ('product_name', 'product_family', 'model', 'color', 'length', 'item_type'):
            setattr(row, key, item[key])
        row.quantity = Decimal(item['quantity'])
        row.unit_price = Decimal(item['unit_price']) if item['unit_price'] is not None else None
        row.line_amount = Decimal(item['line_amount'])
        if row.quantity_unit is None:
            row.quantity_unit = 'piece'
        row.source_record_id, row.updated_at = source.id, captured


def project_invoice(db, invoice_id):
    # The downstream fact/window services use ordinary SELECTs. A pre-existing
    # repeatable-read snapshot can miss other committed orders even after locks.
    # The worker starts its dedicated connection at READ COMMITTED before use.
    if db.get_bind().dialect.name == "mysql" and db.connection().get_isolation_level() != "READ COMMITTED":
        raise ValueError("订单投影需要独立 READ COMMITTED 事务")
    with db.begin_nested():
        snapshot = build_snapshot(db, invoice_id)
        if snapshot is None:
            return None
        # Invoice -> customer -> projected order, retaining immutable storage IDs.
        order = db.scalar(_current(select(CustomerOrder).where(CustomerOrder.local_invoice_id == invoice_id)))
        proof = None
        if order is not None:
            if order.source_system != "ark":
                proof = _opening_proof(db, order, invoice_id)
            ownership = db.scalar(_current(select(CustomerObjectOwnership).where(
                CustomerObjectOwnership.object_type == "order", CustomerObjectOwnership.object_id == order.id)))
            account = _active_customer(db, ownership.current_customer_id if ownership else order.customer_id)
        else:
            account = _active_customer(db, snapshot["customer_id"])
        snapshot["logical_customer_id"] = account.id
        content_hash = sha256(snapshot)
        checkpoint = db.scalar(_current(select(TradeProjection).where(TradeProjection.invoice_id == invoice_id)))
        if checkpoint is not None and checkpoint.content_hash == content_hash:
            return order
        captured = beijing_now()
        occurred = datetime.combine(date.fromisoformat(snapshot["account_date"]), time.min)
        source = _source(db, snapshot, "order", str(invoice_id), account.id, occurred, captured)
        commercial = snapshot["commercial"]
        values = dict(order_no=snapshot["order_no"], order_name=snapshot["order_no"],
            order_status=snapshot["status"], account_date=occurred.date(), currency=snapshot["currency"],
            amount_original=Decimal(snapshot["amount_original"]), amount_usd=Decimal(snapshot["amount_usd"]),
            source_category=commercial.get("commercial_source"),
            is_new_deal=commercial.get("is_new_deal"), is_first_return=commercial.get("is_first_return"),
            is_valid_business_order=snapshot["is_valid_business_order"], invalid_reason=snapshot["invalid_reason"],
            owner_user_id=snapshot["owner_user_id"], owner_external_user_id=None,
            source_record_id=source.id, source_hash=source.content_hash, synced_at=captured, updated_at=captured)
        if proof:
            # Source namespace, storage customer, original numbering and owner
            # aliases retain their identity across all future native updates.
            for key in ('order_no', 'order_name', 'owner_external_user_id'):
                values.pop(key)
        if order is None:
            order = CustomerOrder(local_invoice_id=invoice_id, customer_id=account.id, source_system="ark",
                source_account_key="local", external_order_id=str(invoice_id), created_at=captured, **values)
            db.add(order)
        else:
            for key, value in values.items():
                setattr(order, key, value)
        db.flush()
        sources = [_source(db, {**item, "logical_customer_id": account.id}, "order_item",
            f"{invoice_id}:{item['item_id']}", account.id, occurred, captured) for item in snapshot["items"]]
        if proof:
            _sync_opening_items(db, order, snapshot, sources, proof, captured)
        else:
            projected = _sync_order_items(db, order=order, raw_items=snapshot["items"], item_sources=sources,
                snapshot_mode="full", captured_at=captured)
            for row, item in zip(projected, snapshot['items'], strict=True):
                row.local_invoice_item_id = int(item['item_id'])
        if order.is_valid_business_order:
            append_fact(db, customer_id=account.id, subject_type="customer", fact_key="commercial.has_valid_order",
                value_type="boolean", value=True, fact_layer="observed", verification_status="verified", confidence=1,
                confidence_method_version="confidence_v1", confidence_components={"order_state": 1}, source_system="ark",
                source_entity_type="order", observed_at=occurred, source_record_id=source.id,
                direct_evidence=[DirectFactEvidence("order", order.id, {"json_path": "$.status"})])
        activate_customer_from_order(db, order.id)
        if not order.is_valid_business_order:
            reconcile_invalidated_order(db, order.id)
        db.flush()
        on_order_projected(db, order.id)
        if checkpoint is None:
            checkpoint = TradeProjection(invoice_id=invoice_id, customer_order_id=order.id)
            db.add(checkpoint)
        checkpoint.invoice_version = snapshot["invoice_version"]
        checkpoint.finance_event_id = snapshot["finance_event_id"]
        checkpoint.aftersales_execution_id = snapshot["aftersales_execution_id"]
        checkpoint.content_hash, checkpoint.projected_at = content_hash, captured
        db.flush()
        return order
