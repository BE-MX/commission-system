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
    test_source, _validate_source_config,
)

# 抓取 (供其他业务模块复用)
from app.insight.fetcher import (  # noqa: F401
    filter_items, fetch_rss, fetch_html, fetch_aihot_daily,
)

# 情报条目
from app.insight.item_service import (  # noqa: F401
    list_items, get_item, create_item, update_item, toggle_feature,
    update_status, batch_toggle_feature, batch_update_status, upload_manual_md,
)

# 采集引擎
from app.insight.collector_service import (  # noqa: F401
    collect_source, run_collection_batch,
)

# 情报速览
from app.insight.intelligence_service import (  # noqa: F401
    generate_intelligence_report, list_intelligence_reports,
    get_intelligence_report_html, delete_intelligence_report, pin_report,
)

# 定时规则
from app.insight.schedule_service import (  # noqa: F401
    list_rules, get_rule, create_rule, update_rule, toggle_rule, delete_rule,
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

# 外部账号绑定
from app.insight.external_binding_service import (  # noqa: F401
    resolve_owner, ensure_candidate, list_candidates,
    bind_candidate, ignore_candidate,
    get_user_bindings, create_binding, delete_binding,
)

# 客户机会
from app.insight.customer_opportunity_service import (  # noqa: F401
    import_accio_inquiries, get_opportunity, list_my_opportunities,
    list_all_opportunities, list_unassigned_opportunities, get_opportunity_stats,
    update_opportunity_status, add_opportunity_feedback, assign_opportunity,
)

# 客户经营雷达
from app.insight.customer_profile_service import (  # noqa: F401
    get_or_create_profile, get_profile, get_profile_by_opportunity,
    ingest_opportunity_event, list_profiles,
)
from app.insight.customer_radar_service import (  # noqa: F401
    generate_daily_actions, get_daily_focus, get_thread_counts,
    complete_action, dismiss_action, snooze_action, submit_feedback,
)
from app.insight.customer_source_service import (  # noqa: F401
    get_source_records, add_manual_note,
)
