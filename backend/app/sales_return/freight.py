"""Refund only proven paid freight, independently of goods and surcharges."""
from app.sales_return.policy import ZERO, money


def limits(snapshot, history):
    payments = snapshot['payments']
    evidenced = [row for row in payments if 'freight_principal' in row]
    previous = history.get('freight_refunds', {})
    previous_usd = history.get('freight_refunds_usd', {})
    if not evidenced:
        if any(money(value) for value in [*previous.values(), *previous_usd.values()]):
            raise ValueError('已退运费的原收款证据缺失，请核对原单')
        return {'supported': False, 'original': ZERO, 'remaining': ZERO, 'payment': None}
    # The source adapter only proves freight on one fully paid USD stock invoice.
    # Never infer foreign exchange or presale/fractional payment allocations here.
    if snapshot['currency'] != 'USD' or 'funding_batches' in snapshot or len(payments) != 1:
        raise ValueError('原单运费尚无精确的已收款分摊依据')
    payment = evidenced[0]
    original = money(payment['freight_principal'])
    goods = money(payment['principal'])
    cash = money(payment['cash_principal'])
    non_goods = money(payment['non_goods_amount'])
    if (payment['currency'] != 'USD' or min(original, goods, cash, non_goods) < 0
            or original > non_goods or cash != goods + non_goods
            or any(money(payment[key]) != expected for key, expected in
                [('freight_principal_usd', original), ('principal_usd', goods),
                 ('cash_principal_usd', cash), ('non_goods_amount_usd', non_goods)])):
        raise ValueError('原运费、商品本金及现金收款不一致，请核对原单')
    identity = payment['payment_id']
    if any(key != identity and money(value) for key, value in previous.items()):
        raise ValueError('已退运费的原回款关联已变化，请核对原单')
    used = money(previous.get(identity, 0))
    if used < 0 or used > original or money(previous_usd.get(identity, 0)) != used:
        raise ValueError('累计运费退款超出原运费或美元分摊不一致')
    return {'supported': True, 'original': original, 'remaining': original-used, 'payment': payment}


def allocate(allocations, facts, amount):
    """Keep allocation totals as cash, with explicit freight subcomponents."""
    for allocation in allocations:
        allocation.update(freight_refund_amount='0.00', freight_refund_amount_usd='0.00')
    payment = facts['payment']
    if payment is None:
        return
    identity = payment['payment_id']
    allocation = next((row for row in allocations if row['original_payment_id'] == identity), None)
    if allocation is None and amount:
        allocation = dict(original_payment_id=identity, refund_amount='0.00', refund_amount_usd='0.00', funding=[])
        allocations.append(allocation)
    if allocation is not None:
        refundable = money(payment['principal']) + facts['original']
        allocation.update(original_principal=str(refundable), original_principal_usd=str(refundable),
            refund_amount=str(money(allocation['refund_amount'])+amount),
            refund_amount_usd=str(money(allocation['refund_amount_usd'])+amount),
            freight_refund_amount=str(amount), freight_refund_amount_usd=str(amount))
