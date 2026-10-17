"""Versioned, run-correlated desktop progress; CLI behavior remains unchanged."""
import json
import os
import re
import sys
import time
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from static_retention import atomic_json

PREFIX = "ARK_DEPLOY_EVENT "
PROTOCOL = 1
_timing = None
_guard = threading.RLock()


def log_line(value):
    """One complete write, shared by concurrent progress and protocol events."""
    with _guard:
        sys.stdout.write(value + '\n')
        sys.stdout.flush()


def timestamp():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='milliseconds')


def save_timing():
    global _timing
    with _guard:
        if not _timing or _timing[0] is None:
            return
        try:
            atomic_json(*_timing)
        except OSError:
            # Observability must never change a migration/freeze/activation result
            # or mask its original exception, particularly when the disk is full.
            _timing = (None, _timing[1])
            log_line('WARNING: deployment timing file unavailable; release checks continue')


@contextmanager
def timing_session(state, **metadata):
    """Persist CLI and desktop timings, including failed and interrupted phases."""
    global _timing
    previous = _timing
    started = time.perf_counter()
    path = state / 'timings' / (uuid.uuid4().hex + '.json')
    data = dict(schema=1, started_at=timestamp(), status='running', steps=[], **metadata)
    _timing = (path, data)
    save_timing()
    try:
        yield data
    except BaseException as error:
        data.update(status='failed', error_type=type(error).__name__)
        raise
    else:
        data['status'] = 'succeeded'
    finally:
        data.update(finished_at=timestamp(), elapsed_ms=round((time.perf_counter() - started) * 1000, 3))
        try:
            save_timing()
        finally:
            _timing = previous


def enabled():
    return bool(re.fullmatch(r"[a-f0-9]{32}", os.environ.get("ARK_DESKTOP_RUN_ID", "")))


def emit(kind, **data):
    run_id = os.environ.get("ARK_DESKTOP_RUN_ID", "")
    if enabled():
        log_line(PREFIX + json.dumps(dict(protocol=PROTOCOL, run_id=run_id, kind=kind, **data),
                                    ensure_ascii=True))


def step(key, label, action, *args, **kwargs):
    started = time.perf_counter()
    row = dict(key=key, label=label, status='running', started_at=timestamp())
    with _guard:
        if _timing:
            _timing[1]['steps'].append(row)
            save_timing()
    emit("step", key=key, label=label, status="running")
    try:
        result = action(*args, **kwargs)
    except Exception as error:
        # Raw errors may contain subprocess credentials: the desktop diagnoses
        # from sanitized output plus these fixed stage/type fields.
        with _guard:
            row.update(status='failed', error_type=type(error).__name__)
        emit("step", key=key, label=label, status="failed", error_type=type(error).__name__,
             elapsed_ms=round((time.perf_counter() - started) * 1000, 3))
        raise
    else:
        with _guard:
            row['status'] = 'succeeded'
    finally:
        with _guard:
            row.update(finished_at=timestamp(), elapsed_ms=round((time.perf_counter() - started) * 1000, 3))
            if _timing:
                save_timing()
    emit("step", key=key, label=label, status="succeeded", elapsed_ms=row['elapsed_ms'])
    return result
