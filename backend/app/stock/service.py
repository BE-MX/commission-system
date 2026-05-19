"""备货管理 — service facade

历史上是 667 行单文件。阶段二拆分后此处仅 re-export 各子模块,
保留以兼容 router/scheduler 调用方:
  - app/stock/router.py: 调 `service.query_stock_overview(...)` 等
  - app/stock/scheduler.py: 调日报相关函数

新代码建议直接 import 子模块:
  - constants / sku_query / overview_service / safety_service / daily_report_service
"""

# 常量与状态计算
from app.stock.constants import (  # noqa: F401
    VALID_ORDER_FILTER,
    TFT_SERVICE_ENABLED, TFT_SERVICE_URL,
    SOURCE_MANUAL, SOURCE_FORMULA, SOURCE_TFT, SOURCE_INSUFFICIENT,
    calc_status, calc_suggested_qty,
)

# 私有兼容: 历史 _source_label / _source_code (router 不应直接用,但保留兼容)
from app.stock.constants import source_label as _source_label  # noqa: F401
from app.stock.constants import source_code as _source_code  # noqa: F401

# 销量查询
from app.stock.sku_query import (  # noqa: F401
    get_sku_sales, query_all_sku_status,
)

# 销量备货一览
from app.stock.overview_service import (  # noqa: F401
    query_stock_overview, get_filter_options,
)

# 安全库存 CRUD + AI 建议
from app.stock.safety_service import (  # noqa: F401
    query_safety_stock_list, save_safety_stock,
    get_safety_stock_suggestion, batch_generate_suggestions,
)

# 日报
from app.stock.daily_report_service import (  # noqa: F401
    upsert_daily_report, get_daily_report,
    mark_daily_report_pushed, get_stock_recipients,
)
