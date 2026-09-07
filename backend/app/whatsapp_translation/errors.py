"""Stable, privacy-safe domain errors."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler


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
    @app.exception_handler(RequestValidationError)
    async def handle_private_validation(request: Request, exc: RequestValidationError):
        if request.url.path == "/api/whatsapp-translation/reply-suggestions":
            # FastAPI's default includes invalid input values (possibly chat text).
            return JSONResponse(status_code=422, headers={"Cache-Control": "no-store"}, content={
                "code": 422, "message": "Invalid reply request", "data": {"error_code": "reply_invalid_request"},
            })
        return await request_validation_exception_handler(request, exc)

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
