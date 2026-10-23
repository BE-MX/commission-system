"""Employee-attested terminal absence recovery; never sends supplier writes.

Canonical GET absence is a current observation, not proof that an unknown
request cannot finish later. The original request's terminal fact is supplied
by a currently authorized employee, explicitly bound to the viewed attempt.
"""
from dataclasses import dataclass
import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.time import beijing_now
from app.invoice import edit_authority, okki_client, settlement_service as shipments
from app.invoice import shipment_confirmation_recovery as confirmation
from app.invoice import shipment_creation_facts as facts, shipment_retry_service, shipment_state_service as states
from app.invoice.lifecycle_guard import ensure_active
from app.invoice.settlement_models import ShipmentSettlement, SettlementEvent
from app.invoice.settlement_policy import require_delivery
from app.invoice.stock_reservations import fenced
from app.portal.authority import lock_authority
from app.portal.errors import PortalError, TransactionBusy
from app.receipt import access, authority, service as receipts
from app.receipt.models import ReceiptLog

logger = logging.getLogger(__name__)


def _end_transaction(db):
    transaction = db.get_transaction()
    if transaction is not None and not transaction.is_active:
        db.close()
    else:
        db.rollback()


def action(db, row, target, *, current=False, confirmation_summary=None):
    reason = ''
    if (row.state != 'outbound_uncertain' or target is None or target.status != 'uncertain'
            or target.invoice_id != row.invoice_id or target.settlement_id != row.id
            or target.remote_id or target.remote_line_snapshot is not None or target.lease_until is not None):
        reason = '仅原创建结果待核对、无远端单据且发送已停止的任务支持恢复'
    elif (not target.payload or target.payload.get('serial_id') != target.outbound_no
            or shipments.digest(target.payload) != target.payload_hash):
        reason = '原出库编号或冻结快照不完整，请核对原单'
    else:
        summary = confirmation_summary or confirmation.summary(db, target, current=current)
        if summary['state'] != 'none' or summary['attempt_count'] != 0:
            reason = '原任务存在实际出库确认历史，不能恢复创建'
        elif facts.late_results(db, target.id, current=current):
            reason = '已记录迟到的小满出库结果，请核对并绑定原单'
    result = {'allowed': not bool(reason), 'reason': reason, 'requires_terminal_confirmation': True}
    if not reason:
        # Binds an employee's external terminal declaration to the viewed
        # attempt, without exposing the executor's attempt token to the client.
        result['version'] = shipments.digest([row.id, row.invoice_id, row.version, target.id,
            target.version, target.attempt_token, target.outbound_no, target.payload_hash])
    return result


@dataclass(frozen=True)
class OriginalAttempt:
    target_id: int
    serial_id: str
    token: str | None
    target_version: int
    payload_hash: str
    binding: str
    confirmation: str
    creation_facts: str


def _capture(db, identity, body, user):
    authority.fresh_boundary(db)
    try:
        lock_authority(db, force=True)
        current = authority.current_user(db, user, 'shipment:write', 'shipment:admin')
        invoice_id = db.scalar(select(ShipmentSettlement.invoice_id).where(ShipmentSettlement.id == identity))
        if invoice_id is None:
            raise HTTPException(404, '订单或发货结算不存在')
        invoice = edit_authority.lock_document(db, invoice_id, force=True)
        if invoice is None:
            raise HTTPException(404, '订单或发货结算不存在')
        db.refresh(invoice, with_for_update=True)
        access.ensure_invoice(db, invoice, current)
        ensure_active(invoice)
        receipts.ensure_order_ready(db, invoice, current=True)
        if invoice.order_type != 'presale' or invoice.shipping_fee:
            raise ValueError('仅主单运费为零的预售单支持发货结算')
        row, graph = states._capture(db, invoice, identity, 'recover_outbound')
        target = graph.outbound
        allowed = action(db, row, target, current=True)
        if not allowed['allowed']:
            raise ValueError(allowed['reason'])
        if row.version != body.version or allowed['version'] != body.recovery_version:
            raise ValueError('原出库尝试已变化，请刷新后重新核实原请求')
        active_receipts = {app.receipt_id for app in graph.applications if app.status != 'released'}
        if db.scalar(select(ReceiptLog.id).where(ReceiptLog.receipt_id.in_(active_receipts),
                ReceiptLog.action == 'late_result').limit(1)):
            raise ValueError('本批存在迟到回款结果，请先核对原效果')
        journal = confirmation.capture(db, target, current=True)
        if journal.histories or journal.proven_shipped:
            raise ValueError('原任务存在实际出库确认历史，不能恢复创建')
        shipments.funding_balance(db, row, current=True)
        original = OriginalAttempt(target.id, target.outbound_no, target.attempt_token, target.version,
            target.payload_hash, shipment_retry_service._binding(db, invoice, row),
            journal.fingerprint, facts.fingerprint(db, target.id, current=True))
        return invoice, row, target, current, original
    except TransactionBusy:
        raise
    except PortalError as error:
        raise HTTPException(error.status, '出库恢复授权暂不可用') from None


@fenced
def _recover(db, identity, body, user):
    require_delivery()
    _, row, target, _, original = _capture(db, identity, body, user)
    db.commit()  # Keep the executor fence, release business/authority locks.
    try:
        found = okki_client.find_outbound_by_serial(db, original.serial_id)
        if found is not None and (not isinstance(found, dict) or not found.get('outbound_invoice_id')
                or found.get('serial_id') != original.serial_id):
            raise okki_client.OkkiApiError('Original outbound observation is incomplete')
        observed_at = beijing_now().isoformat()
        db.commit()  # Only credential metadata may have changed.
    except (okki_client.OkkiApiError, SQLAlchemyError, OSError, TypeError) as error:
        states.result_unavailable(error)
    finally:
        _end_transaction(db)
        db.expire_all()
    _, row, target, current, actual = _capture(db, identity, body, user)
    if actual != original:
        raise HTTPException(409, '原出库任务、权限依据或资金在核验期间已变化，请刷新原批次')
    if found is not None:
        raise HTTPException(409, '小满已有原编号出库单，请使用核对出库单绑定原单，不能恢复发送')
    before_version = row.version
    facts.append(db, target.id, facts.RECOVERED, body.recovery_version, {
        'invoice_id': row.invoice_id, 'settlement_id': row.id, 'target_id': target.id,
        'serial_id': original.serial_id, 'attempt_token': original.token,
        'outbound_version': original.target_version, 'settlement_version': before_version,
        'payload_hash': original.payload_hash, 'original_request_closed': body.original_request_closed,
        'terminal_fact_source': 'employee_external_confirmation',
        'resolution_reference': body.resolution_reference,
        'remote_observation': {'serial_id': original.serial_id, 'result': 'canonical_not_found',
            'observed_at': observed_at},
    }, actor_id=access.user_id(current), reason=body.reason)
    target.status = 'pending'
    target.attempt_token = None
    target.lease_until = None
    target.last_error = None
    target.version += 1
    row.state = 'outbound_pending'
    row.version += 1
    db.add(SettlementEvent(settlement_id=row.id, action='recover_outbound',
        actor_id=access.user_id(current), reason=body.reason))
    db.flush()
    result = shipments.describe(db, row, current=True)
    db.commit()  # Commit while still excluding the original executor.
    return result


def recover(db, identity, body, user):
    # Reject an unrelated dirty caller before taking the fence or rolling back.
    authority.fresh_boundary(db)
    try:
        return _recover(db, identity, body, user)
    except ValueError as error:
        _end_transaction(db)
        logger.warning('Shipment absence recovery rejected (%s)', type(error).__name__)
        print('[shipment] absence recovery rejected', flush=True)
        raise HTTPException(409, str(error)) from None
    except (SQLAlchemyError, RuntimeError) as error:
        _end_transaction(db)
        states.result_unavailable(error)
