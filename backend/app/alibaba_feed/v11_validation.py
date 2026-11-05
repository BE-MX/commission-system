"""Explicit v1.1 adapter; collector claims never grant automation capability."""
import copy
from datetime import timedelta

from .canonical import canonical_bytes
from .validation import keys, parse_envelope, record_quality, require, text, timestamp

SCHEMA = "ark_alibaba_feed_v1.1"
RECORD_EXT = {"buyer_id", "conversation_id", "assignee_external_user_id", "observed_at",
              "snapshot_revision", "conversation_revision", "last_activity_at", "coverage"}
MESSAGE_EXT = {"message_id", "source_order", "actor_type", "sender_external_user_id", "message_revision", "deleted_at"}


def revision(value, *, optional=False):
    return (optional and value is None) or (type(value) is int and 0 < value < 2**63)


def identity(value):
    return value is None or text(value, 128)


def bounded_time(value, now, path):
    try:
        require(timestamp(value) <= now + timedelta(minutes=5), path)
    except (ValueError, TypeError, OverflowError):
        require(False, path)


def validate(data, key, now, limits):
    keys(data, "schema run stats by_assignee records source_account_uid", "$")
    require(text(data.get("source_account_uid"), 64), "source_account_uid")
    require(isinstance(data.get("run"), dict), "run")
    run = data["run"]
    for field in ("collector_id", "collector_version"):
        require(text(run.get(field), 100), "run." + field)
    require(revision(run.get("collection_generation"), optional=True), "run.collection_generation")
    coverage = run.get("coverage")
    keys(coverage, "selection activity_window_start activity_window_end all_pages_read activity_scan_complete", "run.coverage")
    selection = coverage.get("selection")
    require(selection in ("created_window", "activity_window"), "run.coverage.selection")
    for field in ("all_pages_read", "activity_scan_complete"):
        require(type(coverage.get(field)) is bool, "run.coverage." + field)
    require(isinstance(run.get("window"), dict), "run.window")
    window = run["window"]
    basis = "inquiry_created_at" if selection == "created_window" else "conversation_last_activity_at"
    require(window.get("basis") == basis, "run.window.basis", "WINDOW_INVALID")
    for side in ("start", "end"):
        value = coverage.get("activity_window_" + side)
        if selection == "activity_window":
            require(value == window.get(side), "run.coverage.activity_window_" + side, "WINDOW_INVALID")
        elif value is not None:
            bounded_time(value, now, "run.coverage.activity_window_" + side)
    require(isinstance(data.get("records"), list), "records")
    for index, record in enumerate(data["records"]):
        path = f"records[{index}]"
        require(isinstance(record, dict), path)
        for field in ("buyer_id", "conversation_id", "assignee_external_user_id"):
            require(identity(record.get(field)), path + "." + field)
        require(revision(record.get("snapshot_revision")), path + ".snapshot_revision")
        require(revision(record.get("conversation_revision"), optional=record.get("conversation_id") is None), path + ".conversation_revision")
        bounded_time(record.get("observed_at"), now, path + ".observed_at")
        if record.get("last_activity_at") is not None:
            bounded_time(record["last_activity_at"], now, path + ".last_activity_at")
        cv = record.get("coverage")
        keys(cv, "history_complete latest_complete has_more covered_from covered_through edits_observable deletions_observable", path + ".coverage")
        for field in ("history_complete", "latest_complete", "has_more", "edits_observable", "deletions_observable"):
            require(type(cv.get(field)) is bool, path + ".coverage." + field)
        for field in ("covered_from", "covered_through"):
            if cv.get(field) is not None:
                bounded_time(cv[field], now, path + ".coverage." + field)
        if cv.get("covered_from") is not None and cv.get("covered_through") is not None:
            require(timestamp(cv["covered_from"]) <= timestamp(cv["covered_through"]), path + ".coverage")
        require(isinstance(record.get("messages"), list), path + ".messages")
        for message in record["messages"]:
            require(isinstance(message, dict), path + ".messages")
            require(identity(message.get("message_id")), path + ".messages.message_id")
            require(revision(message.get("source_order"), optional=True), path + ".messages.source_order")
            require(revision(message.get("message_revision")), path + ".messages.message_revision")
            require(message.get("actor_type") in ("human", "bot", "system", "unknown"), path + ".messages.actor_type")
            require(identity(message.get("sender_external_user_id")), path + ".messages.sender_external_user_id")
            if message.get("deleted_at") is not None:
                bounded_time(message["deleted_at"], now, path + ".messages.deleted_at")
    # The established v1 validator owns all unchanged envelope/record fields.
    # Removing only the explicitly registered extensions still rejects unknown keys.
    compatible = copy.deepcopy(data)
    compatible["schema"] = "ark_alibaba_feed_v1"
    compatible.pop("source_account_uid")
    for field in ("collector_id", "collector_version", "collection_generation", "coverage"):
        compatible["run"].pop(field, None)
    compatible["run"]["window"]["basis"] = "inquiry_created_at"
    for record in compatible["records"]:
        for field in RECORD_EXT:
            record.pop(field, None)
        for message in record["messages"]:
            for field in MESSAGE_EXT:
                message.pop(field, None)
    parse_envelope(canonical_bytes(compatible), key, now, limits)
    return data


def quality(record, window, selection, max_message_bytes):
    checked = dict(record)
    if selection == "activity_window":
        if record.get("last_activity_at") is None:
            # Validate remaining times/messages without pretending created_at is activity.
            _, issues = record_quality(checked, window, max_message_bytes)
            return "uncertain", sorted((set(issues) - {"WINDOW_OUTSIDE"}) | {"ACTIVITY_TIME_UNKNOWN"})
        checked.update(created_at=record["last_activity_at"], created_at_precision="minute")
    return record_quality(checked, window, max_message_bytes)
