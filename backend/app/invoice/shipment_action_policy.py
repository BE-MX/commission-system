"""Shared local action rules for settlement commands and their UI facts."""
from app.invoice.presale_runtime import POOL_PURPOSES
from app.invoice.shipment_cancellation_policy import CANCELLED_STATES


def failed_outbound_candidate(row, outbound):
    """Local eligibility only. Provider absence is still required to apply."""
    if not (row.state == 'review_required' and outbound is not None and outbound.status == 'failed'
            and not outbound.remote_id and outbound.lease_until is None
            and outbound.remote_line_snapshot is None):
        return False
    from app.invoice.settlement_service import digest
    return (isinstance(outbound.payload, dict) and bool(outbound.outbound_no)
        and outbound.payload.get('serial_id') == outbound.outbound_no
        and digest(outbound.payload) == outbound.payload_hash)


def action_reason(row, action, *, outbound, freight, applications, receipts, late_result=False):
    if action not in {'cancel', 'pause', 'resume'}:
        return '无效的结算状态变更'
    failed_cancel = action == 'cancel' and failed_outbound_candidate(row, outbound)
    if row.state in {'shipped', *CANCELLED_STATES, 'outbound_uncertain', 'review_required'} and not failed_cancel:
        return '当前结算状态不能执行此操作'
    if outbound and not failed_cancel:
        return '已有出库任务，请先核实远端效果'
    if freight and freight.remote_status in {'sending', 'verifying', 'uncertain'}:
        return '运费目标正在发送或结果待核对，请先核实远端效果'
    active = [app for app in applications if app.status != 'released']
    if any(receipts[app.receipt_id].sync_status in {'syncing', 'uncertain'} for app in active):
        return '本批回款正在发送或结果待核对，请先核实远端效果'
    if action in {'cancel', 'resume'} and late_result:
        return '本批存在迟到回款结果，请先核对原效果；暂不能取消或恢复'
    if action == 'cancel':
        paid = any(app.component != 'deposit' and receipts[app.receipt_id].purpose not in POOL_PURPOSES
                   for app in active)
        if paid or (freight and (freight.remote_order_id or freight.remote_status == 'bound')):
            return '已有真实付款或运费目标，仅支持原批暂停/恢复'
    if action == 'pause' and row.state == 'paused':
        return '本批已暂停；继续原批次请恢复，重新安排请取消本批次'
    if action == 'resume' and row.state != 'paused':
        return '仅已暂停的批次支持恢复'
    return ''
