"""设计预约 — service facade

历史上是 1074 行单文件。阶段二拆分后此处仅 re-export 各子模块,
保留以兼容 router/scheduler 调用方:
  - app/design/router.py: 调 `service.create_request(...)` 等
  - app/design/scheduler.py: 调 `service.check_today_shoot_reminders` 等

新代码建议直接 import 子模块:
  - request_service / schedule_service / stats_service / import_service
  - audit_log (审计日志写入 helper)
"""

# 请求 / 审批 / 操作 / 修改
from app.design.request_service import (  # noqa: F401
    create_request, audit_request, action_request,
    update_request_remark, update_request_shoot_type, update_task_shoot_type,
)

# 排期 / 容量 / 不可日 / 调度模式 / 甘特图
from app.design.schedule_service import (  # noqa: F401
    get_gantt_data, reschedule_task,
    create_unavailable_dates, delete_unavailable_date,
    get_capacity, update_capacity,
    get_scheduling_mode_info, update_scheduling_mode,
)

# 统计 / 导出
from app.design.stats_service import (  # noqa: F401
    export_tasks_excel, get_design_stats,
)

# 批量导入
from app.design.import_service import (  # noqa: F401
    batch_import_requests,
)

# 审计日志 helper (兼容历史 _write_audit_log 调用)
from app.design.audit_log import write_audit_log as _write_audit_log  # noqa: F401
