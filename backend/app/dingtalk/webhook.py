"""钉钉 Webhook 机器人 — 群消息推送"""

import time
import logging

import httpx

from app.dingtalk.config import get_dingtalk_settings
from app.dingtalk.client import DingTalkClient

logger = logging.getLogger("commission.dingtalk")


class WebhookSender:
    """通过群机器人 Webhook 发送消息"""

    def __init__(self):
        self._settings = get_dingtalk_settings()

    def _build_url(self) -> str:
        """拼接签名参数后的 Webhook URL"""
        url = self._settings.DINGTALK_WEBHOOK_URL
        if not url:
            raise RuntimeError("DINGTALK_WEBHOOK_URL 未配置")

        secret = self._settings.DINGTALK_WEBHOOK_SECRET
        if secret:
            ts = str(round(time.time() * 1000))
            sign = DingTalkClient.sign_webhook(ts, secret)
            url += f"&timestamp={ts}&sign={sign}"
        return url

    async def send(self, payload: dict) -> dict:
        """发送消息到钉钉群"""
        url = self._build_url()
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10)
            result = resp.json()
            if result.get("errcode") != 0:
                logger.error("钉钉消息发送失败: %s", result.get("errmsg"))
                raise RuntimeError(f"钉钉消息发送失败: {result.get('errmsg')}")
            return result

    async def send_text(
        self,
        content: str,
        at_mobiles: list[str] | None = None,
        is_at_all: bool = False,
    ) -> dict:
        """发送文本消息"""
        payload = {
            "msgtype": "text",
            "text": {"content": content},
            "at": {
                "atMobiles": at_mobiles or [],
                "isAtAll": is_at_all,
            },
        }
        return await self.send(payload)

    async def send_markdown(
        self,
        title: str,
        text: str,
        at_mobiles: list[str] | None = None,
        is_at_all: bool = False,
    ) -> dict:
        """发送 Markdown 消息"""
        payload = {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": text},
            "at": {
                "atMobiles": at_mobiles or [],
                "isAtAll": is_at_all,
            },
        }
        return await self.send(payload)

    async def send_action_card(
        self,
        title: str,
        text: str,
        btns: list[dict],
        btn_orientation: str = "1",
    ) -> dict:
        """发送 ActionCard 消息（带按钮跳转）"""
        payload = {
            "msgtype": "actionCard",
            "actionCard": {
                "title": title,
                "text": text,
                "btns": btns,
                "btnOrientation": btn_orientation,
            },
        }
        return await self.send(payload)


# 全局单例
_sender: WebhookSender | None = None


def get_webhook_sender() -> WebhookSender:
    global _sender
    if _sender is None:
        _sender = WebhookSender()
    return _sender
