"""开发机采集器的机器对机器鉴权（红线 3 白名单：无用户身份，凭 token 的 SHA-256 列表校验）。

Settings.DEVLOG_INGEST_TOKEN_HASHES 允许同时登记新旧两个哈希，轮换时先加新、改开发机、再删旧。
"""
import hashlib
import hmac

from fastapi import Header, HTTPException, Request
from fastapi.routing import APIRoute
import re

from app.core.config import get_settings

MAX_BODY_BYTES = 4 * 1024 * 1024


def _require_devlog_machine(x_devlog_token: str | None = Header(default=None)) -> None:
    hashes = [value.strip().lower() for value in get_settings().DEVLOG_INGEST_TOKEN_HASHES.split(",") if re.fullmatch(r"[0-9a-fA-F]{64}", value.strip())]
    if not hashes or not x_devlog_token or not 24 <= len(x_devlog_token) <= 512:
        raise HTTPException(status_code=401, detail="采集器凭证无效")
    digest = hashlib.sha256(x_devlog_token.encode("utf-8")).hexdigest()
    matched = False
    for expected in hashes:
        matched = hmac.compare_digest(digest, expected) or matched
    if not matched:
        raise HTTPException(status_code=401, detail="采集器凭证无效")


def _require_small_body(request: Request) -> None:
    length = request.headers.get("content-length")
    if length is None or not length.isascii() or not length.isdigit() or len(length) > 10 or int(length) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="上报内容超过上限或缺少长度")


class MachineBodyRoute(APIRoute):
    """Enforce the actual byte limit before FastAPI's JSON/model parsing."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def bounded(request: Request):
            if request.method == "POST":
                _require_devlog_machine(request.headers.get("x-devlog-token"))
                _require_small_body(request)
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > MAX_BODY_BYTES:
                        raise HTTPException(status_code=413, detail="上报内容超过上限")
                request._body = bytes(body)
            return await original(request)

        return bounded
