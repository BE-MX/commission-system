"""Versioned v1 envelope checks and local record quality classification."""
import re
from datetime import datetime, timedelta, timezone

from app.core.time import to_beijing_naive
from .canonical import parse_json
from .errors import FeedError

BEIJING = timezone(timedelta(hours=8))


def limit(config, name, default):
    return getattr(config, "ALIBABA_FEED_" + name, default)


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("offset required")
    return to_beijing_naive(parsed)


def local_minute(value):
    return datetime.strptime(value, "%Y-%m-%d %H:%M")


def require(condition, path, code="SCHEMA_INVALID"):
    if not condition:
        raise FeedError(422, code, path)


def keys(value, allowed, path):
    require(isinstance(value, dict), path)
    require(not (set(value) - set(allowed.split())), path)


def text(value, maximum=512):
    return isinstance(value, str) and 0 < len(value) <= maximum


def parse_envelope(raw, idempotency_key, now, limits=None):
    if len(raw) > limit(limits, "MAX_BODY_BYTES", 10 * 1024 * 1024):
        raise FeedError(413, "PAYLOAD_TOO_LARGE")
    if not idempotency_key:
        raise FeedError(400, "IDEMPOTENCY_KEY_REQUIRED")
    data = parse_json(raw)
    if isinstance(data, dict) and data.get("schema") == "ark_alibaba_feed_v1.1":
        from .v11_validation import validate
        return validate(data, idempotency_key, now, limits)
    keys(data, "schema run stats by_assignee records", "$")
    require(data.get("schema") == "ark_alibaba_feed_v1", "schema", "SCHEMA_UNSUPPORTED")
    run = data.get("run")
    keys(run, "run_id source delivery status error window scraped_at reply_status_snapshot_at time_fields_basis validation warnings", "run")
    require(isinstance(run.get("run_id"), str) and re.fullmatch(r"[A-Za-z0-9_-]{1,96}", run["run_id"]), "run.run_id")
    require(run["run_id"] == idempotency_key, "run.run_id", "HEADER_BODY_KEY_MISMATCH")
    require(run.get("status") in ("ok", "partial", "failed"), "run.status")
    require(text(run.get("source")) and text(run.get("delivery")), "run")
    require(run.get("error") is None or text(run["error"], 2048), "run.error")
    require(run["status"] != "failed" or text(run.get("error"), 2048), "run.error")
    window = run.get("window")
    keys(window, "start end timezone interval basis", "run.window")
    try:
        start, end = timestamp(window["start"]), timestamp(window["end"])
        require(all(datetime.fromisoformat(window[k]).utcoffset() == timedelta(hours=8) for k in ("start", "end")), "run.window", "WINDOW_INVALID")
        require(end > start and window.get("timezone") == "Asia/Shanghai" and window.get("interval") == "[start,end)" and window.get("basis") == "inquiry_created_at", "run.window", "WINDOW_INVALID")
        for field in ("scraped_at", "reply_status_snapshot_at"):
            require(timestamp(run[field]) <= now + timedelta(minutes=5), "run." + field)
    except (ValueError, TypeError, KeyError, OverflowError):
        raise FeedError(422, "WINDOW_INVALID", "run") from None
    records = data.get("records")
    require(isinstance(records, list), "records")
    if len(records) > limit(limits, "MAX_RECORDS", 1000):
        raise FeedError(413, "PAYLOAD_TOO_LARGE")
    stats = data.get("stats")
    keys(stats, "inquiry_records inquiry_buyers tm_raw tm_buyers_dedup buyers_total records_total", "stats")
    require(all(type(value) is int and value >= 0 for value in stats.values()), "stats")
    groups = data.get("by_assignee")
    require(isinstance(groups, list), "by_assignee")
    for group in groups:
        keys(group, "assignee_name note counts inquiry_ids", "by_assignee")
        require(group.get("assignee_name") is None or isinstance(group["assignee_name"], str), "by_assignee.assignee_name")
        keys(group.get("counts"), "total replied pending unreplied unknown", "by_assignee.counts")
        require(all(type(v) is int and v >= 0 for v in group["counts"].values()), "by_assignee.counts")
        require(isinstance(group.get("inquiry_ids"), list) and all(text(v, 128) for v in group["inquiry_ids"]), "by_assignee.inquiry_ids")
    total_messages = 0
    for index, record in enumerate(records):
        path = f"records[{index}]"
        keys(record, "inquiry_id type type_label buyer assignee_name product_or_source created_at created_at_precision created_at_raw first_reply_at last_updated_at reply_status detail_scraped scrape_status messages trust", path)
        require(text(record.get("inquiry_id"), 128), path + ".inquiry_id")
        require(record.get("type") in ("inquiry", "tm"), path + ".type")
        require(record.get("reply_status") in ("replied", "pending", "unreplied", "unknown"), path + ".reply_status")
        require(record.get("created_at_precision") in ("day", "minute"), path + ".created_at_precision")
        require(record.get("trust") == "untrusted_external", path + ".trust")
        require(type(record.get("detail_scraped")) is bool and text(record.get("scrape_status"), 64), path + ".detail_scraped")
        keys(record.get("buyer"), "name country level level_note", path + ".buyer")
        require(all(v is None or isinstance(v, str) for v in record["buyer"].values()), path + ".buyer")
        require(record.get("assignee_name") is None or isinstance(record["assignee_name"], str), path + ".assignee_name")
        messages = record.get("messages")
        require(isinstance(messages, list), path + ".messages")
        if len(messages) > limit(limits, "MAX_MESSAGES_PER_RECORD", 5000):
            raise FeedError(413, "PAYLOAD_TOO_LARGE", path + ".messages")
        total_messages += len(messages)
        for message in messages:
            keys(message, "ref dir at text", path + ".messages")
            require(message.get("dir") in ("buyer", "seller", "bot"), path + ".messages.dir")
            require(isinstance(message.get("text"), str), path + ".messages.text")
    if total_messages > limit(limits, "MAX_MESSAGES", 50000):
        raise FeedError(413, "PAYLOAD_TOO_LARGE")
    return data


def record_quality(record, window, max_message_bytes=65536):
    issues = []
    result = "uncertain"
    try:
        start, end = timestamp(window["start"]), timestamp(window["end"])
        if record["created_at_precision"] == "day":
            created = datetime.strptime(record["created_at"], "%Y-%m-%d")
            until = created + timedelta(days=1)
            result = "in_window" if start <= created and until <= end else "out_of_window" if until <= start or created >= end else "uncertain"
        else:
            created = timestamp(record["created_at"])
            result = "in_window" if start <= created < end else "out_of_window"
        for field in ("first_reply_at", "last_updated_at"):
            if record.get(field) is not None:
                local_minute(record[field])
        refs = set()
        for message in record["messages"]:
            local_minute(message["at"])
            ref = message.get("ref")
            if not text(ref, 128) or ref in refs:
                issues.append("MESSAGE_REF_INVALID")
            refs.add(ref)
            if len(message["text"].encode("utf-8")) > max_message_bytes:
                issues.append("MESSAGE_TOO_LARGE")
    except (ValueError, KeyError, TypeError, OverflowError):
        issues.append("RECORD_TIME_INVALID")
    if result == "out_of_window":
        issues.append("WINDOW_OUTSIDE")
    if result == "uncertain":
        issues.append("WINDOW_PRECISION_INSUFFICIENT")
    if not record["detail_scraped"] or record["scrape_status"] != "success":
        issues.append("DETAIL_INCOMPLETE")
    return result, sorted(set(issues))
