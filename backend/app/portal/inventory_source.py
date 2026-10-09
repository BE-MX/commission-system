"""Read exact SKU availability from an explicitly attested, read-only OKKI mirror.

No timestamp fallback and no inference of count units from product names/weights.
The deployment contract must name the stock sync column, its naive timezone and
the source count unit for each enabled product:sku pair before it can be used.
"""
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.time import beijing_now, to_beijing_naive
from app.invoice import product_service
from app.portal.inventory import InventoryObservation


logger = logging.getLogger(__name__)
_ID = re.compile(r"[1-9][0-9]{0,18}")
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?")
_MAX_QUANTITY = Decimal('999999999999999999')
_QUANTUM = Decimal('0.000001')


def _id(value):
    value = str(value)
    return value if _ID.fullmatch(value) and int(value) <= 9223372036854775807 else None


def _amount(value):
    # Floats already lost decimal precision; do not restore fictitious accuracy.
    if type(value) not in {int, str, Decimal}:
        return None
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or not Decimal(0) <= amount <= _MAX_QUANTITY:
        return None
    # Exact at the supported six-decimal stock boundary, never round up a source.
    with localcontext() as context:
        context.prec = 32
        try:
            fixed = amount.quantize(_QUANTUM)
        except InvalidOperation:
            return None
    return fixed if fixed == amount else None


def _timestamp(value, timezone):
    if isinstance(value, str):
        if not _STAMP.fullmatch(value):
            return None
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    try:
        return to_beijing_naive(value, naive_is_beijing=timezone == 'Asia/Shanghai')
    except (ValueError, OverflowError):
        return None


def load(db, items):
    settings = get_settings()
    namespace = settings.PORTAL_OKKI_NAMESPACE
    time_column = settings.PORTAL_INVENTORY_OBSERVED_COLUMN
    timezone = settings.PORTAL_INVENTORY_SOURCE_TIMEZONE
    units = settings.PORTAL_INVENTORY_UNIT_BY_SKU
    # synced_at is an observation only when the upstream importer refreshes every
    # stock row on a successful fetch. Deployment must verify that invariant.
    if not namespace or time_column != 'synced_at' or timezone not in {'Asia/Shanghai', 'UTC'} or not units:
        return {}
    pairs = {}
    for item in items:
        product_id, sku_id = _id(item.product_id), _id(item.sku_id)
        if item.source_namespace != namespace or not product_id or not sku_id:
            continue
        key = (product_id, sku_id)
        unit = units.get(':'.join(key))
        if not isinstance(unit, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,31}', unit):
            continue
        pairs.setdefault(key, []).append((item.public_id, unit))
    if not pairs:
        return {}
    schema = product_service._schema()
    if not re.fullmatch(r'[A-Za-z0-9_]+', schema):
        return {}
    try:
        columns = product_service._table_columns(db, 'okki_inventory')
        if not {'product_id', 'sku_id', 'enable_count', 'disable_flag', time_column} <= columns:
            return {}
        product_columns = product_service._table_columns(db, 'okki_products')
        sku_columns = product_service._table_columns(db, 'okki_product_skus')
        if not {'product_id', 'disable_flag'} <= product_columns or not {'product_id', 'sku_id', 'disable_flag'} <= sku_columns:
            return {}
        statement = text(f'''
            SELECT i.product_id, i.sku_id, i.enable_count, i.`{time_column}` AS observed_at
            FROM `{schema}`.okki_inventory i
            WHERE (i.product_id, i.sku_id) IN :pairs AND i.disable_flag = 0
              AND EXISTS (SELECT 1 FROM `{schema}`.okki_products p
                          WHERE p.product_id = i.product_id AND p.disable_flag = 0)
              AND EXISTS (SELECT 1 FROM `{schema}`.okki_product_skus s
                          WHERE s.product_id = i.product_id AND s.sku_id = i.sku_id AND s.disable_flag = 0)
            LIMIT 20001
        ''').bindparams(bindparam('pairs', expanding=True))
        aggregates = {}
        bad = set()
        keys = sorted(pairs)
        for offset in range(0, len(keys), 200):
            rows = db.execute(statement, {'pairs': [(int(p), int(s)) for p, s in keys[offset:offset+200]]}).mappings().all()
            now = beijing_now()
            if len(rows) > 20000:
                return {}  # Never publish a silently truncated aggregate.
            for row in rows:
                key = (_id(row['product_id']), _id(row['sku_id']))
                if key not in pairs:
                    continue
                amount = _amount(row['enable_count'])
                stamp = _timestamp(row['observed_at'], timezone)
                if amount is None or stamp is None or not 0 <= (now - stamp).total_seconds() <= settings.PORTAL_INVENTORY_MAX_AGE_SECONDS:
                    bad.add(key)
                    continue
                previous_amount, previous_stamp = aggregates.get(key, (Decimal(0), stamp))
                with localcontext() as context:
                    context.prec = 32
                    total = previous_amount + amount
                if total > _MAX_QUANTITY:
                    bad.add(key)
                    continue
                aggregates[key] = (total, min(previous_stamp, stamp))
    except SQLAlchemyError as exc:
        message = f'Portal inventory source unavailable: {type(exc).__name__}'
        logger.warning(message)
        print(message, flush=True)
        return {}
    result = {}
    for key, (amount, stamp) in aggregates.items():
        if key in bad:
            continue
        for public_id, unit in pairs[key]:
            result[public_id] = InventoryObservation(amount, unit, stamp,
                f'okki_inventory:{namespace}:{key[0]}:{key[1]}:{time_column}')
    return result
