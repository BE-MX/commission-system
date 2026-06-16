"""HTTP client for the isolated WhatsApp Connector service."""

from typing import Any

import httpx

from app.core.config import get_settings


class ConnectorNotConfigured(RuntimeError):
    """Raised when the external connector URL is not configured."""


class ConnectorError(RuntimeError):
    """Raised when the external connector returns an invalid response."""


class WhatsAppConnectorClient:
    def __init__(self):
        settings = get_settings()
        self.base_url = settings.WHATSAPP_CONNECTOR_BASE_URL.rstrip("/")
        self.api_key = settings.WHATSAPP_CONNECTOR_API_KEY
        self.timeout = settings.WHATSAPP_CONNECTOR_TIMEOUT_SECONDS

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        if not self.base_url:
            raise ConnectorNotConfigured("WHATSAPP_CONNECTOR_BASE_URL 未配置")

        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout, headers=self._headers()) as client:
                response = client.request(method, url, **kwargs)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise ConnectorError(f"Connector 返回错误: HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Connector 连接失败: {exc}") from exc
        except ValueError as exc:
            raise ConnectorError("Connector 返回非 JSON 数据") from exc

        if isinstance(payload, dict) and "data" in payload:
            data = payload.get("data")
            return data if isinstance(data, dict) else {"items": data or []}
        if isinstance(payload, dict):
            return payload
        raise ConnectorError("Connector 返回结构不符合预期")

    def create_bind_session(self, ark_user_id: int) -> dict[str, Any]:
        return self._request("POST", "/internal/v1/bind-sessions", json={"ark_user_id": ark_user_id})

    def get_bind_session(self, bind_session_uid: str) -> dict[str, Any]:
        return self._request("GET", f"/internal/v1/bind-sessions/{bind_session_uid}")

    def revoke_account(self, account_uid: str) -> dict[str, Any]:
        return self._request("POST", f"/internal/v1/accounts/{account_uid}/revoke")

    def pull_conversations(self, account_uid: str, cursor: str | None, limit: int) -> dict[str, Any]:
        params = {"account_uid": account_uid, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "/internal/v1/conversations", params=params)

    def pull_messages(
        self,
        account_uid: str,
        cursor: str | None,
        limit: int,
        chat_id: str | None = None,
    ) -> dict[str, Any]:
        params = {"account_uid": account_uid, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        if chat_id:
            params["chat_id"] = chat_id
        return self._request("GET", "/internal/v1/messages", params=params)
