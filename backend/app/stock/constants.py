"""备货管理 — 公共常量与状态计算

订单口径与提成模块一致 (status / departments 过滤)。
TFT 微服务配置可选,默认关闭走公式兜底。
"""

import os

# ── 订单口径 (与提成模块一致) ──────────────────────────────
VALID_ORDER_FILTER = """
    (
        o.status = 13972831656
        OR (o.status = 13972831654 AND o.status_name = '已结清')
    )
    AND (
        o.departments LIKE '%"department_id": 24925%'
        OR o.departments LIKE '%"department_id": 24926%'
        OR o.departments LIKE '%"department_id": 25198%'
        OR o.departments LIKE '%"department_id": 258938%'
        OR o.departments LIKE '%"department_id": 258940%'
        OR o.departments LIKE '%"department_id": 258941%'
        OR o.departments LIKE '%"department_id": 258942%'
    )
"""

# ── TFT 配置 ─────────────────────────────────────────────
TFT_SERVICE_ENABLED = os.environ.get("TFT_SERVICE_ENABLED", "").lower() in {"1", "true", "yes"}
TFT_SERVICE_URL = os.environ.get("TFT_SERVICE_URL", "")

# ── 来源枚举 ─────────────────────────────────────────────
SOURCE_MANUAL = "manual"
SOURCE_FORMULA = "formula"
SOURCE_TFT = "tft"
SOURCE_INSUFFICIENT = "insufficient_data"


# ── 状态计算 ──────────────────────────────────────────────


def calc_status(enable_count: float, safety_stock: int) -> str:
    """库存状态: unset / shortage / warning / sufficient"""
    if not safety_stock or safety_stock == 0:
        return "unset"
    if enable_count < safety_stock:
        return "shortage"
    if enable_count < safety_stock * 1.5:
        return "warning"
    return "sufficient"


def calc_suggested_qty(enable_count: float, safety_stock: int) -> int:
    """建议备货量 = max(0, safety_stock × 2 - enable_count)"""
    return max(0, int(safety_stock) * 2 - int(enable_count))


def source_label(code: int) -> str:
    """source 整数码 → 字符串标签"""
    return {0: SOURCE_MANUAL, 1: SOURCE_FORMULA, 2: SOURCE_TFT}.get(int(code or 0), SOURCE_MANUAL)


def source_code(label: str) -> int:
    """source 字符串 → 整数码"""
    return {SOURCE_MANUAL: 0, SOURCE_FORMULA: 1, SOURCE_TFT: 2}.get(label, 0)
