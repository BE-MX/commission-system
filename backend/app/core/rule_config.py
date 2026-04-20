"""订单匹配规则配置加载与 SQL 构建"""

from pathlib import Path
from functools import lru_cache
from typing import Any

import yaml

from app.core.config import get_settings

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "order_match_rules.yaml"


@lru_cache
def load_order_match_config() -> dict[str, Any]:
    """加载并缓存 order_match_rules.yaml"""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["order_match"]


def build_batch_order_match_query(customer_ids: list[str]) -> str:
    """
    批量版订单匹配：一次查询返回多个客户的首条匹配订单。
    返回按 company_id, account_date 排序的结果，调用方取每个客户的第一条。
    """
    settings = get_settings()
    cfg = load_order_match_config()

    schema = settings.BUSINESS_DB_NAME
    table = cfg["table"]
    cid_field = cfg["customer_id_field"]
    cond = cfg["conditions"]

    id_list = ", ".join(f"'{cid}'" for cid in customer_ids)
    clauses = [f"`{cid_field}` IN ({id_list})"]

    if cond.get("custom_fields_like"):
        escaped = cond["custom_fields_like"].replace("'", "\\'")
        clauses.append(f"`custom_fields` LIKE '%{escaped}%'")
    if cond.get("account_date_min"):
        clauses.append(f"`account_date` >= '{cond['account_date_min']}'")
    if cond.get("trail_not_like"):
        clauses.append(f"(`trail` IS NULL OR `trail` NOT LIKE '%{cond['trail_not_like']}%')")

    status_values = cond.get("status_values", [])
    if status_values:
        status_parts = []
        for sv in status_values:
            val = sv["value"]
            sn = sv.get("status_name")
            if sn:
                status_parts.append(f"(`status` = '{val}' AND `status_name` = '{sn}')")
            else:
                status_parts.append(f"`status` = '{val}'")
        clauses.append(f"({' OR '.join(status_parts)})")

    dept_ids = cond.get("department_ids", [])
    if dept_ids:
        id_vals = ", ".join(str(d) for d in dept_ids)
        clauses.append(f"""`departments` REGEXP '"id":({id_vals})'""")

    where = " AND ".join(clauses)
    sql = (
        f"SELECT * FROM `{schema}`.`{table}` "
        f"WHERE {where} "
        f"ORDER BY `{cid_field}`, `account_date` ASC"
    )
    return sql


def build_order_match_query(customer_id: str) -> str:
    """
    根据配置文件拼接订单匹配的 SQL WHERE 子句。

    返回完整 SELECT 语句，用于在业务库中查找该客户的匹配订单。
    """
    settings = get_settings()
    cfg = load_order_match_config()

    schema = settings.BUSINESS_DB_NAME
    table = cfg["table"]
    cid_field = cfg["customer_id_field"]
    cond = cfg["conditions"]

    clauses = [f"`{cid_field}` = '{customer_id}'"]

    # custom_fields LIKE
    if cond.get("custom_fields_like"):
        escaped = cond["custom_fields_like"].replace("'", "\\'")
        clauses.append(f"`custom_fields` LIKE '%{escaped}%'")

    # account_date >= min
    if cond.get("account_date_min"):
        clauses.append(f"`account_date` >= '{cond['account_date_min']}'")

    # trail NOT LIKE
    if cond.get("trail_not_like"):
        clauses.append(f"(`trail` IS NULL OR `trail` NOT LIKE '%{cond['trail_not_like']}%')")

    # status / status_name 条件（OR 组合）
    status_values = cond.get("status_values", [])
    if status_values:
        status_parts = []
        for sv in status_values:
            val = sv["value"]
            sn = sv.get("status_name")
            if sn:
                status_parts.append(f"(`status` = '{val}' AND `status_name` = '{sn}')")
            else:
                status_parts.append(f"`status` = '{val}'")
        clauses.append(f"({' OR '.join(status_parts)})")

    # department_ids 白名单
    dept_ids = cond.get("department_ids", [])
    if dept_ids:
        id_list = ", ".join(str(d) for d in dept_ids)
        clauses.append(f"`departments` REGEXP '\"id\":({id_list})'")

    where = " AND ".join(clauses)
    sql = (
        f"SELECT * FROM `{schema}`.`{table}` "
        f"WHERE {where} "
        f"ORDER BY `account_date` ASC LIMIT 1"
    )
    return sql
