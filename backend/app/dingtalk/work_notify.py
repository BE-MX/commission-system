"""钉钉工作通知 — 通过企业内部应用发送消息给指定用户"""

import logging

from app.dingtalk.client import get_dingtalk_client, DingTalkError

logger = logging.getLogger("commission.dingtalk")


class WorkNotifier:
    """企业内部应用工作通知（发给指定用户）"""

    async def send_to_users(
        self,
        user_ids: list[str],
        title: str,
        markdown_text: str,
    ):
        """
        向指定用户发送工作通知（Markdown）。
        user_ids: 钉钉 UserID 列表
        """
        client = get_dingtalk_client()
        settings_client = client  # get agent_id from settings
        from app.dingtalk.config import get_dingtalk_settings
        agent_id = get_dingtalk_settings().DINGTALK_AGENT_ID

        if not agent_id:
            logger.warning("DINGTALK_AGENT_ID 未配置，跳过工作通知")
            return

        try:
            await client.post("topapi/message/corpconversation/asyncsend_v2", json_data={
                "agent_id": agent_id,
                "userid_list": ",".join(user_ids),
                "msg": {
                    "msgtype": "markdown",
                    "markdown": {
                        "title": title,
                        "text": markdown_text,
                    },
                },
            })
            logger.info("工作通知已发送给 %s", user_ids)
        except DingTalkError as e:
            logger.error("工作通知发送失败: %s", e)

    async def send_oa_notice(
        self,
        user_ids: list[str],
        title: str,
        content: str,
        message_url: str = "",
    ):
        """
        发送 OA 消息通知（带详情链接）。
        """
        client = get_dingtalk_client()
        from app.dingtalk.config import get_dingtalk_settings
        agent_id = get_dingtalk_settings().DINGTALK_AGENT_ID

        if not agent_id:
            logger.warning("DINGTALK_AGENT_ID 未配置，跳过工作通知")
            return

        try:
            await client.post("topapi/message/corpconversation/asyncsend_v2", json_data={
                "agent_id": agent_id,
                "userid_list": ",".join(user_ids),
                "msg": {
                    "msgtype": "oa",
                    "oa": {
                        "message_url": message_url,
                        "head": {
                            "bgcolor": "FFBBBBBB",
                            "text": title,
                        },
                        "body": {
                            "content": content,
                        },
                    },
                },
            })
        except DingTalkError as e:
            logger.error("OA 通知发送失败: %s", e)


_notifier: WorkNotifier | None = None


def get_work_notifier() -> WorkNotifier:
    global _notifier
    if _notifier is None:
        _notifier = WorkNotifier()
    return _notifier
