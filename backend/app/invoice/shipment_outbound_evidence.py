"""Verify active outbounds against certified links and bounded live details."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from time import monotonic

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.invoice import linked_outbound_service as outbound
from app.invoice.settlement_models import OutboundLinkProof
from app.receipt import remote

MAX_UNVERIFIED_DETAILS = 16
SUMMARY_SECONDS = 45
DETAIL_SECONDS = 90
REQUEST_SECONDS = 8


class OutboundEvidenceNotReady(ValueError):
    pass


def _digits(value):
    value = str(value)
    return value.isascii() and value.isdecimal()


def _positive_id(value):
    value = str(value)
    return _digits(value) and not value.startswith('0')


def _timestamp(value):
    if not isinstance(value, str) or len(value) != 19:
        raise ValueError('小满出库时间证据不完整')
    return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')


def _quantity(value):
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def _version(row):
    updated = _timestamp(row.get('update_time'))
    status = row.get('status')
    quantity = _quantity(row.get('product_total_count'))
    if not _digits(status) or quantity is None:
        raise ValueError('小满出库列表版本或数量不完整')
    return updated, str(status), quantity


def source_key():
    settings = get_settings()
    identity = [settings.OKKI_API_BASE.rstrip('/'), settings.OKKI_CLIENT_ID]
    return sha256(json.dumps(identity, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _closed_version(proof, updated):
    if proof.remote_version != str(updated):
        return False
    try:
        return _timestamp(proof.listed_at) > updated
    except ValueError:
        return False


def _certified_links(db, versions, order_id):
    # Presence comes from the live list. Only the background worker can certify
    # a non-match, after fetching complete details after the provider's update second.
    ids = list(versions)
    account = source_key()
    proven = {}
    for offset in range(0, len(ids), 1000):
        rows = db.scalars(select(OutboundLinkProof).where(
            OutboundLinkProof.source_key == account,
            OutboundLinkProof.outbound_id.in_(ids[offset:offset + 1000]),
        ))
        for row in rows:
            updated, status, quantity = versions[row.outbound_id]
            if (row.remote_status == status and _quantity(row.remote_quantity) == quantity
                    and _closed_version(row, updated) and isinstance(row.order_ids, list)
                    and all(isinstance(link, str) and _positive_id(link) for link in row.order_ids)):
                proven[row.outbound_id] = order_id in row.order_ids
    return proven


def find_related(db, order):
    order_id = str(order.get('order_id'))
    if not _positive_id(order_id):
        raise ValueError('关联订单身份不完整')
    day = datetime.strptime(str(order.get('create_time'))[:10], '%Y-%m-%d')
    params = dict(start_time=day.strftime('%Y-%m-%d 00:00:00'), time_type=1, count=100, removed=0)
    deadline = monotonic() + SUMMARY_SECONDS

    with httpx.Client() as client:
        def read(session, path, query):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise OutboundEvidenceNotReady('小满出库列表暂未核验齐全，请稍后重新核算')
            body = remote.read(session, path, query, client=client, timeout=min(REQUEST_SECONDS, remaining),
                               include_envelope=True)
            if not isinstance(body, dict) or not isinstance(body.get('data'), dict):
                raise ValueError('小满出库列表响应不完整')
            listed_at = _timestamp(body.get('now'))
            data = body['data']
            # Do not use a list returned within a record's mutable update second
            # to prove that an outbound is unrelated or that a link stayed stable.
            rows = data.get('list')
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict) and _timestamp(row.get('update_time')) >= listed_at:
                        raise outbound.OutboundListChanged('小满出库单仍在更新，请稍后重试')
            return data

        def versions():
            rows = outbound._list_rows(db, params, read=read)
            if any(not _positive_id(identity) for identity in rows):
                raise ValueError('小满出库列表身份不完整')
            return {identity: _version(row) for identity, row in rows.items()}

        before = versions()
        proven = _certified_links(db, before, order_id) if len(before) > 1 else {}
        unknown = before.keys() - proven.keys()
        if len(unknown) > MAX_UNVERIFIED_DETAILS:
            raise OutboundEvidenceNotReady('小满出库关联尚未同步齐全，请稍后重试')
        candidates = sorted(unknown | {identity for identity, related in proven.items() if related}, key=int)
        # Live details are outside the summary budget. Known order links are not subject to the unknown-detail cap.
        started = monotonic()
        details = []
        for offset in range(0, len(candidates), MAX_UNVERIFIED_DETAILS):
            remaining = DETAIL_SECONDS - (monotonic() - started)
            if remaining <= 0:
                raise OutboundEvidenceNotReady('小满关联出库单暂未核验齐全，请稍后重新核算')
            batch = candidates[offset:offset + MAX_UNVERIFIED_DETAILS]
            rows = outbound._read_details(db, batch, timeout=min(REQUEST_SECONDS, remaining))
            if len(rows) != len(batch):
                raise ValueError('小满出库单详情未完整读取')
            details.extend(rows)
        deadline += monotonic() - started
        related = []
        for identity, detail in zip(candidates, details):
            if not isinstance(detail, dict) or str(detail.get('outbound_invoice_id')) != identity:
                raise ValueError('小满出库单详情身份不完整')
            if _version(detail) != before[identity]:
                raise outbound.OutboundListChanged('小满出库单版本在核验期间发生变化')
            lines = detail.get('record_list')
            if not isinstance(lines, list) or any(not isinstance(line, dict)
                    or (str(line.get('order_id')) != '0' and not _positive_id(line.get('order_id'))) for line in lines):
                raise ValueError('小满出库单详情的订单关联不完整')
            line_ids = [str(line.get('outbound_record_id')) for line in lines]
            if any(not _positive_id(key) for key in line_ids) or len(set(line_ids)) != len(line_ids):
                raise ValueError('小满出库单明细身份缺失或重复')
            quantities = [_quantity(line.get('outbound_count')) for line in lines]
            if None in quantities or sum(quantities) != before[identity][2]:
                raise ValueError('小满出库明细数量与列表不一致')
            if any(str(line['order_id']) == order_id for line in lines):
                related.append(detail)
        if versions() != before:
            raise outbound.OutboundListChanged('小满出库单列表在核验期间发生变化')
    return related
