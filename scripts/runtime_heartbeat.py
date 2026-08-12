#!/usr/bin/env python3
"""Send a least-privilege heartbeat from a cloud cron, MCP, Shopify, or OpenClaw unit."""

import argparse
import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat()


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"缺少环境变量 {name}")
    return value


def _csv(name: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def send_once(*, require_stable_started_at: bool = False) -> None:
    base_url = _required("ARK_OPERATIONS_BASE_URL").rstrip("/")
    try:
        parsed_base = urlsplit(base_url)
        _ = parsed_base.port
    except ValueError as exc:
        raise ValueError("ARK_OPERATIONS_BASE_URL 必须是有效 URL") from exc
    local_http = parsed_base.scheme == "http" and parsed_base.hostname in {
        "127.0.0.1", "localhost", "::1",
    }
    if (
        parsed_base.scheme != "https" and not local_http
        or not parsed_base.hostname
        or parsed_base.username
        or parsed_base.password
        or parsed_base.query
        or parsed_base.fragment
        or parsed_base.path not in {"", "/"}
    ):
        raise ValueError("ARK_OPERATIONS_BASE_URL 必须使用 HTTPS（本机回环地址除外）")
    token = _required("ARK_HEARTBEAT_TOKEN")
    if len(token) < 24:
        raise ValueError("ARK_HEARTBEAT_TOKEN 至少 24 个字符")
    configured_started_at = os.environ.get("ARK_RUNTIME_STARTED_AT", "").strip()
    if require_stable_started_at and not configured_started_at:
        raise ValueError("cron 单次上报必须配置稳定的 ARK_RUNTIME_STARTED_AT")
    payload = {
        "service_id": _required("ARK_RUNTIME_SERVICE_ID"),
        "instance_id": os.environ.get("ARK_RUNTIME_INSTANCE_ID", socket.gethostname()).strip(),
        "service_name": _required("ARK_RUNTIME_SERVICE_NAME"),
        "environment": os.environ.get("ARK_RUNTIME_ENVIRONMENT", "leshine.work 云端").strip(),
        "version": os.environ.get("ARK_RUNTIME_VERSION", "").strip() or None,
        "status": os.environ.get("ARK_RUNTIME_STATUS", "healthy").strip(),
        "started_at": configured_started_at or PROCESS_STARTED_AT,
        "last_activity_at": os.environ.get("ARK_RUNTIME_LAST_ACTIVITY_AT", "").strip() or None,
        "capabilities": _csv("ARK_RUNTIME_CAPABILITIES"),
        "dependencies": _csv("ARK_RUNTIME_DEPENDENCIES"),
    }
    request = Request(
        f"{base_url}/api/operations/heartbeats",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "ark-runtime-heartbeat/1.0",
        },
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"heartbeat returned HTTP {response.status}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true", help="持续上报；默认只上报一次，适合 cron")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    while True:
        try:
            send_once(require_stable_started_at=not args.watch)
            print(f"runtime heartbeat accepted at {_iso_now()}", flush=True)
        except (ValueError, RuntimeError, HTTPError, URLError, TimeoutError) as exc:
            print(f"runtime heartbeat failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            if not args.watch:
                return 1
        if not args.watch:
            return 0
        time.sleep(max(15, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
