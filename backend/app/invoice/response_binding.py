"""Atomic product-line identity matching for OKKI acceptance responses."""
from decimal import Decimal


def _identity(value):
    if isinstance(value, bool):
        raise ValueError('Invalid product identity')
    value = str(value)
    if len(value) > 64 or not value.isascii() or not value.isdecimal() or value.startswith('0'):
        raise ValueError('Invalid product identity')
    return value


def _number(value):
    value = Decimal(str(value))
    if not value.is_finite():
        raise ValueError('Nonfinite commercial evidence')
    return value


def _matches(sent, actual):
    if any(_identity(sent[k]) != _identity(actual[k]) for k in ('product_id', 'sku_id')):
        return False
    if any(_number(sent[k]) != _number(actual[k]) for k in ('count', 'unit_price')):
        return False
    # The push response omits cost_amount. Never infer a discounted subtotal;
    # repeated-product completion separately reads the full order and amount.
    return 'cost_amount' not in actual or _number(sent['cost_amount']) == _number(actual['cost_amount'])


def _signature(row):
    return (*(_identity(row[k]) for k in ('product_id', 'sku_id')),
            *(_number(row[k]) for k in ('count', 'unit_price', 'cost_amount')))


def match(bindings, response_rows):
    """Return assignments only after every expected and returned row matches."""
    if not isinstance(response_rows, list) or len(bindings) != len(response_rows):
        raise ValueError('Accepted product set differs from sent product set')
    pool = {}
    for row in response_rows:
        uid = _identity(row['unique_id'])
        if uid in pool:
            raise ValueError('Duplicate returned line identity')
        pool[uid] = row
    assignments, fresh = [], []
    for items, sent in bindings:
        if not sent.get('unique_id'):
            fresh.append((items, sent))
            continue
        uid = _identity(sent['unique_id'])
        actual = pool.pop(uid, None)
        if actual is None or not _matches(sent, actual):
            raise ValueError('Existing line identity or commercial values changed')
        assignments.append((items, uid))
    for position, (items, sent) in enumerate(fresh):
        matches = [uid for uid, actual in pool.items() if _matches(sent, actual)]
        if len(matches) > 1 and all('cost_amount' in pool[uid] for uid in matches):
            # Fully proven identical lines are interchangeable. Preserve anchored
            # identities first, then assign this complete equivalence class once.
            signature = _signature(sent)
            remaining = sum(_signature(row) == signature for _, row in fresh[position:])
            if remaining == len(matches) and all(_signature(pool[uid]) == signature for uid in matches):
                matches = [min(matches, key=int)]
        if len(matches) != 1:
            raise ValueError('New line identity is missing or ambiguous')
        uid = matches[0]
        pool.pop(uid)
        assignments.append((items, uid))
    if pool:
        raise ValueError('Unmatched returned product lines')
    return assignments
