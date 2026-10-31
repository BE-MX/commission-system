"""Remaining shipment pricing anchored to reviewed historical actual cents.

Historical batches may precede native proportional rounding. Freeze their
amounts and distribute only the remaining contract value across remaining
pieces. The final shipment consumes every remaining cent and deposit component.
"""
from app.invoice.settlement_pricing import _cents, _round_ratio, _format


def quote_remaining(invoice, requested, shipped, *, freight, deposit_remaining, deposit_charge_remaining):
    old = [row for row in shipped if row.quote.get('opening_record_id') is not None]
    if not old:
        raise ValueError('承接订单缺少原已发批次金额基线')
    old_quantities, old_amounts = {}, {}
    for row in old:
        for line in row.quote['items']:
            identity = line['invoice_item_id']
            old_quantities[identity] = old_quantities.get(identity, 0) + line['quantity']
            old_amounts[identity] = old_amounts.get(identity, 0) + _cents(line['line_amount'], 'original_line_amount')
    remaining_goods = prior_goods = goods = requested_count = 0
    is_final = True
    items = []
    for item in invoice.items:
        old_quantity, old_amount = old_quantities.get(item.id, 0), old_amounts.get(item.id, 0)
        quantity, shipped_quantity, count = item.quantity - old_quantity, item.stock_shipped_quantity - old_quantity, requested.get(item.id, 0)
        amount = _cents(item.total_price, 'line_amount') - old_amount
        if min(quantity, shipped_quantity, count, amount) < 0 or shipped_quantity + count > quantity:
            raise ValueError('本地剩余发货与原已发基线不一致')
        if quantity == 0:
            if amount:
                raise ValueError('原已发全量明细尚有未确认商品金额，须先核验')
            continue
        before = _round_ratio(amount * shipped_quantity, quantity)
        current = _round_ratio(amount * (shipped_quantity + count), quantity) - before
        remaining_goods += amount
        prior_goods += before
        goods += current
        requested_count += count
        is_final = is_final and shipped_quantity + count == quantity
        if count:
            items.append(dict(invoice_item_id=item.id, quantity=count, line_amount=_format(current)))
    if requested_count == 0:
        raise ValueError('须选择原订单剩余商品')
    old_packaging = sum(_cents(row.quote['packaging_amount'], 'original_packaging') for row in old)
    old_handling = sum(_cents(row.quote['handling_amount'], 'original_handling') for row in old)
    packaging = _cents(invoice.internal_accessory or 0, 'packaging') - old_packaging
    handling = _cents(invoice.surcharge_amount, 'handling') - old_handling
    native = [row for row in shipped if row not in old]
    prior_packaging = sum(_cents(row.quote['packaging_amount'], 'prior_packaging') for row in native)
    prior_handling = sum(_cents(row.quote['handling_amount'], 'prior_handling') for row in native)
    deposit, deposit_fee = _cents(deposit_remaining, 'remaining_deposit'), _cents(deposit_charge_remaining, 'remaining_deposit_fee')
    if remaining_goods == 0:
        old_freight = sum(_cents(row.quote['freight_amount'], 'original_freight') for row in old)
        if (packaging or handling or deposit or deposit_fee or prior_packaging or prior_handling or freight
                or invoice.order_type != 'presale' and _cents(invoice.shipping_fee, 'contract_freight') != old_freight):
            raise ValueError('零剩余货值仍有费用或首款责任，须先核验完整历史分摊')
        return dict(items=items, is_final=is_final, **{key: '0.00' for key in (
            'goods_amount', 'packaging_amount', 'handling_amount', 'freight_amount', 'deposit_applied',
            'deposit_charge_applied', 'goods_payment_due', 'goods_payment_charge', 'new_payment_due')})
    if (min(packaging, handling) < 0 or deposit_fee > min(deposit, handling)
            or deposit - deposit_fee > remaining_goods - prior_goods):
        raise ValueError('原已发费用或剩余首款超出剩余合同责任')
    expected_packaging = _round_ratio(packaging * prior_goods, remaining_goods)
    expected_handling = min(_round_ratio(handling * (prior_goods + expected_packaging), remaining_goods + packaging), handling - deposit_fee)
    if (prior_packaging, prior_handling) != (expected_packaging, expected_handling):
        raise ValueError('新发批次累计金额与原冻结期初尾差不一致')
    cumulative = prior_goods + goods
    batch_packaging = packaging - prior_packaging if is_final else _round_ratio(packaging * cumulative, remaining_goods) - prior_packaging
    batch_handling = handling - prior_handling if is_final else min(
        _round_ratio(handling * (cumulative + prior_packaging + batch_packaging), remaining_goods + packaging), handling - deposit_fee) - prior_handling
    if not is_final and remaining_goods - cumulative < deposit - deposit_fee:
        raise ValueError('剩余货值不能覆盖尚未应用首款本金')
    applied, fee_applied = (deposit, deposit_fee) if is_final else (0, 0)
    goods_due = goods + batch_packaging + batch_handling - applied
    if goods_due < 0 or batch_handling < fee_applied:
        raise ValueError('剩余最终批次不能覆盖首款及费用组成')
    if invoice.order_type == 'presale':
        batch_freight = _cents(freight, 'freight')
    else:
        old_freight = sum(_cents(row.quote['freight_amount'], 'original_freight') for row in old)
        remaining_freight = _cents(invoice.shipping_fee, 'contract_freight') - old_freight
        prior_freight = sum(_cents(row.quote['freight_amount'], 'prior_freight') for row in native)
        if freight or remaining_freight < 0 or prior_freight != _round_ratio(remaining_freight * prior_goods, remaining_goods):
            raise ValueError('剩余原合同运费或既有新批次运费不一致')
        batch_freight = remaining_freight - prior_freight if is_final else _round_ratio(remaining_freight * cumulative, remaining_goods) - prior_freight
    result = dict(items=items, is_final=is_final)
    result.update({key: _format(value) for key, value in (
        ('goods_amount', goods), ('packaging_amount', batch_packaging), ('handling_amount', batch_handling),
        ('freight_amount', batch_freight), ('deposit_applied', applied), ('deposit_charge_applied', fee_applied),
        ('goods_payment_due', goods_due), ('goods_payment_charge', batch_handling - fee_applied), ('new_payment_due', goods_due + batch_freight))})
    return result
