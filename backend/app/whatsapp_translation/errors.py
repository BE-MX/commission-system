"""Stable, privacy-safe domain errors."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class WhatsAppTranslationError(Exception):
    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.retry_after = retry_after


def register_whatsapp_translation_error_handler(app: FastAPI) -> None:
    @app.exception_handler(WhatsAppTranslationError)
    async def handle_whatsapp_translation_error(
        request: Request,
        exc: WhatsAppTranslationError,
    ) -> JSONResponse:
        headers = {"Cache-Control": "no-store"}
        if exc.retry_after is not None:
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.status_code,
                "message": exc.message,
                "data": {"error_code": exc.error_code},
            },
            headers=headers,
        )
