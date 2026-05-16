"""方舟洞见 — service facade

历史上是 1637 行单文件。阶段二拆分后此处仅 re-export 各子模块,
保留以兼容 router/scheduler 调用方:
  - app/insight/router.py: 调 `service.upload_case(...)` 等
  - app/insight/scheduler.py: 调 `service.generate_industry_daily_report` 等
  - app/api/tracking.py (已不存在)、其他模块 也通过 `from app.insight.service import ...`

新代码建议直接 import 子模块:
  - reports_service / sources_service / fetcher / case_library_service
  - meeting_minutes_service / ai_helpers / dashboard_service
"""

# 报告
from app.insight.reports_service import (  # noqa: F401
    list_reports, get_report, get_report_html,
    import_report, regenerate_report,
    render_industry_daily_html, render_ai_tools_html,
    generate_industry_daily_report, generate_ai_tools_report,
)

# 信源 CRUD
from app.insight.sources_service import (  # noqa: F401
    list_sources, get_source, create_source, update_source, delete_source,
    test_source,
)

# 抓取 (供其他业务模块复用)
from app.insight.fetcher import (  # noqa: F401
    filter_items, fetch_rss, fetch_html, fetch_aihot_daily,
)

# 案例库
from app.insight.case_library_service import (  # noqa: F401
    upload_case, manual_create_case, get_case_status, publish_case,
    update_case, list_cases, get_case_detail, delete_case, toggle_case_like,
)

# 周会纪要
from app.insight.meeting_minutes_service import (  # noqa: F401
    upload_minutes, get_minutes_status, list_minutes, get_minutes_detail,
    update_task, export_tasks_csv,
)

# 工作台
from app.insight.dashboard_service import (  # noqa: F401
    get_dashboard_summary,
)
