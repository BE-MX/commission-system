"""Funding evidence for an existing inspected batch, independent of the next edit."""
from app.invoice.models import InvoiceItem
from app.invoice.settlement_contract import _id, _number, _quantity
from app.invoice.settlement_models import Receivable, SettlementApplication, SettlementItem
from app.invoice.settlement_service import digest
from app.receipt import remote
from app.receipt.models import Receipt, ReceiptIntent


def snapshot(db, invoice, settlement, outbound):
    """Only the already verified outbound may use its frozen commercial lines.

    The next batch can change the current order total before its push. That is
    not evidence of a refund on this batch. All receipt and allocation checks
    still use the full current remote lists in shipment_delivery._live_funding.
    """
    payload = outbound.payload
    if (invoice.order_type != 'presale' or not outbound.remote_id
            or outbound.invoice_id != invoice.id or settlement.invoice_id != invoice.id
            or outbound.settlement_id != settlement.id or not isinstance(payload, dict)
            or outbound.payload_hash != digest(payload)
            or str(payload.get('company_id')) != str(invoice.customer_id)
            or payload.get('currency') != invoice.currency
            or str(settlement.quote.get('customer_id')) != str(invoice.customer_id)
            or settlement.quote.get('currency') != invoice.currency):
        raise ValueError('原批次冻结身份已变化，资金待核验')
    main = remote.read(db, '/v1/invoices/order/info', {'order_id':invoice.xiaoman_order_id})
    if (not isinstance(main, dict)
            or str(main.get('order_id')) != str(invoice.xiaoman_order_id)
            or str(main.get('company_id')) != str(invoice.customer_id)
            or main.get('currency') != invoice.currency
            or not remote.order_active(db, main)):
        raise ValueError('原批次主单身份或有效状态已变化')
    observed_total = remote.money(main.get('amount'))
    lines, frozen = main.get('product_list'), payload.get('record_list')
    if not isinstance(lines, list) or not isinstance(frozen, list) or not frozen:
        raise ValueError('原批次主单明细不完整')
    indexed = {}
    for line in lines:
        identity = _id(line.get('unique_id'), '原订单明细 ID')
        if identity in indexed:
            raise ValueError('原订单明细 ID 重复')
        indexed[identity] = line
    local_lines = db.query(InvoiceItem).filter_by(invoice_id=invoice.id).all()
    batch_lines = db.query(SettlementItem).filter_by(settlement_id=settlement.id).all()
    seen = set()
    for line in frozen:
        identity = _id(line.get('order_record_id'), '冻结订单明细 ID')
        actual = indexed.get(identity)
        if identity in seen or actual is None:
            raise ValueError('原批次明细缺失或重复')
        seen.add(identity)
        if (str(line.get('order_id')) != str(invoice.xiaoman_order_id)
                or _id(actual.get('product_id'), '产品 ID') != _id(line.get('product_id'), '冻结产品 ID')
                or _id(actual.get('sku_id'), 'SKU ID') != _id(line.get('sku_id'), '冻结 SKU ID')
                or _quantity(actual.get('count')) < _quantity(line.get('outbound_count'))
                or _number(actual.get('unit_price'), '销售单价') != _number(line.get('sale_price'), '冻结销售单价')):
            raise ValueError('原批次产品、数量或价格已变化')
        original = [item for item in local_lines if str(item.xiaoman_unique_id) == str(identity)]
        selected = [item for item in batch_lines if str(item.snapshot.get('order_record_id')) == str(identity)]
        if (len(original) != 1 or len(selected) != 1
                or selected[0].invoice_item_id != original[0].id
                or selected[0].quantity != _quantity(line.get('outbound_count'))):
            raise ValueError('原批次成交金额缺少唯一历史明细依据')
        item = original[0]
        # Before the next push the provider can still show the original whole
        # line; after it, the same UID can show only its archived shipped part.
        # Match complete quantity/amount pairs, never a rounded per-batch slice.
        amounts = {(_quantity(item.quantity), remote.money(item.total_price))}
        if item.presale_archived and item.presale_shipped_quantity:
            amounts.add((_quantity(item.presale_shipped_quantity), remote.money(item.presale_shipped_amount)))
        if (_quantity(actual.get('count')), remote.money(actual.get('cost_amount'))) not in amounts:
            raise ValueError('原批次成交金额或历史数量已变化')
    return {'rows':remote.order_receipts(db, invoice.xiaoman_order_id),
        'exchange_rate':main.get('exchange_rate'), 'invoice_binding':remote.invoice_binding(invoice),
        'observed_order_amount':str(observed_total)}, main


def binding(db, invoice, settlement, outbound, *, current=False):
    """Recheck the local order and complete funding graph after unlocked reads."""
    def state(row):
        return {column.name:getattr(row, column.name) for column in row.__table__.columns}
    graph = [state(invoice), state(settlement), state(outbound)]
    for model, condition in (
        (InvoiceItem, InvoiceItem.invoice_id == invoice.id),
        (SettlementItem, SettlementItem.settlement_id == settlement.id),
        (SettlementApplication, SettlementApplication.settlement_id == settlement.id),
        (Receivable, Receivable.settlement_id == settlement.id),
        (Receipt, Receipt.invoice_id == invoice.id),
        (ReceiptIntent, ReceiptIntent.invoice_id == invoice.id),
    ):
        query = db.query(model).filter(condition).order_by(model.id).populate_existing()
        if current:
            query = query.with_for_update()
        graph.append([state(row) for row in query.all()])
    return digest(graph)
