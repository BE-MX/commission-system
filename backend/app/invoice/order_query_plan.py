"""Pure original-request projection and bounded GET-only supplier verification."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from app.invoice import uncertain_recovery
from app.invoice.cancellation_facts import digest

ROW_FIELDS = ('product_id', 'sku_id', 'count', 'unit_price', 'cost_amount', 'unique_id')
HEADER_FIELDS = ('name', 'company_id', 'currency', 'account_date', 'status', 'create_user', 'handler', 'users', 'departments')


def request_snapshot(payload):
    # No contacts, addresses, notes, credentials or execution tokens in audit data.
    result = {key: deepcopy(payload.get(key)) for key in HEADER_FIELDS}
    result['flags'] = {key: deepcopy(value) for key, value in payload.items() if key.isdecimal()}
    result['remark_fingerprint'] = digest((payload.get('remark') or '').replace('\r\n', '\n').strip())
    result['product_list'] = [{key: row[key] for key in ROW_FIELDS if key in row}
                              for row in payload['product_list']]
    result['cost_list'] = [{key: row[key] for key in ('cost_name', 'cost', 'percent_type', 'percent_amount')
                           if key in row} for row in payload.get('cost_list', [])]
    return result


def window(start, end):
    lower = start.replace(microsecond=0)
    upper = datetime.fromisoformat(end)
    if upper <= lower or (upper - lower).total_seconds() > 301:
        raise ValueError('Invalid original send window')
    return lower, upper


def verify(invoice, request, detail, lower, upper):
    from app.invoice.uncertain_recovery import _canonical_uid
    identity = _canonical_uid(detail.get('order_id'))
    stamp = datetime.strptime(detail.get('create_time', ''), '%Y-%m-%d %H:%M:%S')
    if not lower <= stamp <= upper or detail.get('name') != request['name']:
        raise ValueError('Candidate is outside original order attempt')
    def account_day(value):
        value = str(value)
        return datetime.strptime(value, '%Y-%m-%d' if len(value) == 10 else '%Y-%m-%d %H:%M:%S').date()
    if account_day(detail.get('account_date')) != account_day(request['account_date']):
        raise ValueError('Original account date differs')
    for key in ('currency', 'status', 'create_user', *request['flags']):
        expected = request['flags'][key] if key in request['flags'] else request[key]
        if str(detail.get(key)) != str(expected):
            raise ValueError('Original commercial header differs')
    if digest((detail.get('remark') or '').replace('\r\n', '\n').strip()) != request['remark_fingerprint']:
        raise ValueError('Original order notes differ')
    if sorted(map(str, detail.get('handler', []))) != sorted(map(str, request['handler'] or [])):
        raise ValueError('Original handlers differ')
    def ownership(entries, identity_key):
        if not isinstance(entries, list) or not entries:
            raise ValueError('Missing original ownership')
        result = []
        for row in entries:
            # OKKI department 0 is the legitimate enterprise root.
            identity = str(row[identity_key])
            if not (identity_key == 'department_id' and identity == '0'):
                identity = _canonical_uid(row[identity_key])
            rate = Decimal(str(row['rate']))
            if not rate.is_finite() or not 0 <= rate <= 100:
                raise ValueError('Invalid original ownership rate')
            result.append((identity, rate))
        if len({identity for identity, rate in result}) != len(result):
            raise ValueError('Duplicate original ownership')
        return sorted(result)
    for key, identity_key in (('users', 'user_id'), ('departments', 'department_id')):
        if ownership(detail.get(key), identity_key) != ownership(request[key], identity_key):
            raise ValueError('Original ownership allocation differs')
    target = SimpleNamespace(xiaoman_order_id=identity, customer_id=invoice.customer_id,
        currency=invoice.currency, total_amount=invoice.total_amount, surcharge_amount=invoice.surcharge_amount)
    rows = uncertain_recovery.verify_existing(target, request['product_list'], detail)
    def costs(entries):
        result = []
        for row in entries:
            amount = Decimal(str(row['cost']))
            if not amount.is_finite() or row['percent_type'] != 0:
                raise ValueError('Unsupported original fee evidence')
            result.append((row['cost_name'], amount))
        return sorted(result)
    if costs(request['cost_list']) != costs(detail.get('cost_list', [])):
        raise ValueError('Original fees differ')
    return rows


def find(read, invoice, request, lower, upper):
    def scan():
        seen, total = {}, None
        for page in range(1, 6):
            data = read('/v1/invoices/order/list', {'start_time': lower.strftime('%Y-%m-%d 00:00:00'),
                'end_time': upper.strftime('%Y-%m-%d 23:59:59'), 'time_type': 2,
                'removed': 0, 'approval_with_draft': 1, 'count': 100, 'start_index': page})
            if (not isinstance(data, dict) or not isinstance(data.get('list'), list)
                    or type(data.get('count')) not in (int, str) or not str(data['count']).isdigit()):
                raise ValueError('Incomplete active order index')
            count = int(data['count'])
            if total is not None and total != count:
                raise ValueError('Changing active order index')
            total = count
            for row in data['list']:
                if not isinstance(row, dict):
                    raise ValueError('Malformed active order index row')
                identity = uncertain_recovery._canonical_uid(row.get('order_id'))
                if identity in seen or not isinstance(row.get('name'), str):
                    raise ValueError('Ambiguous active order index')
                seen[identity] = row['name']
            if len(seen) == total:
                return seen
            if not data['list'] or len(seen) > total:
                break
        raise ValueError('Active order index exceeds bounded scan')
    first, second = scan(), scan()
    if first != second:
        raise ValueError('Active order index changed during verification')
    matching = [identity for identity, name in second.items() if name == request['name']]
    if len(matching) != 1:
        raise ValueError('No unique original order candidate')
    detail = read('/v1/invoices/order/info', {'order_id': matching[0]})
    if not isinstance(detail, dict) or str(detail.get('order_id')) != matching[0]:
        raise ValueError('Candidate detail identity differs')
    verify(invoice, request, detail, lower, upper)
    if read('/v1/invoices/order/info', {'order_id': matching[0]}) != detail:
        raise ValueError('Candidate changed during verification')
    return detail
