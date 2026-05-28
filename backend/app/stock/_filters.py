"""备货管理 — 列表筛选 SQL 助手 (overview / safety 共享)"""

from typing import Any, Optional


def _add_in_clause(
    field_expr: str,
    param_prefix: str,
    raw_value: Optional[str],
    clauses: list[str],
    params: dict[str, Any],
) -> None:
    """逗号分隔多值 → SQL IN 子句"""
    if not raw_value:
        return
    vals = [v for v in raw_value.split(",") if v]
    if not vals:
        return
    placeholders = ",".join(f":{param_prefix}{i}" for i in range(len(vals)))
    clauses.append(f"{field_expr} IN ({placeholders})")
    for i, v in enumerate(vals):
        params[f"{param_prefix}{i}"] = v


def name_filter_clauses(
    model: Optional[str] = None,
    product_type: Optional[str] = None,
    size: Optional[str] = None,
    color: Optional[str] = None,
    weight: Optional[str] = None,
) -> tuple[str, dict[str, Any]]:
    """产品型号 + 名称按 '/' 拆分的筛选 SQL 片段。

    颜色规则: name 拆段 >=5 段且倒数第 3 段以 # 开头 → 倒数第 3/2 段拼接,否则 → 倒数第 2 段。
    返回 (附加 SQL 片段, 命名参数 dict)。
    """
    clauses: list[str] = []
    params: dict[str, Any] = {}
    _add_in_clause("p.model", "m", model, clauses, params)
    _add_in_clause("SUBSTRING_INDEX(p.name, '/', 1)", "t", product_type, clauses, params)
    _add_in_clause(
        "SUBSTRING_INDEX(SUBSTRING_INDEX(p.name, '/', 2), '/', -1)",
        "s", size, clauses, params,
    )
    _add_in_clause(
        """CASE
            WHEN (LENGTH(p.name) - LENGTH(REPLACE(p.name, '/', '')) + 1) >= 5
                 AND SUBSTRING_INDEX(SUBSTRING_INDEX(p.name, '/', -3), '/', 1) LIKE '#%'
            THEN CONCAT(
                SUBSTRING_INDEX(SUBSTRING_INDEX(p.name, '/', -3), '/', 1),
                '/',
                SUBSTRING_INDEX(SUBSTRING_INDEX(p.name, '/', -2), '/', 1)
            )
            ELSE SUBSTRING_INDEX(SUBSTRING_INDEX(p.name, '/', -2), '/', 1)
        END""",
        "c", color, clauses, params,
    )
    _add_in_clause("SUBSTRING_INDEX(p.name, '/', -1)", "w", weight, clauses, params)
    sql = " AND ".join(clauses)
    return (f"AND {sql}" if sql else ""), params
