"""Authoritative active-list membership; deleted OKKI details can remain readable."""
from datetime import date, datetime
import logging

import httpx

from app.invoice import okki_client

logger = logging.getLogger(__name__)
PAGE_SIZE = 100
MAX_PAGES = 500


class PresenceError(ValueError):
    pass


def creation_floor(value):
    """Never use warehouse/shipping date as a creation/update query boundary."""
    try:
        stamp = datetime.strptime(str(value), '%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError) as exc:
        raise PresenceError('缺少有效的小满创建时间，不能判断出库单已删除') from exc
    return stamp.strftime('%Y-%m-%d 00:00:00')


def _page(token, start, end, page):
    try:
        response = httpx.request('GET', okki_client._base_url() + '/v1/invoices/outbound/list',
            params={'start_time': start, 'end_time': end, 'time_type': 2, 'removed': 0,
                    'count': PAGE_SIZE, 'start_index': page},
            headers={'Authorization': f'Bearer {token}'}, timeout=30)
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning('Outbound presence unavailable: %s', type(exc).__name__)
        print(f'[outbound_presence] unavailable: {type(exc).__name__}', flush=True)
        raise PresenceError('小满有效出库单列表查询失败，未判定删除') from exc
    if response.status_code != 200 or not isinstance(body, dict) or body.get('code') not in (0, 200):
        raise PresenceError('小满有效出库单列表拒绝查询，未判定删除')
    data = body.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('list'), list):
        raise PresenceError('小满有效出库单列表格式异常，未判定删除')
    count = data.get('count')
    if isinstance(count, bool) or not str(count).isdigit():
        raise PresenceError('小满有效出库单列表缺少总数，未判定删除')
    return data['list'], int(count)


def _scan(token, start, end, target=None):
    seen, rows_by_id, expected = set(), {}, None
    for page in range(1, MAX_PAGES + 1):
        rows, count = _page(token, start, end, page)
        if expected is not None and count != expected:
            raise PresenceError('小满有效出库单列表数量变化，请稍后核对')
        expected = count
        if len(rows) != min(PAGE_SIZE, max(0, count - len(seen))):
            raise PresenceError('小满有效出库单列表分页不完整，未判定删除')
        for row in rows:
            identity = str(row.get('outbound_invoice_id') or '') if isinstance(row, dict) else ''
            if not identity.isdigit() or int(identity) <= 0 or identity in seen:
                raise PresenceError('小满有效出库单列表ID缺失或重复，未判定删除')
            seen.add(identity)
            rows_by_id[identity] = row
        if target in seen:
            return rows_by_id
        if len(seen) == count:
            return rows_by_id
    raise PresenceError('小满有效出库单列表超出核验上限，未判定删除')


def _creation_day_bounds(value):
    try:
        day = date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError) as exc:
        raise PresenceError('缺少有效的小满创建时间，不能判断出库单已删除') from exc
    return f'{day.isoformat()} 00:00:00', f'{day.isoformat()} 23:59:59'


def active_rows_for_day(token, creation_day):
    """Return one stable active-ID snapshot bounded to an immutable creation day."""
    start, end = _creation_day_bounds(creation_day)
    first = _scan(token, start, end)
    second = _scan(token, start, end)
    if set(first) != set(second):
        raise PresenceError('小满有效出库单列表发生变化，请稍后核对')
    return second


def active_ids(token, start):
    """Compatibility wrapper for exact creation-day membership checks."""
    return set(active_rows_for_day(token, start))


def is_active(token, identity, start):
    """Finding the exact ID needs no absence proof or second full scan."""
    start, end = _creation_day_bounds(start)
    first = _scan(token, start, end, target=identity)
    if identity in first:
        return True
    if set(first) != set(_scan(token, start, end)):
        raise PresenceError('小满有效出库单列表发生变化，请稍后核对')
    return False
