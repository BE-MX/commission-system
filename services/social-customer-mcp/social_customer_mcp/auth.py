"""Constant-time Bearer token authentication for the whole MCP transport."""

import hmac
import json
from collections.abc import Awaitable, Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BearerAuthMiddleware:
    def __init__(self, app: ASGIApp, token: str):
        self.app = app
        self.expected = f"Bearer {token}".encode("utf-8")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/health":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        supplied = headers.get(b"authorization", b"")
        if not hmac.compare_digest(supplied, self.expected):
            payload = json.dumps(
                {"error": "unauthorized", "message": "请使用 Authorization: Bearer <token>"},
                ensure_ascii=False,
            ).encode("utf-8")
            response_start: Message = {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
            await send(response_start)
            await send({"type": "http.response.body", "body": payload})
            return

        await self.app(scope, receive, send)
