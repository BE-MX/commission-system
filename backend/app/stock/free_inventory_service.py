"""Snapshot free stock for the overview; no provider calls on list requests."""
import logging
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from sqlalchemy import bindparam, text

from app.core.config import get_settings
from app.invoice.stock_reservations import WAREHOUSE_ID, claims

logger = logging.getLogger(__name__)


def get_free_inventory(db, product_ids: set[int]) -> tuple[dict, dict]:
    """Use enabled-warehouse mirrors and only untransferred outbound demand.

    Native handoff requires a strictly newer default-warehouse mirror. Missing
    SKU/quantity/time or unresolved native evidence leaves the product unknown.
    """
    if not product_ids:
        return {}, {}
    schema = get_settings().BUSINESS_DB_NAME
    rows = db.execute(text(f"""
        SELECT sku_keys.product_id, sku_keys.sku_id, i.warehouse_id,
               i.enable_count, i.synced_at
        FROM (
            SELECT product_id, sku_id FROM `{schema}`.okki_product_skus
            WHERE product_id IN :product_ids
            UNION
            SELECT product_id, sku_id FROM `{schema}`.okki_inventory
            WHERE product_id IN :product_ids AND disable_flag = 0
        ) AS sku_keys
        LEFT JOIN `{schema}`.okki_inventory i
          ON i.product_id = sku_keys.product_id AND i.sku_id = sku_keys.sku_id
          AND i.disable_flag = 0
    """).bindparams(bindparam('product_ids', expanding=True)),
        {'product_ids': sorted(product_ids)}).mappings().all()
    balances, held = defaultdict(Decimal), defaultdict(Decimal)
    default_keys, keys = set(), defaultdict(set)
    default_times, sync_times = {}, {}
    unknown = set()
    for row in rows:
        product = int(row['product_id'])
        if row['sku_id'] is None or row['warehouse_id'] is None or row['enable_count'] is None or not row['synced_at']:
            unknown.add(product)
            continue
        key = (product, int(row['sku_id']))
        amount = Decimal(str(row['enable_count']))
        if not amount.is_finite() or amount < 0:
            unknown.add(product)
            continue
        at = row['synced_at']
        if not isinstance(at, datetime):
            at = datetime.fromisoformat(str(at))
        keys[product].add(key)
        warehouse_key = (*key, str(row['warehouse_id']))
        balances[warehouse_key] += amount
        sync_times[product] = min(sync_times.get(product, at), at)
        if str(row['warehouse_id']) == WAREHOUSE_ID:
            default_keys.add(key)
            default_times[key] = min(default_times.get(key, at), at)
    try:
        reservations = claims(db)
    except (ValueError, ArithmeticError, TypeError, KeyError) as error:
        logger.warning('Overview stock reservation unavailable (%s)', type(error).__name__)
        print('[stock-overview] reservation evidence unavailable', flush=True)
        reservations = []
        unknown.update(product_ids)
    for claim in reservations:
        for key, amount in claim.amounts.items():
            product = key[0]
            if product not in product_ids:
                continue
            keys[product].add(key)
            if claim.status in ('native_unknown', 'running', 'uncertain') or key not in default_keys:
                unknown.add(product)
            if claim.status in ('done', 'native_partial') and (
                    not claim.processed_at or default_times.get(key, datetime.min) <= claim.processed_at):
                unknown.add(product)
            if claim.status != 'done':
                held[key] += amount
    totals = defaultdict(Decimal)
    for (product, sku, warehouse), amount in balances.items():
        reserved = held[(product, sku)] if warehouse == WAREHOUSE_ID else Decimal(0)
        totals[product] += max(Decimal(0), amount - reserved)
    result = {
        p: None if p in unknown or not keys[p] or not keys[p].issubset(default_keys)
        else float(totals[p]) for p in product_ids
    }
    return result, {p: sync_times[p].isoformat() if p in sync_times else None for p in product_ids}
