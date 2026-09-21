"""Exact identity reads and non-replayed destructive OKKI operations."""
import logging
import httpx
from app.invoice import okki_client

logger = logging.getLogger(__name__)


def request(token, kind, identity, *, remove=False):
    key = {"order": "order_id", "receipt": "cash_collection_id"}[kind]
    path = f"/v1/invoices/{kind}/{'remove' if remove else 'info'}"
    try:
        response = httpx.request("POST" if remove else "GET", okki_client._base_url() + path,
            params={key: str(identity)}, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("OKKI lifecycle response unavailable (%s)", type(exc).__name__)
        print(f"[invoice-lifecycle] response unavailable ({type(exc).__name__})", flush=True)
        error = okki_client.OkkiOutcomeUncertainError if remove else okki_client.OkkiApiError
        raise error("小满响应异常，请核对原单") from exc
    if not isinstance(body, dict):
        raise okki_client.OkkiOutcomeUncertainError("小满响应格式异常")
    if response.status_code == 200 and body.get("code") == 404 and body.get("message") in (
            "Not Found Resource", "Not Found Resource.") and not body.get("data"):
        return None
    if response.status_code == 200 and body.get("code") in (0, 200):
        if remove:
            return True
        data = body.get("data")
        if isinstance(data, dict) and str(data.get(key)) == str(identity):
            return data
        raise okki_client.OkkiApiError("小满返回单据身份不匹配，禁止推断已删除")
    # All unrecognized destructive outcomes stay quarantined. An administrator
    # may record a business cancellation, but cannot replay an ambiguous POST.
    error = okki_client.OkkiOutcomeUncertainError if remove else okki_client.OkkiApiError
    raise error("小满未确认操作，请核对权限、审批、确认状态及下游单据")


def read(db, kind, identity):
    return request(okki_client.ensure_access_token(db), kind, identity)
