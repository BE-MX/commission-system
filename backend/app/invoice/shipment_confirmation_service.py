"""Decode historical status-two confirmation payloads for immutable fact recovery.

New outbound completion is handled by shipment_inspection_service; this module
performs no supplier writes and exposes no confirmation command.
"""
from decimal import Decimal
from app.core.time import beijing_now
from app.invoice import outbound_reconciliation_service as reconciliation


def confirmation_payload(frozen):
    payload=frozen.target.payload;baseline=frozen.target.remote_line_snapshot;seen=set();lines=[]
    for line in payload['record_list']:
        previous=baseline[str(line['order_record_id'])];identity=reconciliation._canonical(previous['outbound_record_id'])
        if identity in seen:raise ValueError('小满待出库明细 ID 重复，不能确认实际出库')
        seen.add(identity);cost=Decimal(str(previous['cost_unit_price_rmb']))
        if not cost.is_finite() or cost<0:raise ValueError('原成本基线无效')
        lines.append({**line,'outbound_record_id':int(identity),'cost_unit_price_rmb':float(cost)})
    return {**payload,'record_list':lines,'outbound_invoice_id':int(frozen.target.remote_id),'status':2,
        'warehouse_invoice_time':beijing_now().strftime('%Y-%m-%d %H:%M:%S')}
