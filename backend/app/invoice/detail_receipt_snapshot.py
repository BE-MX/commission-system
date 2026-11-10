"""Readonly display snapshots; never used to authorize a payment or send."""
from collections import defaultdict
from datetime import datetime, timedelta
from threading import Lock

from sqlalchemy import select

from app.core.time import beijing_now
from app.receipt import receipt_index, remote
from app.receipt.models import ReceiptIndexState


_page_cache = None
_page_cache_lock = Lock()


def _read(db, source):
    payload = receipt_index._load(db, source)
    if payload is None:
        raise ValueError("回款快照尚未就绪，已显示方舟回款单；可刷新实时核验")
    stamp = datetime.strptime(payload["watermark"], "%Y-%m-%d %H:%M:%S")
    _require_fresh(stamp)
    return payload, stamp


def _require_fresh(stamp):
    if beijing_now() - stamp > timedelta(minutes=2):
        raise ValueError("回款快照已超过2分钟，已显示方舟回款单；请刷新实时核验")


def load(db):
    return _read(db, receipt_index._source())


def page_orders(db, order_ids):
    """Read only the checksum per page; validate and index once per publication."""
    global _page_cache
    source, bind = receipt_index._source(), db.get_bind()
    digest = db.scalar(select(ReceiptIndexState.snapshot["sha256"].as_string())
                       .where(ReceiptIndexState.source == source))
    if not digest:
        raise ValueError("回款快照尚未就绪")
    with _page_cache_lock:
        key = (bind, source, digest)
        if _page_cache is None or _page_cache[0] != key:
            # Hold the ORM instance so _read validates these same bytes, even
            # if a new snapshot is published between the two SQL statements.
            state = db.get(ReceiptIndexState, source, populate_existing=True)
            payload, stamp = _read(db, source)
            rows_by_order = defaultdict(list)
            for row in payload["rows"]:
                rows_by_order[str(row["order_id"])].append(row)
            _page_cache = ((bind, source, state.snapshot["sha256"]), stamp, rows_by_order)
        _, stamp, rows_by_order = _page_cache
    _require_fresh(stamp)
    return {order_id: rows_by_order[order_id] for order_id in order_ids if order_id in rows_by_order}


def order(payload, invoice):
    return {"rows": [row for row in payload["rows"] if str(row["order_id"]) == str(invoice.xiaoman_order_id)],
            "invoice_binding": remote.invoice_binding(invoice)}


def freight(payload, target):
    if target.remote_status != "bound":
        raise ValueError("独立运费目标尚未核验，请刷新实时核验")
    return {"rows": [row for row in payload["rows"] if str(row["order_id"]) == str(target.remote_order_id)],
            "target_binding": [target.id, target.remote_order_id, str(target.amount),
                               target.currency, target.customer_id, target.version]}
