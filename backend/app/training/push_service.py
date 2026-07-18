"""培训速递 — 发布后钉钉群推送（群机器人 actionCard，发布主流程失败不受推送影响）"""

import asyncio
import logging

from app.core.config import get_settings
from app.training.models import TrainingDigest
from app.training.schemas import DigestSections

logger = logging.getLogger("commission")


def detail_url(digest_id: int) -> str:
    base = get_settings().TRAINING_DETAIL_BASE_URL.rstrip("/")
    return f"{base}/{digest_id}"


def push_published(digest: TrainingDigest, creator_name: str) -> bool:
    """发布即推群卡片：标题 + 一句话总结 + 前 3 条重点 + 详情链接。

    尽力而为：webhook 未配置或请求失败只记日志返回 False，不影响发布事务
    （发布在调用方已 commit，推送失败可在详情页手动重推）。
    """
    try:
        from app.dingtalk.webhook import get_webhook_sender

        sections = DigestSections.model_validate(digest.sections_json or {})
        points = [h.title.strip() for h in sections.highlights if h.title.strip()][:3]
        lines = [
            f"### 📚 培训速递 · {digest.title}",
            "",
            f"> {digest.summary or ''}",
            "",
        ]
        for i, p in enumerate(points, start=1):
            lines.append(f"{i}. {p}")
        lines += [
            "",
            f"讲师：{digest.lecturer or '—'} · 参训：{creator_name}"
            f" · 约 {digest.read_minutes} 分钟读完",
        ]
        sender = get_webhook_sender()
        # send_action_card 是 async；本函数只在 sync 路由（线程池，无事件循环）里调用，
        # 用 asyncio.run 真正执行——同步裸调只会构造协程、恒"假成功"（2026-07-17 对抗性审查 P0）
        return bool(
            asyncio.run(
                sender.send_action_card(
                    title=f"培训速递 · {digest.title}",
                    text="\n".join(lines),
                    btns=[{"title": "查看完整速览", "actionURL": detail_url(digest.id)}],
                )
            )
        )
    except Exception as e:  # noqa: BLE001
        msg = f"[training] dingtalk push failed digest={digest.id}: {e}"
        logger.warning(msg)
        print(msg, flush=True)
        return False
