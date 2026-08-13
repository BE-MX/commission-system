"""Idempotently add the OKKI order indexes used by order intelligence.

The business database is an external OKKI projection, so its indexes are managed
with an explicit online-DDL script instead of the commission database Alembic chain.
"""

from __future__ import annotations

import re

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.core.config import get_settings
from app.core.database import engine


INDEX_NAME = "idx_order_intel_user_account_date"
INDEX_COLUMNS = ("user_id", "account_date")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")


def _business_schema() -> str:
    schema = get_settings().BUSINESS_DB_NAME
    if not _SAFE_IDENTIFIER.fullmatch(schema):
        raise ValueError("BUSINESS_DB_NAME 只能包含字母、数字和下划线")
    return schema


def apply_indexes(db_engine: Engine = engine) -> list[str]:
    """Create missing indexes with online DDL and return action messages."""

    schema = _business_schema()
    actions: list[str] = []
    with db_engine.begin() as connection:
        existing = inspect(connection).get_indexes("okki_orders", schema=schema)
        by_name = {item["name"]: tuple(item.get("column_names") or ()) for item in existing}

        if INDEX_NAME in by_name:
            if by_name[INDEX_NAME] != INDEX_COLUMNS:
                raise RuntimeError(
                    f"{schema}.okki_orders.{INDEX_NAME} 已存在但列定义不一致: "
                    f"{by_name[INDEX_NAME]}"
                )
            return [f"SKIP {schema}.okki_orders.{INDEX_NAME} already exists"]

        if INDEX_COLUMNS in by_name.values():
            existing_name = next(name for name, columns in by_name.items() if columns == INDEX_COLUMNS)
            return [
                f"SKIP {schema}.okki_orders.{existing_name} already covers "
                f"{','.join(INDEX_COLUMNS)}"
            ]

        ddl = (
            f"ALTER TABLE `{schema}`.`okki_orders` "
            f"ADD INDEX `{INDEX_NAME}` (`user_id`, `account_date`), "
            "ALGORITHM=INPLACE, LOCK=NONE"
        )
        connection.execute(text(ddl))
        actions.append(f"ADD {schema}.okki_orders.{INDEX_NAME}")
    return actions


if __name__ == "__main__":
    for action in apply_indexes():
        print(action)
