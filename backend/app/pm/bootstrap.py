"""PM Hub 启动钩子：pm_diff preset 自动初始化 + 差异管线看门狗 + 存储目录自检。

在 app/main.py lifespan 中调用 init_pm_module()。任何一步失败只告警不阻塞启动。
"""

import logging

from app.pm.diff_service import DIFF_PRESET, DIFF_SYSTEM_PROMPT, recover_stale_diffs
from app.pm.service import ensure_storage_root

logger = logging.getLogger("commission")


def init_pm_module() -> None:
    try:
        ensure_storage_root()
    except OSError as exc:  # 存储目录不可建不阻塞平台启动（首次上传时会再报）
        logger.warning("[PM] storage root init failed: %s", exc)
        print(f"[PM] storage root init failed: {exc}", flush=True)
    _seed_diff_preset()
    recover_stale_diffs()


def _seed_diff_preset() -> None:
    """复用 seed_ai 的幂等创建器（同名跳过；无 provider 时告警不阻塞）。"""
    try:
        from app.bootstrap.seed_ai import _auto_create_preset
        _auto_create_preset(
            preset_name=DIFF_PRESET,
            system_prompt=DIFF_SYSTEM_PROMPT,
            parameters={"temperature": 0.2, "max_tokens": 1024},
            description="PM协作站：资料版本本地 diff → AI 差异概要",
        )
    except Exception as exc:
        logger.warning("[PM] seed pm_diff preset skipped: %s", exc)
        print(f"[PM] seed pm_diff preset skipped: {exc}", flush=True)
