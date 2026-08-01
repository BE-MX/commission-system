"""名片询盘钉钉群推送。

尽力而为：webhook 未配置或请求失败只记日志返回 False，绝不影响询盘落库
（调用方已 commit，且在 daemon 线程里跑——客户提交不等钉钉接口）。
"""

import asyncio
import logging

logger = logging.getLogger("commission.card")


def push_inquiry(salesperson_name: str, contact: str, message: str, matched: bool) -> bool:
    try:
        from app.dingtalk.webhook import get_webhook_sender

        text = "\n".join([
            f"### 📇 名片询盘 · {salesperson_name}",
            "",
            f"- 联系方式：{contact}",
            f"- 建档客户：{'已命中' if matched else '未建档'}",
            "",
            f"> {message[:500]}",
            "",
            "处理：主站 → 展会营销 → 名片管家 → 客户询盘",
        ])
        sender = get_webhook_sender()
        # send_markdown 是 async；本函数在无事件循环的 daemon 线程里调用，
        # 必须 asyncio.run 真正执行——同步裸调只构造协程、恒"假成功"
        # （training push_service 2026-07-17 对抗性审查 P0 同款坑）
        return bool(
            asyncio.run(
                sender.send_markdown(title=f"名片询盘 · {salesperson_name}", text=text)
            )
        )
    except Exception as e:  # noqa: BLE001
        msg = f"[card] inquiry dingtalk push failed: {e}"
        logger.warning(msg)
        print(msg, flush=True)
        return False
