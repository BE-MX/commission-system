"""报表中心 — 数据组装服务

按 report_code 分发到对应的数据查询函数。
新增报表只需加一个函数 + 注册到 _DATA_DISPATCH 表。
"""

from __future__ import annotations

import logging
from collections import OrderedDict
import re as _re
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings

logger = logging.getLogger("report")


def _extract_weight_grams(product_name: str) -> float:
    """从 product_name 中提取克重。

    规则：取最后一个字母 'g' 和最后一个 '/' 之间的数字。
    例如 "莱莎仿生手织发帘/12寸/100g/自然色" → 100
    如果匹配不到返回 0。
    """
    if not product_name:
        return 0.0
    # 找最后一个 'g' 的位置
    last_g = product_name.rfind('g')
    if last_g < 0:
        return 0.0
    # 找最后一个 '/' 的位置（在 last_g 之前）
    last_slash = product_name.rfind('/', 0, last_g)
    if last_slash < 0:
        return 0.0
    segment = product_name[last_slash + 1:last_g].strip()
    try:
        return float(segment)
    except (ValueError, TypeError):
        return 0.0

# 预留最大列槽位数（order 中实际出现的 product_remark+size2 组合数不会超过此值）
_MAX_PIVOT_COLS = 30


# ── 订单打印数据 ─────────────────────────────────────────


def _pivot_items(rows: List[Dict]) -> Dict[str, Any]:
    """将长格式 rows 透视为宽格式，供 Stimulsoft 普通 Table 使用。

    输入: [{color, production_color_requirement, product_remark, size, production_size_requirement, qty}, ...]
    输出: {column_defs, rows, col_totals}
    """
    # 1) 收集所有唯一列组合 (product_remark, size)，按出现顺序保持
    seen_cols: OrderedDict[tuple, int] = OrderedDict()  # (remark, size) -> col index
    col_details: Dict[tuple, Dict] = {}  # (remark, size) -> {size, size_req}
    row_map: OrderedDict[str, Dict] = OrderedDict()  # color -> {col_N: qty}

    for r in rows:
        col_key = (r["product_remark"] or "", r["size"] or "")
        if col_key not in seen_cols:
            seen_cols[col_key] = len(seen_cols)
            col_details[col_key] = {
                "size": r.get("size", ""),
                "size_req": r.get("production_size_requirement", ""),
            }

        color = r["color"] or ""
        if color not in row_map:
            row_map[color] = {
                "color": r.get("color", ""),
                "production_color_requirement": r.get("production_color_requirement", ""),
            }

        col_idx = seen_cols[col_key]
        row_map[color][f"col_{col_idx}"] = row_map[color].get(f"col_{col_idx}", 0) + (r["qty"] or 0)

    # 2) 构造 column_defs — 按 group 排序，相同 group 的列排在一起
    # 先按 (remark, size) 的出现顺序记录，再按 remark 聚合排序
    sorted_cols: List[tuple] = sorted(
        seen_cols.items(),
        key=lambda item: (item[0][0], item[0][1])  # (remark, size) 排序
    )
    # 重新编号
    column_defs: List[Dict[str, str]] = []
    new_idx = 0
    old_to_new: Dict[int, int] = {}  # old col_idx -> new col_idx
    for (remark, size_val), old_idx in sorted_cols:
        detail = col_details[(remark, size_val)]
        old_to_new[old_idx] = new_idx
        column_defs.append({
            "key": f"col_{new_idx}",
            "group": remark,   # 一级表头: product_remark
            "size": detail["size"],
            "size_req": detail["size_req"],
        })
        new_idx += 1

    # 3) 构造 rows — 用新编号重映射列值，补齐 + 行合计
    result_rows = []
    for color, data in row_map.items():
        row_total = 0
        new_data = {
            "color": data["color"],
            "production_color_requirement": data["production_color_requirement"],
        }
        for new_i, ((remark, size_val), old_idx) in enumerate(sorted_cols):
            key = f"col_{new_i}"
            val = data.get(f"col_{old_idx}", 0)
            new_data[key] = val
            row_total += val
        new_data["row_total"] = row_total
        result_rows.append(new_data)

    # 4) 构造列合计
    col_totals = {}
    grand_total = 0
    for new_i in range(len(sorted_cols)):
        key = f"col_{new_i}"
        total = sum(r.get(key, 0) for r in result_rows)
        col_totals[key] = total
        grand_total += total
    col_totals["grand_total"] = grand_total

    return {
        "column_defs": column_defs,
        "rows": result_rows,
        "col_totals": col_totals,
        "total_cols": len(column_defs),  # 模板用：知道实际有多少列
    }


def get_production_order_print_data(db: Session, order_no: str) -> Dict[str, Any]:
    """生产订单打印数据：header + 透视后的宽格式数据。

    宽格式结构:
      column_defs: [{key, group(product_remark), size, size_req}]
      rows: [{color, production_color_requirement, col_0..col_N, row_total}]
      col_totals: {col_0..col_N, grand_total}
    """
    settings = get_settings()
    business_db = settings.BUSINESS_DB_NAME

    # ── header ───────────────────────────────────────────
    header_sql = text(f"""
        SELECT
            o.order_no,
            o.batch_no,
            o.remark,
            o.created_at
        FROM ark_production_orders o
        WHERE o.order_no = :order_no AND o.deleted_flag = 0
    """)
    header_row = db.execute(header_sql, {"order_no": order_no}).mappings().first()
    if not header_row:
        return {"header": {}, "column_defs": [], "rows": [], "col_totals": {}, "total_cols": 0}

    header = {
        "company_name": "青岛丽丝发制品有限公司",
        "order_no": header_row["order_no"],
        "batch_no": header_row["batch_no"] or "",
        "remark": header_row["remark"] or "",
    }

    # ── items（长格式）────────────────────────────────────
    items_sql = text(f"""
        SELECT
            o.order_no,
            p.color,
            MAX(IFNULL(p.production_color_requirement, '')) AS production_color_requirement,
            IFNULL(p.product_remark, '') AS product_remark,
            p.size,
            MAX(IFNULL(p.production_size_requirement, '')) AS production_size_requirement,
            CAST(SUM(oi.order_qty) AS SIGNED) AS qty
        FROM ark_production_order_items oi
        JOIN ark_production_orders o ON o.id = oi.order_id
        LEFT JOIN `{business_db}`.okki_products p ON p.product_id = oi.product_id
        WHERE o.order_no = :order_no
          AND o.deleted_flag = 0
        GROUP BY
            o.order_no,
            p.color,
            p.product_remark,
            p.size
        ORDER BY
            p.color,
            p.product_remark,
            p.size
    """)
    rows = db.execute(items_sql, {"order_no": order_no}).mappings().all()

    long_items = []
    for r in rows:
        color = r["color"] or ""
        prod_remark = r["product_remark"] or ""
        size = r["size"] or ""
        # 过滤：LEFT JOIN okki_products 时 product_remark/size 为 NULL 的行不入透视
        if not prod_remark and not size:
            continue
        long_items.append({
            "color": color,
            "production_color_requirement": r["production_color_requirement"] or "",
            "product_remark": prod_remark,
            "size": size,
            "production_size_requirement": r["production_size_requirement"] or "",
            "qty": int(r["qty"]) if r["qty"] else 0,
        })

    # ── 透视 ─────────────────────────────────────────────
    pivoted = _pivot_items(long_items)

    # ── 公斤数统计 ───────────────────────────────────────
    # 查询每个 order_item 的 product_name + order_qty，用于克重计算
    weight_sql = text(f"""
        SELECT
            p.color,
            IFNULL(p.product_remark, '') AS product_remark,
            p.size,
            IFNULL(p.production_size_requirement, '') AS production_size_requirement,
            oi.product_name,
            oi.order_qty
        FROM ark_production_order_items oi
        JOIN ark_production_orders o ON o.id = oi.order_id
        LEFT JOIN `{business_db}`.okki_products p ON p.product_id = oi.product_id
        WHERE o.order_no = :order_no
          AND o.deleted_flag = 0
    """)
    weight_rows = db.execute(weight_sql, {"order_no": order_no}).mappings().all()

    # 按 (product_remark, size) 累加公斤数，以及 T色 / 纯色 分别统计
    weight_pure_map: Dict[str, float] = {}  # col_key -> kg (纯色：排除 T)
    weight_t_map: Dict[str, float] = {}     # col_key -> kg (T色 only)
    for wr in weight_rows:
        remark = wr["product_remark"] or ""
        size = wr["size"] or ""
        if not remark and not size:
            continue
        col_key = f"{remark}|{size}"
        grams = _extract_weight_grams(wr["product_name"] or "")
        qty = int(wr["order_qty"]) if wr["order_qty"] else 0
        kg = round(grams * qty / 1000, 1)

        color = wr["color"] or ""
        is_t_color = "T" in color.upper()

        # 纯色：排除含 T 的
        if not is_t_color:
            weight_pure_map[col_key] = round(weight_pure_map.get(col_key, 0) + kg, 1)
        # T色：只统计含 T 的
        if is_t_color:
            weight_t_map[col_key] = round(weight_t_map.get(col_key, 0) + kg, 1)

    # 映射到 pivoted column_defs 的 key
    weight_pure_totals = {}
    weight_t_totals = {}
    for col_def in pivoted["column_defs"]:
        col_key = f"{col_def['group']}|{col_def['size']}"
        weight_pure_totals[col_def["key"]] = weight_pure_map.get(col_key, 0)
        weight_t_totals[col_def["key"]] = weight_t_map.get(col_key, 0)

    weight_pure_totals["grand_total"] = round(sum(weight_pure_totals.values()), 1)
    weight_t_totals["grand_total"] = round(sum(weight_t_totals.values()), 1)

    return {
        "header": header,
        **pivoted,
        "weight_totals": weight_pure_totals,
        "weight_t_totals": weight_t_totals,
    }


# ── 工序卡片打印数据 ──────────────────────────────────────


def get_process_card_print_data(db: Session, order_no: str) -> Dict[str, Any]:
    """工序卡片打印数据：按订单明细列出每个产品的工序卡片信息，含二维码 base64。"""
    from app.production.report_service import get_qrcode

    sql = text("""
        SELECT
            oi.id,
            oi.product_name,
            oi.model,
            oi.order_qty,
            o.batch_no,
            o.created_at
        FROM ark_production_order_items oi
        LEFT JOIN ark_production_orders o ON oi.order_id = o.id
        WHERE o.order_no = :order_no AND o.deleted_flag = 0
    """)
    rows = db.execute(sql, {"order_no": order_no}).mappings().all()

    items = []
    for r in rows:
        qr_code_base64 = ""
        try:
            qr_result = get_qrcode(db, r["id"], box_size=4)
            qr_code_base64 = qr_result.get("qr_code", "")
        except Exception:
            pass

        items.append({
            "id": r["id"],
            "product_name": r["product_name"] or "",
            "model": r["model"] or "",
            "order_qty": int(r["order_qty"]) if r["order_qty"] else 0,
            "batch_no": r["batch_no"] or "",
            "created_at": str(r["created_at"]) if r["created_at"] else "",
            "qr_code": qr_code_base64,
        })

    return {"items": items}


# ── 分发表 ───────────────────────────────────────────────

_DATA_DISPATCH = {
    "production_order_print": get_production_order_print_data,
    "process_card_print": get_process_card_print_data,
}


def get_report_data(db: Session, report_code: str, params: Optional[Dict] = None) -> Dict[str, Any]:
    """根据 report_code 分发到对应的数据查询函数。

    Args:
        db: SQLAlchemy session
        report_code: 报表编码
        params: 查询参数，如 {"order_no": "PO20260601-001"}

    Returns:
        报表数据字典
    """
    handler = _DATA_DISPATCH.get(report_code)
    if not handler:
        raise ValueError(f"未知的报表编码: {report_code}")

    params = params or {}

    if report_code == "production_order_print":
        order_no = params.get("order_no", "")
        # 设计器打开时可能传空 order_no，返回带样例行的结构让字典树有完整字段定义
        if not order_no:
            # 构造 3 列样例，让 Stimulsoft 字典树识别所有 col_0..col_2 + row_total
            sample_cols = []
            for i in range(3):
                sample_cols.append({"key": f"col_{i}", "group": f"等级{i+1}", "size": f"尺寸{i+1}", "size_req": ""})
            sample_row = {
                "color": "1B",
                "production_color_requirement": "",
                "row_total": 0,
            }
            for i in range(3):
                sample_row[f"col_{i}"] = 0
            sample_totals = {f"col_{i}": 0 for i in range(3)}
            sample_totals["grand_total"] = 0
            sample_weight = {f"col_{i}": 0.0 for i in range(3)}
            sample_weight["grand_total"] = 0.0
            sample_weight_t = {f"col_{i}": 0.0 for i in range(3)}
            sample_weight_t["grand_total"] = 0.0
            return {
                "header": {"company_name": "", "order_no": "", "batch_no": "", "remark": ""},
                "column_defs": sample_cols,
                "rows": [sample_row],
                "col_totals": sample_totals,
                "total_cols": 3,
                "weight_totals": sample_weight,
                "weight_t_totals": sample_weight_t,
            }
        return handler(db, order_no)

    if report_code == "process_card_print":
        order_no = params.get("order_no", "")
        if not order_no:
            return {
                "items": [{
                    "id": 0, "product_name": "", "model": "",
                    "order_qty": 0, "batch_no": "", "created_at": "",
                    "qr_code": "",
                }],
            }
        return handler(db, order_no)

    return handler(db, **params)
