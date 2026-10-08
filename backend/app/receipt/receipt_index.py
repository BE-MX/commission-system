"""Shared complete index. Only the leased background job publishes snapshots."""
import hashlib
import json
import logging
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.time import beijing_now
from app.invoice.okki_client import OkkiApiError
from app.receipt import remote
from app.receipt.models import ReceiptIndexState

logger = logging.getLogger(__name__)
FIELDS = ("cash_collection_id", "cash_collection_no", "order_id", "amount", "currency",
          "collect_status", "collection_date", "update_time")


class IndexNotReady(ValueError):
    """Preparation can be retried; no receipt POST has been attempted."""


def _encoded(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _source():
    settings = get_settings()
    return hashlib.sha256(_encoded([settings.OKKI_API_BASE.rstrip("/"), settings.OKKI_CLIENT_ID])).hexdigest()


def _warn(message):
    logger.warning(message)
    print("[receipt-index] " + message, flush=True)


def _validate(rows, start, end):
    if not isinstance(rows, list):
        raise ValueError("回款索引数据不完整")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or any(key not in row for key in FIELDS):
            raise ValueError("回款索引字段不完整")
        identity, stamp = str(row["cash_collection_id"] or ""), row["update_time"]
        if not identity or identity in seen or row["order_id"] is None:
            raise ValueError("回款索引ID重复或缺失")
        if not isinstance(stamp, str) or len(stamp) != 19:
            raise ValueError("回款索引时间无效")
        datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
        if not start <= stamp <= end:
            raise ValueError("回款索引核验范围外有新变动，请重试")
        seen.add(identity)


def _load(db, source):
    state = db.get(ReceiptIndexState, source)
    if not state or not state.snapshot:
        return None
    try:
        envelope = state.snapshot
        payload = envelope["payload"]
        if envelope["sha256"] != hashlib.sha256(_encoded(payload)).hexdigest():
            raise ValueError("checksum")
        if payload["version"] != 1 or payload["source"] != source:
            raise ValueError("source/version")
        watermark = payload["watermark"]
        datetime.strptime(watermark, "%Y-%m-%d %H:%M:%S")
        if watermark > beijing_now().strftime("%Y-%m-%d %H:%M:%S"):
            raise ValueError("future watermark")
        _validate(payload["rows"], "1970-01-01 00:00:00", watermark)
        return payload
    except (ValueError, TypeError, KeyError):
        _warn("Invalid shared index; background rebuild required")
        return None


def _page(db, start=None, end=None):
    params = {"start_index": 1, "count": 100, "removed": "0"}
    if start is not None:
        params.update(start_time=start, end_time=end)
    data = remote.read(db, "/v1/invoices/receipt/list", params)
    rows, total = data.get("list"), data.get("totalItem")
    if not isinstance(rows, list) or not str(total).isdigit() or len(rows) != min(100, int(total)):
        raise ValueError("小满回款增量不完整")
    _validate(rows, start or "1970-01-01 00:00:00", end or beijing_now().strftime("%Y-%m-%d %H:%M:%S"))
    return rows, int(total)


def _changes(db, start, end, *, windows=False, heartbeat=None, max_calls=128):
    """Split overflowing time ranges; double-read every complete leaf window."""
    pending, found, calls = [(start, end)], [], 0
    while pending:
        if calls >= max_calls:
            raise ValueError("回款增量窗口过多，需完整重建")
        lower, upper = pending.pop()
        if heartbeat:
            heartbeat()
        rows, count = _page(db, lower, upper)
        calls += 1
        if count > 100:
            if not windows or lower == upper:
                raise ValueError("回款增量超出完整窗口，等待后台刷新")
            a, b = (datetime.strptime(s, "%Y-%m-%d %H:%M:%S") for s in (lower, upper))
            middle = a + timedelta(seconds=int((b - a).total_seconds()) // 2)
            pending.extend([(lower, middle.strftime("%Y-%m-%d %H:%M:%S")),
                            ((middle + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S"), upper)])
            continue
        if calls >= max_calls:
            raise ValueError("回款增量核验预算已用尽，等待后台刷新")
        confirmed, confirmed_count = _page(db, lower, upper)
        calls += 1
        canonical = lambda values: _encoded(sorted(values, key=lambda r: str(r["cash_collection_id"])))
        if count != confirmed_count or canonical(rows) != canonical(confirmed):
            raise ValueError("小满回款增量发生变化")
        found.extend(confirmed)
    _validate(found, start, end)
    return found


def _refresh(db, payload, *, windows=False, heartbeat=None, max_calls=128):
    start = (datetime.strptime(payload["watermark"], "%Y-%m-%d %H:%M:%S") - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    end = beijing_now().strftime("%Y-%m-%d %H:%M:%S")
    changes = _changes(db, start, end, windows=windows, heartbeat=heartbeat, max_calls=max_calls)
    merged = {str(row["cash_collection_id"]): row for row in payload["rows"]}
    for row in changes:
        merged[str(row["cash_collection_id"])] = row
    latest, total = _page(db)
    _validate(latest, "1970-01-01 00:00:00", end)
    if total != len(merged):
        raise ValueError("小满回款总数不匹配，需后台完整重建")
    if windows:
        confirmed = _changes(db, start, end, windows=True, heartbeat=heartbeat, max_calls=max_calls)
        canonical = lambda values: _encoded(sorted(values, key=lambda r: str(r["cash_collection_id"])))
        if canonical(changes) != canonical(confirmed):
            raise ValueError("小满回款增量扫描期间变化")
        latest, total = _page(db)
        _validate(latest, "1970-01-01 00:00:00", end)
        if total != len(merged):
            raise ValueError("小满回款总数变化")
    return list(merged.values()), end


def verified_rows(db):
    """Never rebuild in a caller or use an unverified balance after an error."""
    payload = _load(db, _source())
    if payload is None:
        raise IndexNotReady("回款索引尚未就绪，后台正在重建，请稍后重试")
    try:
        rows, _ = _refresh(db, payload, windows=True, max_calls=32)
        return [{key: row[key] for key in FIELDS} for row in rows]
    except OkkiApiError:
        raise
    except ValueError as exc:
        _warn("Live verification incomplete; waiting for background index refresh")
        raise IndexNotReady("回款索引实时核验未完成，等待后台刷新；尚未发送回款") from exc


def refresh_background(db):
    """One writer across instances; token fences renewal and publication."""
    source, token = _source(), uuid4().hex
    if not db.get(ReceiptIndexState, source):
        try:
            with db.begin_nested():
                db.add(ReceiptIndexState(source=source))
                db.flush()
        except IntegrityError:
            _warn("Another index worker initialized this tenant")
    count = db.execute(update(ReceiptIndexState).where(ReceiptIndexState.source == source,
        or_(ReceiptIndexState.lease_until.is_(None), ReceiptIndexState.lease_until < beijing_now())).values(
            lease_token=token, lease_until=beijing_now() + timedelta(minutes=10))).rowcount
    db.commit()
    if not count:
        return False
    def heartbeat():
        count = db.execute(update(ReceiptIndexState).where(ReceiptIndexState.source == source,
            ReceiptIndexState.lease_token == token, ReceiptIndexState.lease_until > beijing_now()).values(
                lease_until=beijing_now() + timedelta(minutes=10))).rowcount
        db.commit()
        if not count:
            raise RuntimeError("Receipt index refresh lease lost")
    try:
        payload = _load(db, source)
        if payload is not None:
            try:
                rows, watermark = _refresh(db, payload, windows=True, heartbeat=heartbeat)
            except ValueError:
                _warn("Background incremental index incomplete; rebuilding")
                payload = None
        if payload is None:
            rows, watermark = remote._window_order_receipts(db, None, include_watermark=True, heartbeat=heartbeat)
        rows = [{key: row.get(key) for key in FIELDS} for row in rows]
        _validate(rows, "1970-01-01 00:00:00", watermark)
        payload = {"version": 1, "source": source, "watermark": watermark, "rows": rows}
        count = db.execute(update(ReceiptIndexState).where(ReceiptIndexState.source == source,
            ReceiptIndexState.lease_token == token, ReceiptIndexState.lease_until > beijing_now()).values(
                snapshot={"payload": payload, "sha256": hashlib.sha256(_encoded(payload)).hexdigest()},
                updated_at=beijing_now(), lease_until=None, lease_token=None)).rowcount
        if not count:
            raise RuntimeError("Receipt index publication lease lost")
        db.commit()
        return True
    finally:
        db.rollback()
        db.execute(update(ReceiptIndexState).where(ReceiptIndexState.source == source,
            ReceiptIndexState.lease_token == token).values(lease_until=None, lease_token=None))
        db.commit()
