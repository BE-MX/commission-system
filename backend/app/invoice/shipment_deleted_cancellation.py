"""Retire an exact deleted supplier outbound; never sends supplier mutations."""
from dataclasses import dataclass
from decimal import Decimal
import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.time import beijing_now
from app.invoice import okki_client, settlement_service as shipments, shipment_state_service as states
from app.invoice import shipment_confirmation_recovery as confirmation, shipment_creation_facts as facts
from app.invoice import shipment_retry_service, shipment_cancellation_policy as policy
from app.invoice.settlement_models import SettlementEvent
from app.invoice.settlement_policy import require_delivery
from app.invoice.stock_reservations import fenced
from app.receipt import access, authority, remote
from app.shipping_inspection import outbound_service, outbound_delete_client, outbound_presence
from app.shipping_inspection.models import ShippingInspection, ShippingOperationEvent

logger = logging.getLogger(__name__)


def _inspection(db, target, *, current=False):
    record = outbound_service.get_record_by_outbound_invoice_id(db, target.remote_id, include_deleted=True)
    if not record:
        raise ValueError('原出库镜像资料不完整，不能自动释放批次')
    rid = str(record['outbound_record_id'])
    query = select(ShippingInspection).where(ShippingInspection.outbound_record_id == rid).order_by(ShippingInspection.id)
    events = select(ShippingOperationEvent).where(ShippingOperationEvent.outbound_record_id == rid).order_by(ShippingOperationEvent.id)
    if current:
        query = query.with_for_update().execution_options(populate_existing=True)
        events = events.with_for_update().execution_options(populate_existing=True)
    inspections, operations = db.scalars(query).all(), db.scalars(events).all()
    if (any(row.status == 'submitted' or row.submitted_at or row.recalled_at for row in inspections)
            or any(row.action in {'submit', 'recall'} for row in operations)):
        raise ValueError('原批次存在检验提交或撤回历史，请先人工核实实物出库，不能自动撤销')
    from app.shipping_inspection import outbound_sync_state
    if any(row.scope == outbound_sync_state.SCOPE and row.action in outbound_sync_state.BLOCKED for row in operations):
        raise ValueError('原出库资料正在同步或待核对，不能撤销批次')
    values = [[getattr(row, col.name) for col in type(row).__table__.columns]
        for row in inspections + operations]
    return rid, shipments.digest([record, values])


def action(db, row, target, freight, applications, receipts, *, current=False):
    reason = ''
    keep = bool(freight and freight.remote_order_id)
    if (row.state not in {'outbound_pending', 'outbound_uncertain'} or target is None
            or target.status not in {'pending_remote', 'uncertain'} or not target.remote_id
            or target.lease_until is not None or target.invoice_id != row.invoice_id
            or target.settlement_id != row.id):
        reason = '仅已生成、尚未出库且发送已停止的原批次支持核实删除后撤销'
    elif (not isinstance(target.payload, dict) or target.payload.get('serial_id') != target.outbound_no
            or shipments.digest(target.payload) != target.payload_hash):
        reason = '原出库编号或冻结快照不完整，请核对原单'
    elif row.quote.get('funding_version') != 2:
        reason = '历史资金版本须先人工核对，不能自动释放'
    elif Decimal(row.quote.get('freight_amount', '0')) > 0 and freight is None:
        reason = '原批次运费目标缺失，请先核对原运费'
    elif any(app.status != 'released' and (receipts[app.receipt_id].purpose not in {'presale_advance', 'presale_deposit'}
            or receipts[app.receipt_id].sync_status in {'syncing', 'uncertain'}) for app in applications):
        reason = '本批存在独立付款或回款发送未决，请先核对原款'
    elif freight and (freight.remote_status in {'sending', 'verifying', 'uncertain'} or freight.lease_until is not None):
        reason = '运费目标正在发送或结果待核对，请先核对原运费'
    elif freight and ((freight.remote_status == 'bound') != bool(freight.remote_order_id)
            or not keep and freight.remote_status not in {'unverified', 'failed'}):
        reason = '原运费状态与远端身份不一致，请先核对原运费'
    elif keep and (freight.remote_status != 'bound' or Decimal(freight.amount) <= 0
            or sum((app.amount for app in applications if app.component == 'freight' and app.status != 'released'),
                Decimal(0)) != Decimal(freight.amount)):
        reason = '已有运费订单必须足额保留原抵扣，请先核对运费'
    if not reason:
        try:
            journal = confirmation.capture(db, target, current=current)
            if journal.histories or journal.proven_shipped or facts.late_results(db, target.id, current=current):
                reason = '原批次存在实际出库确认历史或迟到结果，请先核对原单'
        except HTTPException as error:
            if error.status_code != 409:
                raise
            reason = '原实际出库确认事实不完整，请先人工核对原单'
        except (ValueError, TypeError, KeyError):
            reason = '原实际出库确认事实不完整，请先人工核对原单'
    return {'allowed': not bool(reason), 'reason': reason, 'keep_freight': keep,
        'retained_freight_amount': str(freight.amount) if keep else '0.00'}


@dataclass(frozen=True)
class Original:
    invoice_id: int
    settlement_id: int
    target_id: int
    remote_id: str
    serial: str
    row_version: int
    fingerprint: str
    inspection: str
    creation: str
    record_id: str
    keep_freight: bool
    freight_id: int | None
    freight_remote_id: str | None
    freight_amount: str
    customer_id: str
    currency: str


def _capture(db, identity, body, user):
    invoice, row, graph, current = states._authorize(db, identity, user, 'cancel')
    if row.version != body.version:
        raise ValueError('原批次已变化，请刷新后重新核实删除')
    target = graph.outbound
    permitted = action(db, row, target, graph.freight, graph.applications, graph.receipts, current=True)
    if not permitted['allowed']:
        raise ValueError(permitted['reason'])
    record_id, inspection = _inspection(db, target, current=True)
    # Exact original allocation and live current receipt effectiveness.
    from app.invoice import presale_runtime, shipment_payment_policy
    presale_runtime.pool_lots(db, invoice, current=True)
    presale_runtime.validate_quote_applications(row, graph.applications, graph.receipts)
    if permitted['keep_freight'] and any(not shipment_payment_policy.receipt_effective(graph.receipts[app.receipt_id])
            for app in graph.applications if app.component == 'freight' and app.status != 'released'):
        raise ValueError('保留运费的回款尚未生效，请先核对')
    original = Original(invoice.id, row.id, target.id, target.remote_id, target.outbound_no,
        row.version, shipment_retry_service._binding(db, invoice, row), inspection,
        facts.fingerprint(db, target.id, current=True), record_id, permitted['keep_freight'],
        graph.freight.id if graph.freight else None,
        graph.freight.remote_order_id if graph.freight else None, permitted['retained_freight_amount'],
        str(invoice.customer_id), invoice.currency)
    return invoice, row, graph, current, original


def _observe(db, original):
    token = okki_client.ensure_access_token(db)
    detail = outbound_delete_client._request(token, original.remote_id)
    found = okki_client.find_outbound_by_serial(db, original.serial)
    if found is not None:
        if (not isinstance(found, dict) or found.get('serial_id') != original.serial
                or str(found.get('outbound_invoice_id')) != original.remote_id):
            raise ValueError('小满存在相同编号的另一张出库单，请先核对替代单')
        # ID and serial reads can disagree for a soft deletion. A readable
        # serial result still requires complete active-list absence proof.
        if detail is None:
            detail = found
    if detail is not None:
        if (detail.get('serial_id') != original.serial
                or str((detail.get('company_info') or {}).get('id')) != original.customer_id):
            raise ValueError('小满原出库身份已变化，不能撤销')
        if str(detail.get('status')) != '1':
            raise ValueError('原出库单曾为已出库状态，请先核对实物')
        start = outbound_presence.creation_floor(detail.get('create_time'))
        if outbound_presence.is_active(token, original.remote_id, start):
            raise ValueError('小满原出库单仍有效，请先在小满删除后重新核实')
    freight_evidence = None
    if original.keep_freight:
        from app.invoice.freight_reconciliation_service import FreightTarget, _read_evidence
        from app.invoice.settlement_models import Receivable
        target = db.get(Receivable, original.freight_id)
        lookup = FreightTarget(target.id, target.remote_order_id, target.remote_order_name,
            target.customer_id, target.currency, Decimal(target.amount))
        evidence = _read_evidence(db, lookup)
        if not evidence.active or not evidence.matches:
            raise ValueError('原运费订单已变化，不能宣称保留原运费')
        freight_evidence = remote.target_snapshot(db, target)
        # Recheck the original source payment amounts against the provider.
        from app.invoice.models import Invoice
        goods = remote.order_snapshot(db, db.get(Invoice, original.invoice_id))
    else:
        goods = None
    return {'remote_id': original.remote_id, 'serial_id': original.serial,
        'result': 'verified_deleted', 'observed_at': beijing_now().isoformat(),
        'freight': freight_evidence, 'goods': goods}


def _apply(db, row, graph, current, original, proof, reason):
    if original.keep_freight:
        from app.receipt.balance import calculate_target
        if Decimal(calculate_target(db, graph.freight, proof['freight'], current=True)['remaining_amount']):
            raise ValueError('原运费抵扣未足额，不能保留')
        summary = shipments.goods_balance(db, db.get(shipments.Invoice, row.invoice_id), proof['goods'], current=True)
        effective = {part['receipt_id'] for part in summary['pool_balances'] if part['effective']}
        if any(app.component == 'freight' and app.receipt_id not in effective for app in graph.applications):
            raise ValueError('原运费的资金来源未通过小满实时核验，不能保留抵扣')
    released = Decimal(0)
    for app in graph.applications:
        if app.status == 'released':
            continue
        if original.keep_freight and app.component == 'freight':
            app.status = 'applied'
        else:
            released += app.amount
            app.status = 'released'
    row.state = policy.CANCELLED_KEEP_FREIGHT if original.keep_freight else 'cancelled'
    row.version += 1
    graph.outbound.status = 'cancelled'
    graph.outbound.version += 1
    data = {'invoice_id': row.invoice_id, 'settlement_id': row.id,
        'remote_id': original.remote_id, 'serial_id': original.serial,
        'released_amount': str(released), 'retained_freight_amount': original.freight_amount,
        'freight_remote_id': original.freight_remote_id, 'observation': proof}
    # Do not put raw payment responses into immutable public audit records.
    data['observation'] = {k: proof[k] for k in ('remote_id', 'serial_id', 'result', 'observed_at')}
    facts.append(db, original.target_id, facts.PREFIX + 'cancelled', str(original.row_version),
        data, actor_id=access.user_id(current), reason=reason)
    event = db.scalar(select(ShippingOperationEvent).where(ShippingOperationEvent.scope == 'outbound-delete',
        ShippingOperationEvent.request_id == original.remote_id).with_for_update()
        .execution_options(populate_existing=True))
    if event and event.action not in {'outbound_deleted', 'delete_failed'}:
        raise ValueError('原单存在未完成的删除请求，请先完成删除核对')
    if event is None:
        name = current.get('real_name') or current.get('username') or str(access.user_id(current))
        db.add(ShippingOperationEvent(scope='outbound-delete', request_id=original.remote_id,
            source='invoice', action='outbound_deleted', outbound_record_id=original.record_id,
            operator_user_id=access.user_id(current), login_user_id=access.user_id(current),
            operator_name=name, login_name=name, payload=data,
            result={'status': 'outbound_deleted', 'message': '已核实小满删除并撤销原批次'}))
    elif event.action == 'delete_failed':
        event.action = 'outbound_deleted'
        event.result = {'status': 'outbound_deleted', 'message': '已核实外部删除并撤销原批次'}
    db.add(SettlementEvent(settlement_id=row.id, action='cancel_deleted',
        actor_id=access.user_id(current), reason=reason))
    db.flush()
    if original.keep_freight:
        policy.validate_retained(row, graph.applications, graph.receipts, graph.freight)


def _cancel_under_fence(db, identity, body, user):
    require_delivery()
    _, _, _, _, original = _capture(db, identity, body, user)
    db.commit()
    try:
        proof = _observe(db, original)
        db.commit()
    finally:
        db.rollback()
        db.expire_all()
    _, row, graph, current, actual = _capture(db, identity, body, user)
    if actual != original:
        raise ValueError('原批次、权限、资金或检验资料在核验期间变化，请刷新后重试核实')
    _apply(db, row, graph, current, original, proof, body.reason)
    result = shipments.describe(db, row, current=True)
    db.commit()  # Keep the executor fence until every release is durable.
    return result


@fenced
def _cancel(db, identity, body, user):
    try:
        return _cancel_under_fence(db, identity, body, user)
    except BaseException:
        db.rollback()  # Roll back before releasing the shared executor fence.
        raise


def cancel(db, identity, body, user):
    authority.fresh_boundary(db)
    try:
        return _cancel(db, identity, body, user)
    except (outbound_delete_client.DeleteRemoteError, outbound_presence.PresenceError,
            okki_client.OkkiApiError, SQLAlchemyError, OSError, RuntimeError) as error:
        db.rollback()
        states.result_unavailable(error)
    except ValueError as error:
        db.rollback()
        logger.warning('Deleted shipment cancellation rejected (%s)', type(error).__name__)
        print('[shipment] deleted cancellation rejected', flush=True)
        raise HTTPException(409, str(error)) from None
    except HTTPException:
        db.rollback()
        raise
