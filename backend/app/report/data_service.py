"""报表中心 — 数据组装服务

按 report_code 分发到对应的数据查询函数。
新增报表只需加一个函数 + 注册到 _DATA_DISPATCH 表。
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings

logger = logging.getLogger("report")

# 预留最大列槽位数（order 中实际出现的 product_remark+size2 组合数不会超过此值）
_MAX_PIVOT_COLS = 30


# ── 订单打印数据 ─────────────────────────────────────────


def _pivot_items(rows: List[Dict]) -> Dict[str, Any]:
    """将长格式 rows 透视为宽格式，供 Stimulsoft 普通 Table 使用。

    输入: [{color2, product_remark, size2, qty}, ...]
    输出: {column_defs, rows, col_totals}
    """
    # 1) 收集所有唯一列组合 (product_remark, size2)，按出现顺序保持
    seen_cols: OrderedDict[tuple, int] = OrderedDict()  # (remark, size2) -> col index
    row_map: OrderedDict[str, Dict] = OrderedDict()  # color2 -> {col_N: qty}

    for r in rows:
        col_key = (r["product_remark"] or "", r["size2"] or "")
        if col_key not in seen_cols:
            seen_cols[col_key] = len(seen_cols)

        color = r["color2"] or ""
        if color not in row_map:
            row_map[color] = {
                "color2": color,
                "color": r.get("color", ""),
                "production_color_requirement": r.get("production_color_requirement", ""),
            }

        col_idx = seen_cols[col_key]
        row_map[color][f"col_{col_idx}"] = row_map[color].get(f"col_{col_idx}", 0) + (r["qty"] or 0)

    # 2) 构造 column_defs
    column_defs: List[Dict[str, str]] = []
    for (remark, size2), idx in seen_cols.items():
        column_defs.append({
            "key": f"col_{idx}",
            "group": remark,   # 一级表头: product_remark
            "label": size2,    # 二级表头: size2
        })

    # 3) 构造 rows（补齐所有列 + 行合计）
    result_rows = []
    for color2, data in row_map.items():
        row_total = 0
        for idx in range(len(seen_cols)):
            key = f"col_{idx}"
            val = data.get(key, 0)
            data[key] = val
            row_total += val
        data["row_total"] = row_total
        result_rows.append(data)

    # 4) 构造列合计
    col_totals = {}
    grand_total = 0
    for idx in range(len(seen_cols)):
        key = f"col_{idx}"
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
      column_defs: [{key, group(product_remark), label(size2)}]
      rows: [{color2, color, production_color_requirement, col_0..col_N, row_total}]
      col_totals: {col_0..col_N, grand_total}
    """
    settings = get_settings()
    business_db = settings.BUSINESS_DB_NAME

    # ── header ───────────────────────────────────────────
    header_sql = text(f"""
        SELECT
            o.order_no,
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
        "remark": header_row["remark"] or "",
    }

    # ── items（长格式）────────────────────────────────────
    items_sql = text(f"""
        SELECT
            o.order_no,
            p.color,
            IFNULL(p.production_color_requirement, '') AS production_color_requirement,
            CONCAT_WS('', NULLIF(p.color, ''), NULLIF(p.production_color_requirement, '')) AS color2,
            IFNULL(p.product_remark, '') AS product_remark,
            p.size,
            IFNULL(p.production_size_requirement, '') AS production_size_requirement,
            CONCAT_WS('', NULLIF(p.size, ''), NULLIF(p.production_size_requirement, '')) AS size2,
            CAST(SUM(oi.order_qty) AS SIGNED) AS qty
        FROM ark_production_order_items oi
        JOIN ark_production_orders o ON o.id = oi.order_id
        LEFT JOIN `{business_db}`.okki_products p ON p.product_id = oi.product_id
        WHERE o.order_no = :order_no
          AND o.deleted_flag = 0
        GROUP BY
            o.order_no,
            p.color,
            p.production_color_requirement,
            p.product_remark,
            p.size,
            p.production_size_requirement
        ORDER BY
            color2,
            product_remark,
            size2
    """)
    rows = db.execute(items_sql, {"order_no": order_no}).mappings().all()

    long_items = []
    for r in rows:
        long_items.append({
            "order_no": r["order_no"],
            "color": r["color"] or "",
            "production_color_requirement": r["production_color_requirement"] or "",
            "color2": r["color2"] or "",
            "product_remark": r["product_remark"] or "",
            "size": r["size"] or "",
            "production_size_requirement": r["production_size_requirement"] or "",
            "size2": r["size2"] or "",
            "qty": int(r["qty"]) if r["qty"] else 0,
        })

    # ── 透视 ─────────────────────────────────────────────
    pivoted = _pivot_items(long_items)

    return {
        "header": header,
        **pivoted,
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
                sample_cols.append({"key": f"col_{i}", "group": f"等级{i+1}", "label": f"尺寸{i+1}"})
            sample_row = {
                "color2": "样例色号",
                "color": "1B",
                "production_color_requirement": "",
                "row_total": 0,
            }
            for i in range(3):
                sample_row[f"col_{i}"] = 0
            sample_totals = {f"col_{i}": 0 for i in range(3)}
            sample_totals["grand_total"] = 0
            return {
                "header": {"company_name": "", "order_no": "", "remark": ""},
                "column_defs": sample_cols,
                "rows": [sample_row],
                "col_totals": sample_totals,
                "total_cols": 3,
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
