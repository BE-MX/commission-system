"""仅转发消息，不在侧车中实现业务逻辑。"""

import logging

import httpx

from payload import message_payload

logger = logging.getLogger("project-radar-bot")


async def forward_message(message, *, backend_url, service_token):
    payload = message_payload(message)
    if payload is None:
        return "方舟雷达目前仅支持单聊文本消息"
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            response = await client.post(
                backend_url.rstrip("/") + "/api/project-radar/inbound/dingtalk",
                headers={"X-Project-Radar-Token": service_token}, json=payload,
            )
            response.raise_for_status()
            data = response.json()
        return data.get("data", {}).get("reply") or "已收到，正在处理"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Radar backend forwarding failed (%s)", type(exc).__name__)
        print(f"Radar backend forwarding failed ({type(exc).__name__})", flush=True)
        return "方舟后端暂时不可用，请稍后重发；本条消息尚未确认收录"
