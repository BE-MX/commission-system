"""北京单活方舟雷达钉钉 Stream 侧车。"""

import asyncio
import logging
import os

import dingtalk_stream
from dingtalk_stream import AckMessage

from forwarder import forward_message

logger = logging.getLogger("project-radar-bot")


class RadarHandler(dingtalk_stream.ChatbotHandler):
    def __init__(self, backend_url, service_token):
        super().__init__()
        self.backend_url = backend_url
        self.service_token = service_token

    async def process(self, callback):
        incoming = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        reply = await forward_message(
            incoming, backend_url=self.backend_url, service_token=self.service_token,
        )
        await asyncio.to_thread(self.reply_text, reply, incoming)
        return AckMessage.STATUS_OK, "OK"


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app_key = os.environ.get("PROJECT_RADAR_DINGTALK_APP_KEY", "")
    app_secret = os.environ.get("PROJECT_RADAR_DINGTALK_APP_SECRET", "")
    service_token = os.environ.get("PROJECT_RADAR_INBOUND_TOKEN", "")
    backend_url = os.environ.get("PROJECT_RADAR_BACKEND_URL", "http://127.0.0.1:8001")
    if not all((app_key, app_secret, service_token)):
        raise RuntimeError("PROJECT_RADAR_DINGTALK_APP_KEY/SECRET 与 PROJECT_RADAR_INBOUND_TOKEN 必须配置")
    credential = dingtalk_stream.Credential(app_key, app_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
        RadarHandler(backend_url, service_token),
    )
    client.start_forever()


if __name__ == "__main__":
    main()
