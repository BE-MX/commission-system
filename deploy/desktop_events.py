"""Versioned, run-correlated desktop progress; CLI behavior remains unchanged."""
import json
import os
import re

PREFIX = "ARK_DEPLOY_EVENT "
PROTOCOL = 1


def enabled():
    return bool(re.fullmatch(r"[a-f0-9]{32}", os.environ.get("ARK_DESKTOP_RUN_ID", "")))


def emit(kind, **data):
    run_id = os.environ.get("ARK_DESKTOP_RUN_ID", "")
    if enabled():
        print(PREFIX + json.dumps(dict(protocol=PROTOCOL, run_id=run_id, kind=kind, **data),
                                 ensure_ascii=True), flush=True)


def step(key, label, action, *args, **kwargs):
    emit("step", key=key, label=label, status="running")
    try:
        result = action(*args, **kwargs)
    except Exception as error:
        # Raw errors may contain subprocess credentials: the desktop diagnoses
        # from sanitized output plus these fixed stage/type fields.
        emit("step", key=key, label=label, status="failed", error_type=type(error).__name__)
        raise
    emit("step", key=key, label=label, status="succeeded")
    return result
