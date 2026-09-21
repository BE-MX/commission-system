"""Exact-ID OKKI deletion boundary; ambiguous writes are never retried."""
import logging

import httpx

from app.invoice import okki_client

logger = logging.getLogger(__name__)


class DeleteRemoteError(ValueError):
    def __init__(self, message, *, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


def _request(token, invoice_id, *, remove=False):
    path = '/v1/invoices/outbound/' + ('remove' if remove else 'info')
    try:
        response = httpx.request(
            'POST' if remove else 'GET', okki_client._base_url() + path,
            params={'outbound_invoice_id': invoice_id},
            headers={'Authorization': f'Bearer {token}'}, timeout=30,
        )
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning('OKKI outbound %s response unavailable: %s', path, type(exc).__name__)
        print(f'[outbound_delete] {path} response unavailable: {type(exc).__name__}', flush=True)
        raise DeleteRemoteError('小满响应异常，请重新核对删除结果', uncertain=remove) from exc
    if not isinstance(body, dict):
        raise DeleteRemoteError('小满响应格式异常', uncertain=remove)
    # Only this documented response proves absence. A generic 404 does not.
    if response.status_code == 200 and body.get('code') == 404 and body.get('message') in (
        'Not Found Resource', 'Not Found Resource.',
    ):
        return None
    if response.status_code == 200 and body.get('code') in (0, 200):
        if remove:
            return True
        data = body.get('data')
        if isinstance(data, dict) and str(data.get('outbound_invoice_id')) == str(invoice_id):
            return data
        raise DeleteRemoteError('小满返回的出库单身份不匹配')
    message = str(body.get('message') or '')
    locked = body.get('code') == 404 and message == '单据被锁定，无法操作'
    denied = response.status_code == 401 or body.get('error') == 'access_denied'
    logger.warning('OKKI outbound %s rejected: HTTP %s code %s', path, response.status_code, body.get('code'))
    print(f'[outbound_delete] {path} rejected: HTTP {response.status_code} code {body.get("code")}', flush=True)
    raise DeleteRemoteError(
        '小满单据被锁定，无法删除' if locked else '小满拒绝操作，请核对权限或单据状态',
        uncertain=remove and not (locked or denied),
    )


def read(token, invoice_id):
    from app.shipping_inspection import outbound_presence
    detail = _request(token, invoice_id)
    if detail is None:
        return None
    # OKKI can return status=1 from a soft-deleted detail. The active list is
    # authoritative; never interpret a failed/incomplete list as absence.
    try:
        start = outbound_presence.creation_floor(detail.get('create_time'))
        active = outbound_presence.is_active(token, str(invoice_id), start)
    except outbound_presence.PresenceError as exc:
        raise DeleteRemoteError(str(exc)) from exc
    return detail if active else None


def remove(token, invoice_id):
    return _request(token, invoice_id, remove=True)
