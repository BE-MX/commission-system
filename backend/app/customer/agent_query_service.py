"""SQL keyset pagination for mutable customer Agent result sets."""

from __future__ import annotations

from datetime import date, datetime
from typing import Callable

from sqlalchemy import and_, func, or_

from app.customer.agent_tool_contract import (
    MAX_LIST_ITEMS,
    decode_keyset_cursor,
    deny,
    encode_keyset_cursor,
    fit,
)


def _limit(value: int) -> int:
    return min(max(int(value), 1), MAX_LIST_ITEMS)


def ascending_id_page(
    query, id_column, *, user: dict, customer_id: int | None, filters: dict,
    profile_version: int | None, cursor: str | None, limit: int,
):
    if cursor:
        keyset = decode_keyset_cursor(
            cursor, user=user, customer_id=customer_id, filters=filters,
            profile_version=profile_version,
        )
        row_id = keyset.get("id")
        if type(row_id) is not int or row_id <= 0:
            deny()
        query = query.filter(id_column > row_id)
    capped = _limit(limit)
    fetched = query.order_by(id_column.asc()).limit(capped + 1).all()
    return fetched[:capped], len(fetched) > capped


def descending_pair_page(
    query, sort_column, id_column, *, sort_type: type[date] | type[datetime],
    user: dict, customer_id: int, filters: dict, profile_version: int | None,
    cursor: str | None, limit: int,
):
    sentinel = datetime(1970, 1, 1) if sort_type is datetime else date(1970, 1, 1)
    sort_expression = func.coalesce(sort_column, sentinel)
    if cursor:
        keyset = decode_keyset_cursor(
            cursor, user=user, customer_id=customer_id, filters=filters,
            profile_version=profile_version,
        )
        raw_sort, row_id = keyset.get("sort"), keyset.get("id")
        try:
            sort_value = sort_type.fromisoformat(raw_sort)
        except (TypeError, ValueError):
            deny()
        if type(row_id) is not int or row_id <= 0:
            deny()
        query = query.filter(or_(
            sort_expression < sort_value,
            and_(sort_expression == sort_value, id_column < row_id),
        ))
    capped = _limit(limit)
    fetched = query.order_by(sort_expression.desc(), id_column.desc()).limit(capped + 1).all()
    return fetched[:capped], len(fetched) > capped


def finish_keyset_page(
    value: dict, rows: list, *, max_bytes: int, has_more: bool,
    key_for_row: Callable[[object], dict], user: dict, customer_id: int | None,
    filters: dict, profile_version: int | None,
) -> dict:
    def cursor_for_count(count: int) -> str:
        if count <= 0 or count > len(rows):
            raise ValueError("OUTPUT_BUDGET_EXCEEDED")
        return encode_keyset_cursor(
            user=user, customer_id=customer_id, filters=filters,
            profile_version=profile_version, keyset=key_for_row(rows[count - 1]),
        )

    value["has_more"] = has_more
    value["cursor"] = cursor_for_count(len(rows)) if has_more else None
    return fit(value, max_bytes=max_bytes, cursor_for_count=cursor_for_count)


def id_key(row) -> dict:
    return {"id": int(row.id)}


def pair_key(sort_attribute: str) -> Callable[[object], dict]:
    def key(row) -> dict:
        value = getattr(row, sort_attribute) or date(1970, 1, 1)
        return {"sort": value.isoformat(), "id": int(row.id)}
    return key
