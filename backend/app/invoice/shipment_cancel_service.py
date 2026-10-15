"""Cancel a definite failed creation only after unlocked exact-serial GET proof."""
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.invoice import okki_client, settlement_service as shipments
from app.invoice import shipment_confirmation_recovery, shipment_state_service as states
from app.invoice.settlement_models import SettlementEvent
from app.invoice.shipment_action_policy import action_reason, failed_outbound_candidate
from app.receipt import access


@dataclass(frozen=True)
class OriginalFailure:
    settlement_id: int
    task_id: int
    serial: str
    task_version: int
    binding: str
    confirmation: str


def _capture(db, captured, version):
    invoice, row, graph, current = captured
    if row.version != version:
        raise HTTPException(409, '结算已变化，请刷新后核对原批次')
    blocked = action_reason(row, 'cancel', outbound=graph.outbound, freight=graph.freight,
        applications=graph.applications, receipts=graph.receipts)
    if blocked:
        raise HTTPException(409, blocked)
    target = graph.outbound
    if not failed_outbound_candidate(row, target):
        raise HTTPException(409, '仅明确失败且没有远端出库事实的任务支持取消')
    journal = shipment_confirmation_recovery.capture(db, target, current=True)
    if journal.histories or journal.proven_shipped:
        raise HTTPException(409, '原任务存在出库确认历史，请先核对原单，不能取消重建')
    # Reuse the existing full invoice/financial/task fingerprint. No row locks
    # or mutable ORM objects cross the external read boundary.
    from app.invoice.shipment_retry_service import _binding
    return OriginalFailure(row.id, target.id, target.outbound_no, target.version,
        _binding(db, invoice, row), journal.fingerprint)


def _exists(db, serial):
    found = okki_client.find_outbound_by_serial(db, serial)
    # The HTTP helper maps only its exact observed canonical missing response
    # to None. Empty/malformed responses never qualify as an absence proof.
    if found is None:
        return False
    if isinstance(found, dict) and found.get('outbound_invoice_id') and found.get('serial_id') == serial:
        return True
    raise ValueError('原出库编号查询结果不完整')


def cancel_failed(db, captured, user, version, reason):
    original = _capture(db, captured, version)
    db.commit()  # Read-only authorization and capture; release business locks.
    try:
        exists = _exists(db, original.serial)
        db.commit()  # Only provider credential metadata may have changed.
    except (ValueError, TypeError, OSError, HTTPException, SQLAlchemyError) as error:
        states.result_unavailable(error)
    finally:
        transaction = db.get_transaction()
        if transaction is not None and not transaction.is_active:
            db.close()
        else:
            db.rollback()
        db.expire_all()
    current_capture = states._authorize(db, original.settlement_id, user, 'cancel')
    actual = _capture(db, current_capture, version)
    if actual != original:
        raise HTTPException(409, '核验期间订单、资金或出库任务已变化，请刷新原批次')
    if exists:
        raise HTTPException(409, '小满已有同编号出库单，请先核对原单，不能取消重建')
    _, row, graph, current = current_capture
    shipments._change_state_verified(db, row, current, 'cancel', version, reason, graph,
        failed_outbound_absent=True)
    # Preserve all 500 characters of the user's reason on the normal cancel
    # event. Record the server-observed absence separately, without a POST.
    db.add(SettlementEvent(settlement_id=row.id, action='cancel_verified',
        actor_id=access.user_id(current), reason=(
            f'小满精确编号 GET 确认无单；原失败任务 ID={original.task_id}, '
            f'version={original.task_version}, serial={original.serial}；未发送远端写入')))
    db.flush()
    return shipments.describe(db, row, current=True)
