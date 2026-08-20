#!/usr/bin/env python3
"""Sync curated claude-mem observations to Mem0 without writing the local DB."""

from __future__ import print_function

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request

from mem0_client import (
    SEARCH_THRESHOLD,
    SEARCH_TOP_K,
    Mem0Client,
    RetryableSyncError,
    SyncError,
    wait_for_event,
)
from memory_policy import classify, memory_text, normalize_project, source_key

BACKFILL_CONFIRMATION = "BACKFILL_HISTORY"


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def expand_path(value):
    return os.path.abspath(os.path.expanduser(value))


def redact(value):
    text = str(value)
    text = re.sub(r"\b(?:m0|sk|xox[baprs])-[A-Za-z0-9_\-]{8,}\b", "<redacted>", text)
    text = re.sub(r"\bgh[pousr]_[A-Za-z0-9]{12,}\b", "<redacted>", text)
    text = re.sub(r"\bglpat-[A-Za-z0-9_\-]{12,}\b", "<redacted>", text)
    text = re.sub(r"\beyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b", "<redacted>", text)
    text = re.sub(r"(?i)(access_token=)[^&\s]+", r"\1<redacted>", text)
    text = re.sub(r"(?i)(bearer|token|password|secret|api[_-]?key)\s*[:=]\s*\S+", r"\1=<redacted>", text)
    text = re.sub(r"/Users/[^/\s]+", "/Users/<redacted>", text)
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record):
        return redact(super(RedactingFormatter, self).format(record))


def configure_logging(verbose=False):
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.DEBUG if verbose else logging.INFO)


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path, value):
    parent = os.path.dirname(path)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".cursor-", suffix=".json", dir=parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


@contextlib.contextmanager
def exclusive_lock(path):
    parent = os.path.dirname(path)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SyncError("another sync process holds the file lock")
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def validate_config(raw):
    required = ("user_id", "source_device", "db_path", "state_path", "lock_path")
    missing = [key for key in required if not str(raw.get(key, "")).strip()]
    if missing:
        raise SyncError("missing config keys: %s" % ", ".join(missing))
    if raw["source_device"] == "CHANGE_ME":
        raise SyncError("source_device must be a stable per-machine slug")
    config = dict(raw)
    for key in ("db_path", "state_path", "lock_path"):
        config[key] = expand_path(config[key])
    config.setdefault("api_base_url", "https://api.mem0.ai")
    config.setdefault("api_key_env", "MEM0_API_KEY")
    config.setdefault("api_key_keychain_service", "")
    config.setdefault("api_key_keychain_account", "")
    config.setdefault("project_aliases", {})
    config.setdefault("retry_attempts", 4)
    config.setdefault("event_poll_attempts", 20)
    return config


def get_api_key(config):
    env_name = config.get("api_key_env")
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    service = config.get("api_key_keychain_service")
    account = config.get("api_key_keychain_account")
    if service and account and sys.platform == "darwin":
        completed = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-w", "-s", service, "-a", account],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            return completed.stdout.strip()
    raise SyncError("Mem0 API key unavailable in configured environment or macOS Keychain")


def db_fingerprint(config):
    stat = os.stat(config["db_path"])
    birth_ns = getattr(stat, "st_birthtime_ns", None)
    if birth_ns is None:
        birth_ns = int(getattr(stat, "st_birthtime", stat.st_ctime) * 1000000000)
    seed = "%s\0%s\0%s\0%s\0%s" % (
        os.path.realpath(config["db_path"]),
        config["source_device"],
        stat.st_dev,
        stat.st_ino,
        birth_ns,
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def open_db(path):
    if not os.path.isfile(path):
        raise SyncError("claude-mem database does not exist")
    uri = "file:%s?mode=ro" % urllib.request.pathname2url(path)
    connection = sqlite3.connect(uri, uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    columns = {row[1] for row in connection.execute("PRAGMA table_info(observations)")}
    required = {"id", "project", "type", "title", "text", "narrative", "facts", "created_at"}
    if not required.issubset(columns):
        connection.close()
        raise SyncError("unsupported claude-mem observations schema")
    return connection


def latest_observation_id(connection):
    row = connection.execute("SELECT COALESCE(MAX(id), 0) FROM observations").fetchone()
    return int(row[0])


def observations_after(connection, cursor, limit):
    return connection.execute(
        """
        SELECT id, project, type, title, text, narrative, facts, created_at
        FROM observations
        WHERE id > ?
        ORDER BY id ASC
        LIMIT ?
        """,
        (cursor, limit),
    ).fetchall()


def new_state(config, cursor):
    return {
        "schema_version": 1,
        "source_device": config["source_device"],
        "db_fingerprint": db_fingerprint(config),
        "cursor": int(cursor),
        "initialized_at": utc_now(),
        "pending": None,
    }


def load_state(config):
    path = config["state_path"]
    if not os.path.exists(path):
        return None
    state = load_json(path)
    if state.get("source_device") != config["source_device"]:
        raise SyncError("cursor source_device does not match this machine")
    if state.get("db_fingerprint") != db_fingerprint(config):
        raise SyncError("cursor database identity does not match config")
    return state


def persist_state(config, state, dry_run=False):
    if not dry_run:
        atomic_write_json(config["state_path"], state)


def resume_pending(config, state, client, dry_run=False):
    pending = state.get("pending")
    if not pending:
        return
    if dry_run:
        logging.info("dry-run pending obs_id=%s would be polled", pending["obs_id"])
        return
    try:
        wait_for_event(client, pending["event_id"], config["event_poll_attempts"])
    except SyncError as error:
        if str(error) != "Mem0 event failed":
            raise
        state["pending"] = None
        state["updated_at"] = utc_now()
        persist_state(config, state)
        logging.warning("failed event cleared; obs_id=%s will be retried", pending["obs_id"])
        return
    state["cursor"] = int(pending["obs_id"])
    state["pending"] = None
    state["updated_at"] = utc_now()
    persist_state(config, state)
    logging.info("completed pending obs_id=%s", state["cursor"])


def run_search(config, query, project):
    client = Mem0Client(get_api_key(config), config["api_base_url"], config["retry_attempts"])
    results = client.search(query, config["user_id"], project=project)
    scope = "project"
    if not results and project:
        results = client.search(query, config["user_id"], project=None)
        scope = "user_fallback"
    print(json.dumps({"scope": scope, "results": results}, ensure_ascii=False, indent=2))


def run_sync(config, args):
    with exclusive_lock(config["lock_path"]):
        connection = open_db(config["db_path"])
        try:
            state = load_state(config)
            latest = latest_observation_id(connection)

            if args.backfill_from is not None:
                if args.confirm_backfill != BACKFILL_CONFIRMATION:
                    raise SyncError("historical backfill requires --confirm-backfill %s" % BACKFILL_CONFIRMATION)
                state = new_state(config, int(args.backfill_from) - 1)
                logging.warning("confirmed historical backfill from obs_id=%s", args.backfill_from)
                persist_state(config, state, args.dry_run)
            elif state is None:
                state = new_state(config, latest)
                persist_state(config, state, args.dry_run)
                logging.info("initialized cursor at current latest obs_id=%s; no history uploaded", latest)
                return

            if latest < int(state["cursor"]):
                raise SyncError(
                    "database max observation id is behind cursor; refusing a replaced or truncated database"
                )

            client = None
            if state.get("pending"):
                client = Mem0Client(get_api_key(config), config["api_base_url"], config["retry_attempts"])
                resume_pending(config, state, client, args.dry_run)
                if args.dry_run:
                    return

            rows = observations_after(connection, int(state["cursor"]), int(args.limit))
            if not rows:
                logging.info("no new observations after cursor=%s", state["cursor"])
                return

            uploaded = skipped = 0
            for row in rows:
                eligible, reason = classify(row)
                if not eligible:
                    skipped += 1
                    logging.info("skip obs_id=%s type=%s reason=%s", row["id"], row["type"], reason)
                    if not args.dry_run:
                        state["cursor"] = int(row["id"])
                        state["updated_at"] = utc_now()
                        persist_state(config, state)
                    continue

                project = normalize_project(row["project"], config["project_aliases"])
                unique_source_key = source_key(config, row["id"])
                logging.info(
                    "%s obs_id=%s type=%s project=%s source_key=%s",
                    "would-upload" if args.dry_run else "upload",
                    row["id"],
                    row["type"],
                    project,
                    unique_source_key,
                )
                if args.dry_run:
                    uploaded += 1
                    continue

                if client is None:
                    client = Mem0Client(get_api_key(config), config["api_base_url"], config["retry_attempts"])
                if client.source_exists(config["user_id"], unique_source_key):
                    logging.info("deduplicated obs_id=%s by unique source key", row["id"])
                else:
                    metadata = {
                        "project": project,
                        "source": "claude-mem",
                        "source_device": config["source_device"],
                        "obs_id": int(row["id"]),
                        "source_key": unique_source_key,
                        "memory_type": str(row["type"]),
                        "source_created_at": str(row["created_at"]),
                    }
                    response = client.add(
                        config["user_id"], unique_source_key, memory_text(row), metadata
                    )
                    event_id = response.get("event_id")
                    status = str(response.get("status") or "PENDING").upper()
                    if event_id and status != "SUCCEEDED":
                        state["pending"] = {"obs_id": int(row["id"]), "event_id": event_id}
                        persist_state(config, state)
                        try:
                            wait_for_event(client, event_id, config["event_poll_attempts"])
                            state["pending"] = None
                        except RetryableSyncError:
                            raise
                        except SyncError:
                            state["pending"] = None
                            persist_state(config, state)
                            raise
                    elif status == "FAILED":
                        raise SyncError("Mem0 add event failed")
                    elif status != "SUCCEEDED":
                        raise RetryableSyncError("Mem0 add returned no event identifier")

                state["cursor"] = int(row["id"])
                state["updated_at"] = utc_now()
                persist_state(config, state)
                uploaded += 1

            logging.info(
                "%s uploaded=%s skipped=%s cursor=%s",
                "dry-run" if args.dry_run else "sync-complete",
                uploaded,
                skipped,
                state["cursor"],
            )
        finally:
            connection.close()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="~/.config/leshine-memory/config.json",
        help="machine-local JSON config path",
    )
    parser.add_argument("--dry-run", action="store_true", help="classify only; do not call Mem0 or write state")
    parser.add_argument("--limit", type=int, default=100, help="maximum observations per run")
    parser.add_argument("--backfill-from", type=int, help="explicit historical observation ID")
    parser.add_argument("--confirm-backfill", help="must equal %s" % BACKFILL_CONFIRMATION)
    parser.add_argument("--search", help="run the project-first retrieval preset instead of syncing")
    parser.add_argument("--project", help="stable project slug for --search")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be positive")
    if args.search is not None:
        if not args.search.strip():
            parser.error("--search query cannot be empty")
        if not args.project:
            parser.error("--search requires --project so project-first retrieval cannot be bypassed")
    return args


def main(argv=None):
    args = parse_args(argv)
    configure_logging(args.verbose)
    try:
        config = validate_config(load_json(expand_path(args.config)))
        if args.search is not None:
            run_search(config, args.search, args.project)
        else:
            run_sync(config, args)
        return 0
    except (SyncError, json.JSONDecodeError, sqlite3.Error) as error:
        logging.error("sync failed: %s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
