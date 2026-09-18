"""Private durable receipt index; every use is verified against live OKKI changes."""
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.core.config import get_settings
from app.core.time import beijing_now
from app.invoice.okki_client import OkkiApiError
from app.receipt import remote

logger = logging.getLogger(__name__)
CACHE_ROOT = Path(__file__).resolve().parents[3] / "backend/data/receipt-index"
FIELDS = ("cash_collection_id", "cash_collection_no", "order_id", "amount", "currency",
          "collect_status", "collection_date", "update_time")
_lock = RLock()


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


def _load(path, source):
    if not path.exists():
        return None
    try:
        envelope = json.loads(path.read_bytes())
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
    except (ValueError, TypeError, KeyError, OSError):
        _warn("Invalid private cache; rebuilding from verified remote data")
        return None


def _save(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    envelope = {"payload": payload, "sha256": hashlib.sha256(_encoded(payload)).hexdigest()}
    try:
        # Unique temporary file and a whole-snapshot atomic replace work across workers.
        # An older complete snapshot winning a race only causes repeated delta reads.
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(_encoded(envelope))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


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


def _refresh(db, payload):
    start = (datetime.strptime(payload["watermark"], "%Y-%m-%d %H:%M:%S") - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    end = beijing_now().strftime("%Y-%m-%d %H:%M:%S")
    changes, count = _page(db, start, end)
    if count > 100:
        raise ValueError("小满回款增量超出单页，需完整重建")
    confirmed, confirmed_count = _page(db, start, end)
    canonical = lambda rows: _encoded(sorted(rows, key=lambda row: str(row["cash_collection_id"])))
    if count != confirmed_count or canonical(changes) != canonical(confirmed):
        raise ValueError("小满回款增量发生变化")
    merged = {str(row["cash_collection_id"]): row for row in payload["rows"]}
    for row in confirmed:
        merged[str(row["cash_collection_id"])] = row
    latest, total = _page(db)
    _validate(latest, "1970-01-01 00:00:00", end)
    if total != len(merged):
        # A deletion (including delete+add with unchanged total) invalidates the baseline.
        # Never guess which missing receipt can release an order's balance.
        raise ValueError("小满回款总数不匹配，需完整重建")
    return list(merged.values()), end


def verified_rows(db):
    """Return only a newly verified snapshot; never return stale data on errors."""
    with _lock:
        source = _source()
        path = CACHE_ROOT / (source + ".json")
        payload = _load(path, source)
        if payload is not None:
            try:
                rows, watermark = _refresh(db, payload)
            except OkkiApiError:
                raise  # Auth/network failure is not permission to use old balances.
            except ValueError:
                _warn("Incremental verification incomplete; rebuilding full receipt index")
                payload = None
        if payload is None:
            rows, watermark = remote._window_order_receipts(db, None, include_watermark=True)
        rows = [{key: row.get(key) for key in FIELDS} for row in rows]
        _validate(rows, "1970-01-01 00:00:00", watermark)
        _save(path, {"version": 1, "source": source, "watermark": watermark, "rows": rows})
        return rows
