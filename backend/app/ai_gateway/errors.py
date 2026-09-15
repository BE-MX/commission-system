"""Stable, content-free gateway errors."""

import logging
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class GatewayError(Exception):
    def __init__(self, status: int, error: str, message: str, retry_after: int | None = None):
        self.status = status
        self.error = error
        self.message = message
        self.retry_after = retry_after

    def response(self, request_id=None):
        headers = {"Cache-Control": "no-store"}
        if self.retry_after is not None:
            headers["Retry-After"] = str(self.retry_after)
        return JSONResponse(status_code=self.status, headers=headers, content={
            "code": self.status, "message": self.message,
            "data": {"request_id": request_id, "error": self.error},
        })


def report_failure(exc, request_id=None):
    # Never render SQLAlchemy params, tokens, messages or upstream exception text.
    logger.warning("AI gateway failure: %s request_id=%s", type(exc).__name__, request_id)
    print(f"[AI-GATEWAY] {type(exc).__name__} request_id={request_id}", flush=True)
