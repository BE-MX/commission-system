"""报表中心 — 数据组装服务

按 report_code 分发到对应的数据查询函数。
新增报表只需加一个函数 + 注册到 _DATA_DISPATCH 表。
"""

from __future__ import annotations

import logging
from collections import OrderedDict
import re as _re
from typing import Any, Dict, List, Optional

from sqlalchemy import bindparam, text
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

# ── 型号分类规则 ─────────────────────────────────────────
# 规则源：发帘与贴发产品清单.xlsx（2026-06-15 更新）
# 每条规则按 Excel 顺序，先命中先胜出（model_includes / model_excludes / unit_includes / unit_excludes 同时满足）
# unit_includes / unit_excludes 为空 = 不限制 unit 字段
# label 中的 \n 在 HTML / Word 中均被渲染为换行
_CATEGORY_RULES: List[Dict[str, Any]] = [
    {  # 1
        "model_includes": ["Deep"], "model_excludes": [],
        "unit_includes": [], "unit_excludes": [],
        "label": "Deep天才发帘 帘宽12“\n20g\n扁头银线3条/包",
    },
    {  # 2
        "model_includes": ["棒棒"], "model_excludes": ["哑光"],
        "unit_includes": [], "unit_excludes": [],
        "label": "棒棒\n1g\n25根/捆 50根/包",
    },
    {  # 3
        "model_includes": ["打孔"], "model_excludes": [],
        "unit_includes": ["60"], "unit_excludes": [],
        "label": "打孔发帘 帘宽33cm\n60g\n扁头银线1条/包",
    },
    {  # 4
        "model_includes": ["打孔"], "model_excludes": [],
        "unit_includes": ["50"], "unit_excludes": [],
        "label": "打孔发帘 帘宽33cm\n50g\n扁头银线1条/包",
    },
    {  # 5
        "model_includes": ["卡子"], "model_excludes": [],
        "unit_includes": [], "unit_excludes": [],
        "label": "机织卡子发\n100g\n银线一套/包",
    },
    {  # 6
        "model_includes": ["机织贴发"], "model_excludes": ["长条"],
        "unit_includes": [], "unit_excludes": [],
        "label": "机织贴发 4*0.8cm\n2.5g\n20片/包",
    },
    {  # 7
        "model_includes": ["贴发", "长条"], "model_excludes": [],
        "unit_includes": [], "unit_excludes": [],
        "label": "机织长条贴发 帘宽14\" 规格：0.8cm\n50g\n1条/包",
    },
    {  # 8
        "model_includes": ["加纱"], "model_excludes": [],
        "unit_includes": [], "unit_excludes": [],
        "label": "加纱天才 帘宽12“\n20g\n扁头银线3条/包",
    },
    {  # 9
        "model_includes": ["迷你", "平型"], "model_excludes": [],
        "unit_includes": [], "unit_excludes": [],
        "label": "迷你平型 0.6*0.6cm\n0.8g\n25根/捆 50根/包",
    },
    {  # 10
        "model_includes": ["平型"], "model_excludes": ["迷你"],
        "unit_includes": [], "unit_excludes": [],
        "label": "平型接发 \n1g\n25根/捆 50根/包",
    },
    {  # 11
        "model_includes": ["三合片"], "model_excludes": [],
        "unit_includes": [], "unit_excludes": [],
        "label": "三合片发帘 先花纹后齐边，帘宽90cm\n150g\n扁头银线1条/包",
    },
    {  # 12
        "model_includes": ["天才", "双层"], "model_excludes": [],
        "unit_includes": [], "unit_excludes": [],
        "label": "双层天才发帘 帘宽12“\n50g\n扁头银线1条/包",
    },
    {  # 13
        "model_includes": ["天才", "12"], "model_excludes": ["双层"],
        "unit_includes": [], "unit_excludes": [],
        "label": "天才发帘 帘宽12“\n20g\n扁头银线3条/包",
    },
    {  # 14
        "model_includes": ["天才", "24"], "model_excludes": ["双层"],
        "unit_includes": [], "unit_excludes": [],
        "label": "天才发帘 帘宽24“\n50g\n扁头银线1条/包",
    },
    {  # 15
        "model_includes": ["贴发"], "model_excludes": ["机织", "长条"],
        "unit_includes": [], "unit_excludes": [],
        "label": "贴发 4*0.8cm\n2.5g\n20片/包",
    },
    {  # 16
        "model_includes": ["铁丝"], "model_excludes": [],
        "unit_includes": [], "unit_excludes": [],
        "label": "铁丝 \n1g\n25根/捆 50根/包",
    },
    {  # 17
        "model_includes": ["哑光棒棒"], "model_excludes": [],
        "unit_includes": [], "unit_excludes": [],
        "label": "哑光棒棒\n1g\n25根/捆 50根/包",
    },
]
_OTHER_CATEGORY_INDEX = -1
_OTHER_LABEL = "其他"


def _classify(model: str, unit: str) -> tuple:
    """按 model + unit 关键字匹配规则，返回 (category_index, category_label)。

    优先级 = Excel 列表顺序，第一条命中即返回。全部不匹配归入 (-1, "其他")。
    """
    model = model or ""
    unit = unit or ""
    for idx, rule in enumerate(_CATEGORY_RULES):
        if (
            all(s in model for s in rule["model_includes"])
            and not any(s in model for s in rule["model_excludes"])
            and all(s in unit for s in rule["unit_includes"])
            and not any(s in unit for s in rule["unit_excludes"])
        ):
            return idx, rule["label"]
    return _OTHER_CATEGORY_INDEX, _OTHER_LABEL


def _split_by_category(long_items: List[Dict]) -> List[tuple]:
    """将长格式 rows 按 (model, unit) 双键分类，返回 [(cat_idx, label, items)]。

    输出顺序：Excel 规则顺序（cat_idx 升序），未匹配的 "其他" 永远放最后。
    """
    buckets: Dict[int, Dict[str, Any]] = {}
    for item in long_items:
        cat_idx, cat_label = _classify(item.get("model", ""), item.get("unit", ""))
        if cat_idx not in buckets:
            buckets[cat_idx] = {"label": cat_label, "items": []}
        buckets[cat_idx]["items"].append(item)
    sorted_keys = sorted(buckets.keys(), key=lambda k: (k == _OTHER_CATEGORY_INDEX, k))
    return [(k, buckets[k]["label"], buckets[k]["items"]) for k in sorted_keys]


def _collect_remarks_for_category(long_items: List[Dict]) -> List[str]:
    """从同分类的 items 中去重收集 product_remark，保持出现顺序。"""
    seen: OrderedDict[str, None] = OrderedDict()
    for item in long_items:
        remark = item.get("product_remark", "")
        if remark and remark not in seen:
            seen[remark] = None
    return list(seen.keys())


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
            o.created_at,
            o.created_by,
            u.real_name AS creator_name
        FROM ark_production_orders o
        LEFT JOIN ark_users u ON u.id = o.created_by
        WHERE o.order_no = :order_no AND o.deleted_flag = 0
    """)
    header_row = db.execute(header_sql, {"order_no": order_no}).mappings().first()
    if not header_row:
        return {"header": {}, "sub_tables": [], "column_defs": [], "rows": [], "col_totals": {}, "total_cols": 0}

    header = {
        "company_name": "青岛丽丝发制品有限公司",
        "order_no": header_row["order_no"],
        "batch_no": header_row["batch_no"] or "",
        "remark": header_row["remark"] or "",
        "creator_name": header_row["creator_name"] or "",
    }

    # ── items（长格式）────────────────────────────────────
    # unit 加入 GROUP BY：分类规则按 (model, unit) 双键判定（如打孔 60g vs 50g 进不同分类）
    items_sql = text(f"""
        SELECT
            o.order_no,
            p.color,
            MAX(IFNULL(p.production_color_requirement, '')) AS production_color_requirement,
            IFNULL(p.product_remark, '') AS product_remark,
            p.size,
            MAX(IFNULL(p.production_size_requirement, '')) AS production_size_requirement,
            oi.model,
            IFNULL(p.unit, '') AS unit,
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
            p.size,
            oi.model,
            p.unit
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
            "model": r["model"] or "",
            "unit": r["unit"] or "",
            "size": size,
            "production_size_requirement": r["production_size_requirement"] or "",
            "qty": int(r["qty"]) if r["qty"] else 0,
        })

    # ── 按 (model, unit) 分类拆分透视 ──────────────────────
    category_splits = _split_by_category(long_items)
    sub_tables = []
    for cat_idx, cat_label, cat_items in category_splits:
        cat_pivoted = _pivot_items(cat_items)
        cat_remarks = _collect_remarks_for_category(cat_items)
        if cat_pivoted["column_defs"]:  # 跳过空表
            sub_tables.append({
                "category_index": cat_idx,
                "category_label": cat_label,  # 含 \n，模板需保留换行
                "category_remarks": cat_remarks,
                **cat_pivoted,
            })

    # ── 中间打孔要求图：任一明细 model 含 "中间打孔" 即在文档末尾插图 ──
    has_middle_punch = any("中间打孔" in (it.get("model") or "") for it in long_items)

    # ── 全量透视（公斤数统计用） ──────────────────────────────
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
        "sub_tables": sub_tables,
        **pivoted,
        "weight_totals": weight_pure_totals,
        "weight_t_totals": weight_t_totals,
        "has_middle_punch": has_middle_punch,
    }


# ── 工序卡片打印数据 ──────────────────────────────────────


def get_process_card_print_data(db: Session, order_no: str) -> Dict[str, Any]:
    """工序卡片打印数据：按订单明细列出每个产品的工序卡片信息，含二维码 base64。"""
    from app.production.report_service import get_qrcode

    settings = get_settings()
    business_db = settings.BUSINESS_DB_NAME

    sql = text(f"""
        SELECT
            oi.id,
            oi.product_id,
            oi.product_name,
            oi.model,
            oi.order_qty,
            o.batch_no,
            o.created_at,
            p.color,
            p.size,
            p.unit,
            p.description,
            p.product_remark
        FROM ark_production_order_items oi
        LEFT JOIN ark_production_orders o ON oi.order_id = o.id
        LEFT JOIN `{business_db}`.okki_products p ON p.product_id = oi.product_id
        WHERE o.order_no = :order_no AND o.deleted_flag = 0
    """)
    rows = db.execute(sql, {"order_no": order_no}).mappings().all()

    item_ids = [r["id"] for r in rows]
    product_ids = [r["product_id"] for r in rows if r.get("product_id")]
    process_map: Dict[int, str] = {}

    # 优先从已初始化的工序进度获取
    if item_ids:
        proc_sql = text("""
            SELECT pp.order_product_id, GROUP_CONCAT(pr.name ORDER BY pp.step_order SEPARATOR '-') AS process_chain
            FROM order_product_process_progress pp
            JOIN process pr ON pr.id = pp.process_id
            WHERE pp.order_product_id IN :ids
            GROUP BY pp.order_product_id
        """).bindparams(bindparam("ids", expanding=True))
        proc_rows = db.execute(proc_sql, {"ids": item_ids}).mappings().all()
        for pr in proc_rows:
            process_map[pr["order_product_id"]] = pr["process_chain"] or ""

    # 未初始化进度的明细，从产品绑定的工艺路线获取
    missing_items = [(r["id"], r["product_id"]) for r in rows if r["id"] not in process_map and r.get("product_id")]
    if missing_items:
        missing_product_ids = list(set(pid for _, pid in missing_items))
        route_sql = text("""
            SELECT ppr.product_id, GROUP_CONCAT(p.name ORDER BY rs.step_order SEPARATOR '-') AS process_chain
            FROM product_process_route ppr
            JOIN process_route_step rs ON rs.route_id = ppr.route_id
            JOIN process p ON p.id = rs.process_id
            WHERE ppr.product_id IN :pids
            GROUP BY ppr.product_id
        """).bindparams(bindparam("pids", expanding=True))
        route_rows = db.execute(route_sql, {"pids": missing_product_ids}).mappings().all()
        product_route_map = {r["product_id"]: r["process_chain"] or "" for r in route_rows}
        for item_id, product_id in missing_items:
            if product_id in product_route_map:
                process_map[item_id] = product_route_map[product_id]

    items = []
    for r in rows:
        qr_data = ""
        try:
            qr_result = get_qrcode(db, r["id"], box_size=4)
            qr_data = qr_result.get("qr_data", "")
        except Exception:
            pass

        items.append({
            "id": r["id"],
            "product_name": r["product_name"] or "",
            "model": r["model"] or "",
            "order_qty": int(r["order_qty"]) if r["order_qty"] else 0,
            "batch_no": r["batch_no"] or "",
            "created_at": str(r["created_at"]) if r["created_at"] else "",
            "qr_code": qr_data,
            "color": r["color"] or "",
            "size": r["size"] or "",
            "unit": r["unit"] or "",
            "description": r["description"] or "",
            "product_remark": r["product_remark"] or "",
            "order_product_process": process_map.get(r["id"], ""),
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
                "sub_tables": [],
                "column_defs": sample_cols,
                "rows": [sample_row],
                "col_totals": sample_totals,
                "total_cols": 3,
                "weight_totals": sample_weight,
                "weight_t_totals": sample_weight_t,
                "has_middle_punch": False,
            }
        return handler(db, order_no)

    if report_code == "process_card_print":
        order_no = params.get("order_no", "")
        if not order_no:
            return {
                "items": [{
                    "id": 0, "product_name": "", "model": "",
                    "order_qty": 0, "batch_no": "", "created_at": "",
                    "qr_code": "", "color": "", "size": "",
                    "unit": "", "description": "", "product_remark": "",
                    "order_product_process": "",
                }],
            }
        return handler(db, order_no)

    return handler(db, **params)
