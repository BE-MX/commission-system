"""OKKI 出库单只读查询 —— 运行时列内省 + 候选字段名映射。

okki_outbound_records / okki_outbound_record_items 是 OKKI 同步作业维护的只读
镜像表。2026-09-01 已用 scripts/show_okki_outbound_columns.py 对实库摸底校准：
- 单号 = serial_id，出库时间 = warehouse_invoice_time，客户 = company_name，
  制单人 = create_user_name；明细数量 = outbound_count，单位 = product_unit，
  规格 = product_model，SKU = sku_code。
- 关键：明细关联出库单走 outbound_invoice_id 桥（两表都有此列且 14125/14125 命中）；
  items.outbound_record_id 是 OKKI 侧另一个实体 id，与 records.id 完全不相交，
  绝不能拿它做 join。无 outbound_invoice_id 列的库（如单元测试种子表）才回退
  到 items.outbound_record_id = records.id 直连。

每个逻辑字段仍保留候选列名列表做兜底，取第一个实际存在的；id 列必须存在，
否则抛 OutboundTableError 并列出实际全部列名。

业务库（lsordertest）只有 SELECT 权限，全部走原生 SQL + schema 前缀
（仿 app/invoice/product_service.py 的 _table_columns/_schema 处理）。
"""

import logging
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

RECORDS_TABLE = "okki_outbound_records"
ITEMS_TABLE = "okki_outbound_record_items"

# 逻辑字段 → 候选列名（按优先级取第一个实际存在的；首选名已按 2026-09-01 实库摸底校准）
_RECORD_CANDIDATES: dict[str, list[str]] = {
    "id": ["id"],
    "invoice_id": ["outbound_invoice_id"],
    "outbound_no": ["serial_id", "outbound_no", "outbound_order_no", "record_no", "bill_no", "order_no", "no", "code"],
    "outbound_date": ["warehouse_invoice_time", "outbound_date", "outbound_time", "delivery_date", "ship_date", "created_at", "create_time", "gmt_create"],
    "customer_name": ["company_name", "customer_name", "client_name", "buyer_name"],
    "owner_name": ["create_user_name", "owner_name", "salesman_name", "user_name", "operator_name"],
}

_ITEM_CANDIDATES: dict[str, list[str]] = {
    "id": ["id"],
    "record_id": ["outbound_record_id", "record_id", "outbound_id", "order_id", "parent_id"],
    "invoice_id": ["outbound_invoice_id"],
    "product_name": ["product_name", "product_cn_name", "cn_name", "name", "product"],
    "quantity": ["outbound_count", "quantity", "qty", "outbound_quantity", "outbound_qty", "num", "amount"],
    "unit": ["product_unit", "unit", "unit_name"],
    "spec": ["product_model", "spec", "specification", "model"],
    "sku": ["sku_code", "sku", "product_no", "product_code", "item_no"],
}

# 进程内列内省缓存：{schema}.{table} → 列名集合
_columns_cache: dict[str, set[str]] = {}


class OutboundTableError(RuntimeError):
    """出库镜像表结构与候选映射不匹配（如缺 id 列），报错文案带实际列名便于校准。"""


def _schema() -> str:
    return settings.BUSINESS_DB_NAME


def _table_columns(db: Session, table_name: str) -> set[str]:
    """运行时列内省：sqlite 测试态走 PRAGMA，生产 MySQL 走 SHOW COLUMNS；进程内缓存。"""
    cache_key = f"{_schema()}.{table_name}"
    cached = _columns_cache.get(cache_key)
    if cached is not None:
        return cached
    bind = db.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    schema = _schema()
    if dialect == "sqlite":
        rows = db.execute(text(f"PRAGMA {schema}.table_info({table_name})")).mappings().all()
        columns = {str(row["name"]) for row in rows}
    else:
        rows = db.execute(text(f"SHOW COLUMNS FROM `{schema}`.`{table_name}`")).mappings().all()
        columns = {str(row["Field"]) for row in rows}
    _columns_cache[cache_key] = columns
    return columns


def _resolve_columns(db: Session, table: str, candidates: dict[str, list[str]]) -> dict[str, str | None]:
    columns = _table_columns(db, table)
    resolved = {key: next((name for name in names if name in columns), None) for key, names in candidates.items()}
    if resolved["id"] is None:
        raise OutboundTableError(
            f"业务库表 {_schema()}.{table} 缺少 id 列；实际列：{sorted(columns)}"
        )
    return resolved


def _record_columns(db: Session) -> dict[str, str | None]:
    return _resolve_columns(db, RECORDS_TABLE, _RECORD_CANDIDATES)


def _item_columns(db: Session) -> dict[str, str | None]:
    return _resolve_columns(db, ITEMS_TABLE, _ITEM_CANDIDATES)


def _link(db: Session) -> tuple[str | None, dict[str, str | None], dict[str, str | None]]:
    """明细↔单头的关联方式：优先 outbound_invoice_id 桥，回退 items.record_id = records.id。

    实库（2026-09-01 摸底）items.outbound_record_id 与 records.id 不相交，
    只有 invoice 桥能连上；单元测试种子表没有 invoice 列，走 record 直连。
    """
    rm = _record_columns(db)
    im = _item_columns(db)
    if rm.get("invoice_id") and im.get("invoice_id"):
        return ("invoice", rm, im)
    if im.get("record_id"):
        return ("record", rm, im)
    return (None, rm, im)


def _col(mapping: dict[str, str | None], key: str, alias: str) -> str:
    """生成 alias.`col` 片段；列缺失时给 NULL，保证 SQL 可执行、对应字段降级为 None。"""
    name = mapping.get(key)
    return f"{alias}.`{name}`" if name else "NULL"


def _str_or_none(value) -> str | None:
    if value is None:
        return None
    text_value = str(value)
    return text_value if text_value else None


def _num(value):
    """数量归一化：整数值给 int，其余给 float；非数值/NULL 给 None。"""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _map_record_row(row) -> dict:
    record_id = str(row["outbound_record_id"])
    outbound_no = _str_or_none(row["outbound_no"])
    return {
        "outbound_record_id": record_id,
        # 单号列缺失时回退展示 id，保证打印/检索有锚点
        "outbound_no": outbound_no or record_id,
        "outbound_date": _str_or_none(row["outbound_date"]),
        "customer_name": _str_or_none(row["customer_name"]),
        "owner_name": _str_or_none(row["owner_name"]),
        "item_count": int(row["item_count"] or 0),
        "total_qty": _num(row["total_qty"]) or 0,
    }


def _map_item_row(row) -> dict:
    return {
        "item_id": str(row["item_id"]),
        "product_name": _str_or_none(row["product_name"]),
        "spec": _str_or_none(row["spec"]),
        "sku": _str_or_none(row["sku"]),
        "qty": _num(row["qty"]),
        "unit": _str_or_none(row["unit"]),
    }


def _record_select(rm: dict[str, str | None]) -> str:
    return (
        f"r.`{rm['id']}` AS outbound_record_id, "
        f"{_col(rm, 'outbound_no', 'r')} AS outbound_no, "
        f"{_col(rm, 'outbound_date', 'r')} AS outbound_date, "
        f"{_col(rm, 'customer_name', 'r')} AS customer_name, "
        f"{_col(rm, 'owner_name', 'r')} AS owner_name"
    )


def list_outbound_records(
    db: Session,
    *,
    keyword: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """出库单分页列表：keyword 匹配单号/客户，date 按出库日期过滤（含当日）。"""
    rm = _record_columns(db)
    im = _item_columns(db)
    schema = _schema()

    params: dict[str, object] = {}
    clauses: list[str] = []
    if keyword:
        like_parts = []
        if rm["outbound_no"]:
            like_parts.append(f"r.`{rm['outbound_no']}` LIKE :kw")
        if rm["customer_name"]:
            like_parts.append(f"r.`{rm['customer_name']}` LIKE :kw")
        if like_parts:
            clauses.append("(" + " OR ".join(like_parts) + ")")
            params["kw"] = f"%{keyword}%"
    if rm["outbound_date"]:
        if date_from:
            clauses.append(f"r.`{rm['outbound_date']}` >= :date_from")
            # 绑定 ISO 字符串而非 date 对象：sqlite 无日期类型，MySQL 字符串比较同样成立
            params["date_from"] = date_from.isoformat()
        if date_to:
            # 出库日期列在实库可能是 DATETIME，右端用次日开区间包住当天
            clauses.append(f"r.`{rm['outbound_date']}` < :date_to_next")
            params["date_to_next"] = (date_to + timedelta(days=1)).isoformat()
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    # 明细统计左连：明细表缺关联列时降级为 0，不拖垮主查询
    link, rm, im = _link(db)
    stats_join = ""
    item_count_expr = "0"
    total_qty_expr = "0"
    if link is not None:
        qty_expr = f"SUM(i.`{im['quantity']}`)" if im["quantity"] else "NULL"
        if link == "invoice":
            join_key_item = im["invoice_id"]
            join_key_record = rm["invoice_id"]
        else:
            join_key_item = im["record_id"]
            join_key_record = rm["id"]
        stats_join = f"""
            LEFT JOIN (
                SELECT i.`{join_key_item}` AS link_key,
                       COUNT(*) AS item_count,
                       {qty_expr} AS total_qty
                FROM `{schema}`.`{ITEMS_TABLE}` i
                GROUP BY i.`{join_key_item}`
            ) s ON s.link_key = r.`{join_key_record}`
        """
        item_count_expr = "COALESCE(s.item_count, 0)"
        total_qty_expr = "COALESCE(s.total_qty, 0)" if im["quantity"] else "0"

    order_by = f"r.`{rm['outbound_date']}` DESC, " if rm["outbound_date"] else ""
    total = db.execute(text(f"""
        SELECT COUNT(*) FROM `{schema}`.`{RECORDS_TABLE}` r {where}
    """), params).scalar() or 0

    rows = db.execute(text(f"""
        SELECT {_record_select(rm)},
               {item_count_expr} AS item_count,
               {total_qty_expr} AS total_qty
        FROM `{schema}`.`{RECORDS_TABLE}` r
        {stats_join}
        {where}
        ORDER BY {order_by} r.`{rm['id']}` DESC
        LIMIT :limit OFFSET :offset
    """), {**params, "limit": page_size, "offset": (page - 1) * page_size}).mappings().all()
    return [_map_record_row(row) for row in rows], int(total)


def get_outbound_record(db: Session, record_id: str) -> dict | None:
    """单条出库单头；不存在返回 None。"""
    rm = _record_columns(db)
    schema = _schema()
    row = db.execute(text(f"""
        SELECT {_record_select(rm)}, 0 AS item_count, 0 AS total_qty
        FROM `{schema}`.`{RECORDS_TABLE}` r
        WHERE r.`{rm['id']}` = :rid
        LIMIT 1
    """), {"rid": record_id}).mappings().first()
    if row is None:
        return None
    result = _map_record_row(row)
    result.pop("item_count", None)
    result.pop("total_qty", None)
    return result


def list_outbound_items(db: Session, record_id: str) -> list[dict]:
    """出库明细（产品名称、数量、单位、规格、SKU）；两库无任何关联列时返回空。"""
    link, rm, im = _link(db)
    if link is None:
        logger.warning("%s 缺少出库单关联列，明细查询降级为空", ITEMS_TABLE)
        return []
    schema = _schema()
    if link == "invoice":
        # outbound_invoice_id 桥：先按 records.id 取出库单发票号，再反查明细
        where = (
            f"i.`{im['invoice_id']}` = ("
            f"SELECT r.`{rm['invoice_id']}` FROM `{schema}`.`{RECORDS_TABLE}` r"
            f" WHERE r.`{rm['id']}` = :rid LIMIT 1)"
        )
    else:
        where = f"i.`{im['record_id']}` = :rid"
    rows = db.execute(text(f"""
        SELECT i.`{im['id']}` AS item_id,
               {_col(im, 'product_name', 'i')} AS product_name,
               {_col(im, 'spec', 'i')} AS spec,
               {_col(im, 'sku', 'i')} AS sku,
               {_col(im, 'quantity', 'i')} AS qty,
               {_col(im, 'unit', 'i')} AS unit
        FROM `{schema}`.`{ITEMS_TABLE}` i
        WHERE {where}
        ORDER BY i.`{im['id']}`
    """), {"rid": record_id}).mappings().all()
    return [_map_item_row(row) for row in rows]
