"""Exact inspection evidence and transactional presale completion.

Writers lock Invoice before the outbound synchronization mutex and inspection.
Supplier documents remain drafts; recall never releases financial allocations.
"""
from decimal import Decimal, InvalidOperation

from app.core.time import beijing_now
from app.invoice.models import Invoice
from app.invoice.settlement_models import ShipmentOutbound, ShipmentSettlement, SettlementApplication, SettlementEvent
from app.shipping_inspection import outbound_service, outbound_sync_state
from app.shipping_inspection.models import ShippingInspection, ShippingOperationEvent


def lock_for_record(db, record_id):
    record = outbound_service.get_outbound_record(db, str(record_id))
    remote_id = record.get('outbound_invoice_id') if record else None
    if not remote_id:
        return None
    locator = db.query(ShipmentOutbound.id, ShipmentOutbound.invoice_id).filter_by(remote_id=str(remote_id)).first()
    if not locator:
        return None
    invoice = db.query(Invoice).filter_by(id=locator.invoice_id).populate_existing().with_for_update().one()
    if invoice.order_type != 'presale':
        return None
    target = db.query(ShipmentOutbound).filter_by(id=locator.id).populate_existing().with_for_update().one()
    if target.remote_id != str(remote_id):
        raise ValueError('检验对应的出库任务已变化，请刷新')
    db.query(ShipmentSettlement).filter_by(id=target.settlement_id).populate_existing().with_for_update().one()
    return target


def snapshot(db, outbound, *, current=False, remote_id=None):
    """Fingerprint includes edit round, mutex and exact frozen line associations."""
    from app.invoice.settlement_service import digest
    identity = remote_id or outbound.remote_id
    record = outbound_service.get_record_by_outbound_invoice_id(db, identity) if identity else None
    if not record:
        return ('missing', False)
    record_id = str(record['outbound_record_id'])
    events = db.query(ShippingOperationEvent).filter_by(scope=outbound_sync_state.SCOPE, request_id=record_id)
    inspections = db.query(ShippingInspection).filter_by(outbound_record_id=record_id)
    if current:
        events = events.populate_existing().with_for_update()
        inspections = inspections.populate_existing().with_for_update()
    event, inspection = events.first(), inspections.first()
    result = (event.result or {}) if event else {}
    overlay = outbound_sync_state.overlay(db, record, event=event)
    rows = (overlay or {}).get('items') if overlay else outbound_service.inspection_item_links(db, record_id)
    rows = rows or []
    fingerprint = digest([record, rows, event.action if event else None, result,
        [inspection.id, inspection.edit_version, inspection.status] if inspection else None])
    blocked = bool(event and (event.action in outbound_sync_state.BLOCKED or result.get('required_recheck_ids')))
    complete = bool(inspection and inspection.status == 'submitted' and not blocked)
    invoice = db.get(Invoice, outbound.invoice_id)
    if (not complete or record['outbound_no'] != outbound.outbound_no or invoice is None
            or str(record.get('company_id')) != str(invoice.customer_id)):
        return (fingerprint, False)
    try:
        def signature(items, *, mirror=False):
            return sorted((str(item['order_id']), str(item['order_record_id']), str(item['product_id']),
                str(item['sku_id']), Decimal(str(item['qty' if mirror and overlay else 'outbound_count']))) for item in items)
        expected = signature(outbound.payload['record_list'])
        actual = signature(rows, mirror=True)
        complete = actual == expected and len({x[:2] for x in actual}) == len(actual)
    except (KeyError, TypeError, ValueError, InvalidOperation):
        complete = False
    return (fingerprint, complete)


def apply(db, outbound, settlement, complete, *, funded=True, actor_id=None, basis='inspection', bump=True):
    """Apply current physical evidence without releasing goods or cash on recall."""
    status = 'shipped' if funded else 'shipped_unfunded'
    state = 'shipped' if funded else 'outbound_uncertain'
    error = None if funded else '检验已提交，但关联回款未通过核验，请立即核查'
    if not complete:
        status, state, error = 'pending_remote', 'outbound_pending', None
    changed = (outbound.status, settlement.state, outbound.last_error) != (status, state, error)
    outbound.status, settlement.state, outbound.last_error = status, state, error
    outbound.verified_at = beijing_now()
    if complete and funded:
        applications = db.query(SettlementApplication).filter_by(settlement_id=settlement.id).order_by(
            SettlementApplication.id).populate_existing().with_for_update().all()
        for application in applications:
            if application.status == 'reserved':
                application.status = 'applied'
    if changed:
        if bump:
            outbound.version += 1
            settlement.version += 1
        db.add(SettlementEvent(settlement_id=settlement.id,
            action='inspection_submitted' if complete else 'inspection_recalled',
            actor_id=actor_id, reason=basis))


def sync_record(db, outbound, *, actor_id=None):
    """Submission/recall already owns Invoice and the inspection mutex. No IO."""
    if outbound is None or outbound.status not in {'pending_remote', 'shipped', 'shipped_unfunded', 'confirm_uncertain'}:
        return
    from app.invoice.shipment_delivery import _funded
    db.flush()
    proof, complete = snapshot(db, outbound, current=True)
    settlement = db.query(ShipmentSettlement).filter_by(id=outbound.settlement_id).populate_existing().with_for_update().one()
    funded = True
    if complete:
        try:
            funded = _funded(db, settlement, current=True)
        except ValueError:
            funded = False
    apply(db, outbound, settlement, complete, funded=funded,
        actor_id=actor_id, basis='inspection:' + proof)
