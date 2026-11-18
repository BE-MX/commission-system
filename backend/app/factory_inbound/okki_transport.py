"""Exact OKKI purchase and receipt reads, plus guarded, single-attempt writes."""

from collections.abc import Callable
import logging

import httpx
from app.invoice import okki_client

logger = logging.getLogger(__name__)
OkkiOutcomeUncertainError = okki_client.OkkiOutcomeUncertainError

PURCHASE_PATH = "/v1/purchaseOrder"
INBOUND_PATH = "/v1/invoices/purchaseInbound"
FACTORY_SCOPE = "invoices purchaseOrder"


class OkkiMutationRejected(okki_client.OkkiApiError):
    """This call demonstrably stopped before sending a business POST."""


def _remote_id(raw: object) -> int | None:
    if type(raw) is int:
        return raw if 0 < raw <= 9223372036854775807 else None
    if isinstance(raw, str) and raw.isascii() and raw.isdecimal() and len(raw) <= 19:
        number = int(raw)
        if str(number) == raw and 0 < number <= 9223372036854775807:
            return number
    return None


class OkkiTransport:
    """Share OKKI auth and HTTP behavior without touching the invoice token cache.

    The executor must supply a gate that consumes the committed send right for
    this exact path/body, and must release transaction locks before returning.
    Read-only reconciliation can construct this adapter without a gate.
    """

    def __init__(self, *, before_send: Callable[[str, dict], None] | None = None):
        self._before_send = before_send
        self._access_token: str | None = None

    def _token(self, *, force: bool = False) -> str:
        if force or self._access_token is None:
            self._access_token, _ = okki_client.fetch_token(scope=FACTORY_SCOPE)
        return self._access_token

    def _get(self, path: str, params: dict) -> dict | None:
        for force in (False, True):
            try:
                response = httpx.get(
                    okki_client._base_url() + path,
                    headers={"Authorization": f"Bearer {self._token(force=force)}"},
                    timeout=okki_client.REQUEST_TIMEOUT, params=params,
                )
            except httpx.HTTPError as exc:
                logger.warning("OKKI factory lookup failed %s: %s", path, type(exc).__name__)
                print(f"[factory-inbound] lookup failed {path}: {type(exc).__name__}", flush=True)
                raise okki_client.OkkiApiError("读取小满工厂到货详情失败") from exc
            if response.status_code == 401:
                continue
            envelope = okki_client._parse_json(response, context="工厂到货查回")
            if envelope.get("error") == "access_denied":
                continue
            code, data = envelope.get("code"), envelope.get("data")
            if response.status_code == 200 and type(code) is int and not envelope.get("error"):
                if code == 404 and envelope.get("message") in (
                    "Not Found Resource", "Not Found Resource.",
                ) and data in (None, {}, []):
                    return None
                if code in (0, 200) and isinstance(data, dict):
                    return data
            raise okki_client.OkkiApiError("小满工厂到货详情响应异常")
        raise okki_client.OkkiApiError("小满工厂到货详情鉴权失败")

    def _find(self, path: str, number_key: str, value: str, id_key: str) -> dict | None:
        if not isinstance(value, str) or not value or value.strip() != value:
            raise okki_client.OkkiApiError("小满工厂到货查回缺少有效单号")
        detail = self._get(f"{path}/info", {number_key: value})
        if detail is None:
            return None
        identity = _remote_id(detail.get(id_key))
        if detail.get(number_key) != value or identity is None:
            raise okki_client.OkkiApiError("小满工厂到货详情单号或 ID 不匹配")
        confirmed = self._get(f"{path}/info", {id_key: identity})
        if (confirmed is None or _remote_id(confirmed.get(id_key)) != identity
                or confirmed.get(number_key) != value):
            raise okki_client.OkkiApiError("小满工厂到货按编号和内部 ID 查回的身份不一致")
        return confirmed

    def find_purchase(self, purchase_order_no: str) -> dict | None:
        return self._find(PURCHASE_PATH, "purchase_order_no", purchase_order_no, "purchase_order_id")

    def find_inbound(self, serial_id: str) -> dict | None:
        return self._find(INBOUND_PATH, "serial_id", serial_id, "inbound_invoice_id")

    def create_purchase(self, body: dict) -> int:
        if "purchase_order_id" in body:
            raise OkkiMutationRejected("工厂到货采购单只支持新建")
        return self._mutate(f"{PURCHASE_PATH}/push", body, "purchase_order_id")

    def push_inbound(self, body: dict) -> int:
        status = body.get("status")
        has_edit_id = "inbound_id" in body
        edit_id = _remote_id(body.get("inbound_id"))
        if (type(status) is not int or status not in (1, 2)
                or (status == 1 and has_edit_id) or (status == 2 and edit_id is None)
                or "inbound_invoice_id" in body):
            raise OkkiMutationRejected("工厂到货入库只支持新建草稿或按原 ID 转完成")
        return self._mutate(f"{INBOUND_PATH}/push", body, "inbound_invoice_id", expected=edit_id)

    def _mutate(self, path: str, body: dict, id_key: str, *, expected: int | None = None) -> int:
        if self._before_send is None:
            raise OkkiMutationRejected("工厂到货外发缺少持久办理权")
        try:
            token = self._token()
            self._before_send(path, body)
        except Exception as exc:
            logger.warning("OKKI factory send stopped before POST %s: %s", path, type(exc).__name__)
            print(f"[factory-inbound] send stopped before POST {path}: {type(exc).__name__}", flush=True)
            raise OkkiMutationRejected("工厂到货凭证或办理权校验未通过，未发送单据") from exc
        try:
            response = httpx.post(
                okki_client._base_url() + path, headers={"Authorization": f"Bearer {token}"},
                json=body, timeout=okki_client.REQUEST_TIMEOUT,
            )
            envelope = okki_client._parse_json(response, context="工厂到货推送")
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("OKKI factory POST did not confirm result %s: %s", path, type(exc).__name__)
            print(f"[factory-inbound] POST did not confirm result {path}", flush=True)
            raise OkkiOutcomeUncertainError("小满未确认工厂到货推送结果，请查回原单") from exc
        code, data = envelope.get("code"), envelope.get("data")
        if (response.status_code != 200 or type(code) is not int
                or code not in (0, 200) or envelope.get("error") or not isinstance(data, dict)):
            raise OkkiOutcomeUncertainError("小满未确认工厂到货推送结果，请查回原单")
        identity = _remote_id(data.get(id_key))
        if identity is None or (expected is not None and identity != expected):
            raise OkkiOutcomeUncertainError("小满工厂到货推送返回 ID 缺失或不匹配，请查回原单")
        return identity
