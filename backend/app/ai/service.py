"""AI 接入模块 — service facade

历史上是一个单文件大模块。阶段二拆分后此文件只是 re-export 各子 service,
保留以兼容现有调用方:
  - app/ai/router.py: 用 `service.list_providers(...)` 等
  - app/services/tracking/...,  app/insight/service.py 等业务代码:
    `from app.ai.service import chat`

新代码建议直接 import 子模块:
  - provider_service / preset_service / call_service / log_service / keyring / http_client
"""

from app.ai.provider_service import (  # noqa: F401
    list_providers, get_provider, create_provider,
    update_provider, delete_provider, test_provider,
)
from app.ai.preset_service import (  # noqa: F401
    list_presets, get_preset, create_preset,
    update_preset, delete_preset, test_preset, test_preset_with_image,
)
from app.ai.call_service import (  # noqa: F401
    chat, delegate, get_task_result,
)
from app.ai.log_service import (  # noqa: F401
    list_logs, get_log,
)
