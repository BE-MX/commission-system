"""Whitelisted list sorting before pagination, with consistent missing values."""

from functools import cmp_to_key
from numbers import Number
import re
from sqlalchemy import String, or_


def apply_list_sort(query, sort_field, sort_order, columns, *, default=(), tie_breakers=()):
    """Sort only mapped SQL expressions; never interpolate client field names.

    Missing values remain last in either direction. Callers supply a unique
    tie breaker so equal values cannot jump between pages. An absent/unknown
    field restores the caller's existing business ordering.
    """
    column = columns.get(sort_field)
    if column is None or sort_order not in ("asc", "desc"):
        return query.order_by(None).order_by(*default, *tie_breakers)
    order = column.desc() if sort_order == "desc" else column.asc()
    missing = column.is_(None)
    if isinstance(getattr(column, 'type', None), String):
        missing = or_(missing, column == '')
    return query.order_by(None).order_by(missing.asc(), order, *tie_breakers)


def apply_items_sort(items, sort_field, sort_order, fields, *, tie_breaker="id"):
    """Sort a complete, already materialized filtered result before slicing.

    Fields map to dict keys or callables for display-derived values. This is
    for queries already materializing all results, never to fetch every page.
    """
    accessor = fields.get(sort_field)
    if accessor is None or sort_order not in ("asc", "desc"):
        return list(items)

    def read(item, key):
        return key(item) if callable(key) else item.get(key)

    def compare(left, right):
        if left is None or right is None:
            return (left is None) - (right is None)
        if isinstance(left, Number) and isinstance(right, Number):
            return (left > right) - (left < right)
        if type(left) is type(right) and not isinstance(left, str):
            return (left > right) - (left < right)
        def natural(value):
            return [(1, int(part)) if part.isdigit() else (0, part.casefold())
                    for part in re.split(r"(\d+)", str(value))]
        lkey, rkey = natural(left), natural(right)
        return (lkey > rkey) - (lkey < rkey)

    def compare_items(left, right):
        lvalue, rvalue = read(left, accessor), read(right, accessor)
        if lvalue is None or rvalue is None:
            result = (lvalue is None) - (rvalue is None)
        else:
            result = compare(lvalue, rvalue) * (-1 if sort_order == "desc" else 1)
        return result or compare(read(left, tie_breaker), read(right, tie_breaker))

    return sorted(items, key=cmp_to_key(compare_items))
