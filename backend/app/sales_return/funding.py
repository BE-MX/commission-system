"""Read-only limits linking a presale refund to the selected shipped batches.

The caller locks the original invoice, receipt and allocation writers before
activation. This adapter only projects current evidence and never releases funds.
"""
from copy import deepcopy
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import select

from app.invoice.models import Invoice
from app.invoice.settlement_models import ShipmentOutbound, ShipmentSettlement, SettlementApplication
from app.invoice import shipment_payment_policy as payment_policy
from app.receipt.models import Receipt
from app.sales_return.models import ReturnAllocation, SalesReturn

CENT = Decimal('0.01')
ZERO = Decimal(0)


def _conflict(message):
    raise HTTPException(409, message)


def _amount(value, label):
    try:
        result = Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        _conflict(label + '缺失，请核对原结算资金分配')
    if not result.is_finite() or result < 0 or result != result.quantize(CENT):
        _conflict(label + '无效，请核对原结算资金分配')
    return result


def _verify_lines(outbound, selected, order_id):
    payload = outbound.payload if isinstance(outbound.payload, dict) else {}
    rows = payload.get('record_list')
    frozen = outbound.remote_line_snapshot
    if not isinstance(rows, list) or not isinstance(frozen, dict):
        _conflict('旧预售出库缺少精确订单行与远端出库行快照，不能追溯可退资金')
    mapped = {str(row.get('order_record_id')): row for row in rows if isinstance(row, dict)}
    if len(mapped) != len(rows):
        _conflict('原预售出库订单行重复或无效，请核对原批次')
    for line in selected:
        key = str(line['order_line_id'])
        original, remote = mapped.get(key), frozen.get(key)
        if (not original or not isinstance(remote, dict)
                or str(remote.get('outbound_record_id')) != str(line['outbound_line_id'])
                or str(original.get('order_id')) != str(order_id)
                or str(original.get('product_id')) != str(line['product_id'])
                or str(original.get('sku_id')) != str(line['sku_id'])
                or _amount(original.get('outbound_count'), '原批次出库数量') != Decimal(line['quantity'])):
            _conflict('所选出库行与原预售结算冻结映射不一致，不能释放其他批次资金')


def _credit_valid(db, settlement):
    try:
        credit = payment_policy.is_credit(settlement)
    except ValueError as error:
        _conflict(str(error))
    if not credit:
        return False
    quote = settlement.quote
    required = {'goods_amount', 'packaging_amount', 'handling_amount', 'freight_amount', 'funding_total_amount',
        'goods_payment_due', 'goods_payment_charge', 'freight_payment_due', 'new_payment_due', 'deposit_applied'}
    if not required <= quote.keys() or not isinstance(quote.get('pool_applications'), list) or type(quote.get('is_final')) is not bool:
        _conflict('先出库原批次缺少完整冻结的欠款及资金分配依据，请先核对旧批次')
    amounts = {key: _amount(quote[key], '原批次冻结金额') for key in required}
    if amounts['funding_total_amount'] != sum((amounts[key] for key in ('goods_amount', 'packaging_amount', 'handling_amount', 'freight_amount')), ZERO):
        _conflict('先出库原批次商品与费用金额不一致，请先核对冻结欠款')
    if not payment_policy.credit_funding_valid(db, settlement):
        _conflict('先出库原批次欠款或原已生效资金状态待核对，不能据此免除债务或退款')
    return True


def _cash_limits(db, invoice, payments, selected_batches, refunded):
    """Released original cash borrowed by another batch cannot be refunded twice."""
    from app.sales_return.presale_adjustments import projection
    try:
        releases = projection(db, invoice).get('releases', {})
    except ValueError as error:
        _conflict(str(error))
    receipts = db.scalars(select(Receipt).where(Receipt.invoice_id == invoice.id,
        Receipt.xiaoman_receipt_id.in_(payments))).all() if payments else []
    result = {}
    for receipt in receipts:
        identity = str(receipt.xiaoman_receipt_id)
        rows = db.execute(select(SettlementApplication, ShipmentSettlement).join(ShipmentSettlement,
            ShipmentSettlement.id == SettlementApplication.settlement_id).where(
            SettlementApplication.receipt_id == receipt.id, SettlementApplication.status != 'released')).all()
        occupied, by_batch = ZERO, defaultdict(lambda: ZERO)
        for app, batch in rows:
            if batch.invoice_id != invoice.id:
                _conflict('原回款资金被其他订单批次占用，请先核对原分配')
            principal = _amount(app.amount, '原分配金额') - _amount(app.bank_charge, '原分配银行手续费')
            released = _amount(releases.get(app.id, ZERO), '原批次已释放本金')
            if principal < released:
                _conflict('原批次已释放本金超过原分配，请先核对原资金')
            remaining = principal - released
            occupied += remaining
            if batch.id in selected_batches and app.component != 'freight':
                by_batch[str(batch.id)] += remaining
        cash = _amount(payments[identity]['principal'], '原回款本金') - refunded[identity]
        # Source principal excludes service fees, which may still be present in
        # the gross application. A nonpositive residual grants no free cash.
        free = max(ZERO, cash - occupied)
        result[identity] = (free, by_batch, min(cash, free + sum(by_batch.values(), ZERO)))
    return result


def constrain(db, snapshot, body, history):
    """Keep order-wide paid P, add selected-batch refundable Q on a copy."""
    result = deepcopy(snapshot)
    invoice_id = result.get('invoice_id')
    if invoice_id is None:
        return result
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        _conflict('原方舟订单不存在，预售资金来源待核对')
    if invoice.order_type != 'presale':
        return result
    if (str(invoice.xiaoman_order_id) != str(result['order_id'])
            or str(invoice.customer_id) != str(result['customer_id'])
            or invoice.currency != result['currency']):
        _conflict('原预售订单身份或币种已变化，请重新核对')
    source_lines = {str(line['source_key']): line for line in result['lines']}
    selected = defaultdict(list)
    for requested in body.lines:
        line = source_lines.get(str(requested.source_key))
        if not line:
            _conflict('所选退货行已不在原实际出库明细中')
        selected[str(line['outbound_id'])].append(line)
    payments = {str(row['payment_id']): row for row in result['payments']}
    if len(payments) != len(result['payments']):
        _conflict('原回款 ID 重复，预售可退资金待核对')
    # Read all effective allocations, even for batches outside this selection:
    # historical total refunds remain part of policy's per-payment P arithmetic.
    previous = db.execute(select(ReturnAllocation, SalesReturn).join(
        SalesReturn, SalesReturn.id == ReturnAllocation.return_id).where(
        SalesReturn.order_id == str(result['order_id']), SalesReturn.status == 'effective')).all()
    refunded_by_edge, refunded_by_payment = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    for allocation, owner in previous:
        identity = str(allocation.original_payment_id)
        funding = getattr(allocation, 'funding', None)
        if not isinstance(funding, list):
            _conflict('历史预售退款缺少资金批次分摊记录，请先核对原退货单')
        total = ZERO
        for entry in funding:
            if not isinstance(entry, dict) or entry.get('settlement_id') is None:
                _conflict('历史预售退款资金分摊记录无效')
            amount = _amount(entry.get('amount'), '历史已退批次本金')
            refunded_by_edge[(identity, str(entry['settlement_id']))] += amount
            total += amount
        if total != _amount(allocation.refund_amount, '历史退款金额'):
            _conflict('历史退款资金分摊与退款金额不一致')
        refunded_by_payment[identity] += total
    for identity in set(refunded_by_payment) | set(history.get('refunds', {})):
        if identity not in payments:
            _conflict('历史退款关联原回款已缺失或失效，请先核对原款')
        if refunded_by_payment[identity] != _amount(history.get('refunds', {}).get(identity, 0), '历史累计退款'):
            _conflict('历史退款额度与有效资金分摊不一致，请刷新原单')
    limits = defaultdict(lambda: defaultdict(lambda: ZERO))
    funding_batches = []
    for remote_id, selected_lines in sorted(selected.items()):
        outbounds = db.scalars(select(ShipmentOutbound).where(
            ShipmentOutbound.invoice_id == invoice.id, ShipmentOutbound.remote_id == remote_id)).all()
        if len(outbounds) != 1:
            _conflict('所选实际出库缺少唯一预售结算映射，旧批次资金来源待核对')
        outbound = outbounds[0]
        settlement = db.get(ShipmentSettlement, outbound.settlement_id)
        if (not settlement or settlement.invoice_id != invoice.id or settlement.state != 'shipped'
                or outbound.status != 'shipped'):
            _conflict('原预售结算或出库尚未完成核验，不能退回该批次资金')
        if (settlement.quote or {}).get('currency') != invoice.currency:
            _conflict('原预售结算币种缺失或与原单不一致')
        _verify_lines(outbound, selected_lines, result['order_id'])
        credit = _credit_valid(db, settlement)
        applications = db.execute(select(SettlementApplication, Receipt).join(
            Receipt, Receipt.id == SettlementApplication.receipt_id).where(
            SettlementApplication.settlement_id == settlement.id,
            SettlementApplication.status != 'released')).all()
        principal_by_payment = defaultdict(lambda: ZERO)
        for application, receipt in applications:
            if application.status != 'applied' and not (credit and application.status == 'reserved'):
                _conflict('原已发货批次仍有待核验资金占用，请先核对原分配')
            if application.component not in {'goods', 'deposit', 'freight'}:
                _conflict('原批次存在未知资金分配用途，请先核对')
            if application.component == 'freight':
                continue
            if application.component == 'deposit' and receipt.purpose not in {'presale_deposit', 'presale_advance'}:
                _conflict('原批次定金资金来源用途不一致')
            identity = str(receipt.xiaoman_receipt_id or '')
            if (receipt.invoice_id != invoice.id or receipt.customer_id != invoice.customer_id
                    or receipt.currency != invoice.currency or str(receipt.xiaoman_order_id) != str(result['order_id'])
                    or receipt.status != 'active'):
                _conflict('原批次商品资金与原订单客户或币种不一致')
            if credit and not payment_policy.receipt_effective(receipt):
                if identity in payments:
                    _conflict('原批次未收款预登记却计入已收本金，请先核对原款生效状态')
                continue  # Verified uncollected credit is debt, never refund cash.
            if (receipt.sync_status != 'synced' or receipt.collect_status != 1
                    or receipt.last_error or not identity or identity not in payments):
                _conflict('原批次商品资金缺少生效且同客户、同订单、同币种的原回款证据')
            amount = _amount(application.amount, '原分配金额')
            charge = _amount(application.bank_charge, '原分配银行手续费')
            if charge > amount:
                _conflict('原批次银行手续费超过分配金额')
            principal_by_payment[identity] += amount - charge
        if not principal_by_payment and not credit:
            _conflict('原批次没有可追溯的已生效商品本金分配，请先核对原款')
        for identity, principal in principal_by_payment.items():
            used = refunded_by_edge[(identity, str(settlement.id))]
            if used > principal:
                _conflict('原批次累计已退本金超过原分配额度')
            limits[identity][str(settlement.id)] = principal - used
        funding_batches.append({'settlement_id': settlement.id, 'outbound_id': remote_id})
    cash_limits = _cash_limits(db, invoice, payments, {row['settlement_id'] for row in funding_batches}, refunded_by_payment)
    for identity, payment in payments.items():
        edges = limits[identity]
        if identity in cash_limits:
            free, remaining_by_batch, payment_cap = cash_limits[identity]
            edges = {key: min(value, free + remaining_by_batch[key]) for key, value in edges.items()}
        available = sum(edges.values(), ZERO)
        if identity in cash_limits:
            available = min(available, payment_cap)
        previous_total = refunded_by_payment[identity]
        if previous_total > _amount(payment['principal'], '原回款本金'):
            _conflict('原回款累计退款超过本金')
        payment['funding_limits'] = [{'settlement_id': int(key), 'amount': format(amount, '.2f')} for key, amount in sorted(edges.items())]
        payment['refundable_amount'] = format(min(_amount(payment['principal'], '原回款本金'), previous_total + available), '.2f')
    result['funding_batches'] = funding_batches
    return result
