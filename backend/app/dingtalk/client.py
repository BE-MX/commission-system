"""钉钉 API 客户端 — token 管理、签名、请求封装"""

import time
import hmac
import hashlib
import base64
import urllib.parse
import logging

import httpx

from app.dingtalk.config import get_dingtalk_settings

logger = logging.getLogger("commission.dingtalk")


class DingTalkError(Exception):
    """钉钉 API 调用异常"""

    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(f"DingTalkError({code}): {message}")


class DingTalkClient:
    """钉钉企业内部应用 API 客户端"""

    BASE_URL = "https://oapi.dingtalk.com"

    def __init__(self):
        settings = get_dingtalk_settings()
        self.app_key = settings.DINGTALK_APP_KEY
        self.app_secret = settings.DINGTALK_APP_SECRET
        self._token: str | None = None
        self._token_expires: float = 0

    async def get_access_token(self) -> str:
        """获取 access_token（自动缓存，过期前 60 秒刷新）"""
        if self._token and time.time() < self._token_expires - 60:
            return self._token

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.BASE_URL}/gettoken",
                params={"appkey": self.app_key, "appsecret": self.app_secret},
                timeout=10,
            )
            data = resp.json()
            if data.get("errcode") != 0:
                raise DingTalkError(data.get("errcode", -1), data.get("errmsg", "获取token失败"))

            self._token = data["access_token"]
            self._token_expires = time.time() + data.get("expires_in", 7200)
            logger.info("DingTalk access_token refreshed, expires in %ds", data.get("expires_in", 7200))
            return self._token

    async def post(self, endpoint: str, params: dict | None = None, json_data: dict | None = None) -> dict:
        """带 token 的 POST 请求"""
        token = await self.get_access_token()
        url = f"{self.BASE_URL}/{endpoint}"
        query = {"access_token": token}
        if params:
            query.update(params)

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, params=query, json=json_data, timeout=15)
            data = resp.json()
            if data.get("errcode", 0) != 0:
                raise DingTalkError(data.get("errcode", -1), data.get("errmsg", "unknown"))
            return data

    async def get(self, endpoint: str, params: dict | None = None) -> dict:
        """带 token 的 GET 请求"""
        token = await self.get_access_token()
        url = f"{self.BASE_URL}/{endpoint}"
        query = {"access_token": token}
        if params:
            query.update(params)

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=query, timeout=15)
            data = resp.json()
            if data.get("errcode", 0) != 0:
                raise DingTalkError(data.get("errcode", -1), data.get("errmsg", "unknown"))
            return data

    @staticmethod
    def sign_webhook(timestamp_ms: str, secret: str) -> str:
        """计算 Webhook 签名"""
        string_to_sign = f"{timestamp_ms}\n{secret}"
        hmac_code = hmac.new(
            secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return urllib.parse.quote_plus(base64.b64encode(hmac_code).decode())


# 全局单例
_client: DingTalkClient | None = None


def get_dingtalk_client() -> DingTalkClient:
    global _client
    if _client is None:
        _client = DingTalkClient()
    return _client
