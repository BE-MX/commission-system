"""Pure presale pricing; monetary inputs are finite, nonnegative, exact cents.

No unit-price recomputation: each line's frozen discounted total is allocated by
differences of cumulative HALF_UP amounts. Integer-cent arithmetic avoids Decimal
context precision influencing repeated shipments or payment allocation.
"""

from decimal import Decimal, InvalidOperation


def _cents(value, name):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f"{name} must be a monetary amount")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a monetary amount") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    numerator, denominator = amount.as_integer_ratio()
    cents, remainder = divmod(numerator * 100, denominator)
    if remainder:
        raise ValueError(f"{name} must have at most two decimal places")
    return cents


def _quantity(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{name} quantity must be an integer")
    try:
        number = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} quantity must be an integer") from exc
    if number < 0:
        raise ValueError(f"{name} quantity must be nonnegative")
    return number


def _round_ratio(numerator, denominator):
    return (2 * numerator + denominator) // (2 * denominator)


def _format(cents):
    return f"{cents // 100}.{cents % 100:02d}"


def quote_settlement(lines, packaging, handling, deposit, deposit_charge,
                     prior_packaging="0", prior_handling="0", *, freight="0"):
    """Quote one batch from ALL contract lines, including unrequested lines.

    Lines require invoice_item_id, quantity (original), total_price (discounted
    frozen total); shipped_quantity and requested_quantity default to zero.
    Money outputs are two-decimal strings. goods_payment_due includes this
    batch's handling fee, less the gross deposit on the final batch only;
    goods_payment_charge is the fee component of that new goods-channel payment.
    Prior amounts must include committed, nonvoid batches only.
    """
    p, h, d, dh, pp, ph, f = (
        _cents(value, name) for value, name in (
            (packaging, "packaging"), (handling, "handling"),
            (deposit, "deposit"), (deposit_charge, "deposit_charge"),
            (prior_packaging, "prior_packaging"), (prior_handling, "prior_handling"),
            (freight, "freight")))
    if not lines:
        raise ValueError("At least one contract line is required")
    items, seen = [], set()
    total_goods = prior_goods = goods = requested_count = 0
    is_final = True
    for row in lines:
        item_id = row["invoice_item_id"]
        if item_id in seen:
            raise ValueError("Duplicate invoice_item_id")
        seen.add(item_id)
        q = _quantity(row["quantity"], "original")
        k = _quantity(row.get("shipped_quantity", 0), "shipped")
        n = _quantity(row.get("requested_quantity", 0), "requested")
        if q == 0 or k + n > q:
            raise ValueError("Shipment quantity exceeds available quantity")
        total = _cents(row["total_price"], "total_price")
        before = _round_ratio(total * k, q)
        amount = _round_ratio(total * (k + n), q) - before
        total_goods += total
        prior_goods += before
        goods += amount
        requested_count += n
        is_final = is_final and k + n == q
        if n:
            items.append({"invoice_item_id": item_id, "quantity": n,
                          "line_amount": _format(amount)})
    if requested_count == 0:
        raise ValueError("At least one requested quantity must be positive")
    if not 0 < d - dh <= total_goods or dh > h:
        raise ValueError("Invalid deposit principal or deposit charge")
    expected_pp = _round_ratio(p * prior_goods, total_goods)
    expected_ph = min(_round_ratio(h * (prior_goods + expected_pp), total_goods + p), h - dh)
    if pp != expected_pp or ph != expected_ph:
        raise ValueError("Prior packaging or handling does not match cumulative shipment amounts")
    cumulative_goods = prior_goods + goods
    batch_p = p - pp if is_final else _round_ratio(p * cumulative_goods, total_goods) - pp
    batch_h = h - ph if is_final else min(
        _round_ratio(h * (cumulative_goods + pp + batch_p), total_goods + p), h - dh) - ph
    if not is_final and total_goods - cumulative_goods < d - dh:
        raise ValueError("Remaining goods cannot cover reserved deposit principal")
    applied = d if is_final else 0
    fee_applied = dh if is_final else 0
    goods_due = goods + batch_p + batch_h - applied
    if goods_due < 0 or batch_h < fee_applied:
        raise ValueError("Final amounts cannot cover deposit allocation")
    result = {"items": items, "is_final": is_final}
    result.update({name: _format(value) for name, value in (
        ("goods_amount", goods), ("packaging_amount", batch_p),
        ("handling_amount", batch_h), ("freight_amount", f),
        ("deposit_applied", applied), ("deposit_charge_applied", fee_applied),
        ("new_payment_due", goods_due + f), ("goods_payment_due", goods_due),
        ("goods_payment_charge", batch_h - fee_applied))})
    return result


def split_payment(amount, goods_remaining, freight_remaining, goods_charge_remaining):
    """Return Decimal goods_amount/freight_amount/charge_amount components.

    Goods includes handling. Allocate cents by largest remainder proportional to
    unpaid gross goods and freight, with ties going to goods. Fee is HALF_UP
    proportional to the allocated goods; the last goods payment takes its entire
    remaining fee. A zero payment is valid; overpayment is rejected.
    """
    a, g, f, c = (_cents(value, name) for value, name in (
        (amount, "amount"), (goods_remaining, "goods_remaining"),
        (freight_remaining, "freight_remaining"),
        (goods_charge_remaining, "goods_charge_remaining")))
    if a > g + f or c > g:
        raise ValueError("Payment or fee exceeds remaining balance")
    if not a:
        return dict(goods_amount=Decimal("0.00"), freight_amount=Decimal("0.00"), charge_amount=Decimal("0.00"))
    goods, gr = divmod(a * g, g + f)
    freight_part, fr = divmod(a * f, g + f)
    if goods + freight_part < a:
        if gr >= fr:
            goods += 1
        else:
            freight_part += 1
    charge = c if goods == g else _round_ratio(c * goods, g)
    return dict(goods_amount=Decimal(_format(goods)), freight_amount=Decimal(_format(freight_part)),
                charge_amount=Decimal(_format(charge)))
