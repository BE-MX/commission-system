"""Cancelled goods can retain one fully funded, already bound freight target."""
from decimal import Decimal

CANCELLED_KEEP_FREIGHT = 'cancelled_keep_freight'
CANCELLED_STATES = ('cancelled', CANCELLED_KEEP_FREIGHT)


def validate_retained(row, applications, receipts, freight):
    if (row.quote.get('funding_version') != 2 or freight is None
            or freight.remote_status != 'bound' or not freight.remote_order_id
            or freight.settlement_id != row.id or freight.invoice_id != row.invoice_id
            or freight.currency != row.quote['currency']
            or str(freight.customer_id) != str(row.quote['customer_id'])
            or Decimal(freight.amount) != Decimal(row.quote['freight_amount'])
            or Decimal(freight.amount) <= 0):
        raise ValueError('保留运费目标与原批次不一致，请核对原单')
    expected = sorted((part['receipt_id'], part['component'], Decimal(part['amount']),
        Decimal(part['bank_charge']), part['purpose']) for part in row.quote['pool_applications'])
    historical = {(identity, component): purpose for identity, component, _, _, purpose in expected}
    actual = sorted((app.receipt_id, app.component, Decimal(app.amount), Decimal(app.bank_charge),
        historical.get((app.receipt_id, app.component), receipts[app.receipt_id].purpose)
        if app.status == 'released' else receipts[app.receipt_id].purpose) for app in applications)
    if actual != expected:
        raise ValueError('保留运费的原资金分配已变化，请核对原单')
    total = Decimal(0)
    for app in applications:
        if app.component == 'freight':
            receipt = receipts[app.receipt_id]
            if (app.status != 'applied' or receipt.purpose != 'presale_advance'
                    or app.bank_charge or receipt.status != 'active'):
                raise ValueError('保留运费抵扣异常，请核对原单')
            total += app.amount
        elif app.status != 'released':
            raise ValueError('已撤销商品仍有未释放资金，请核对原单')
    if total != Decimal(freight.amount):
        raise ValueError('保留运费未足额抵扣，请核对原单')


def retained_rows(db, invoice_id, *, current=False):
    from app.invoice.settlement_models import ShipmentSettlement
    query = db.query(ShipmentSettlement).filter(ShipmentSettlement.invoice_id == invoice_id,
        ShipmentSettlement.state == CANCELLED_KEEP_FREIGHT).order_by(ShipmentSettlement.id)
    return (query.populate_existing().with_for_update() if current else query).all()


def replacement_freight(db, invoice, *, current=False):
    from app.invoice.settlement_models import ShipmentSettlement
    query = db.query(ShipmentSettlement).filter_by(invoice_id=invoice.id).order_by(ShipmentSettlement.id)
    rows = (query.populate_existing().with_for_update() if current else query).all()
    claimed = {row.quote.get('retained_freight_settlement_id') for row in rows
        if row.state not in CANCELLED_STATES}
    available = [row for row in rows if row.state == CANCELLED_KEEP_FREIGHT and row.id not in claimed]
    if len(available) > 1:
        raise ValueError('存在多笔待沿用的保留运费，请先核对原批次')
    return available[0] if available else None
