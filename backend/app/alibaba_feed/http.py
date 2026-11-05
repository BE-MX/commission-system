"""Safe response envelopes shared by collector and source administration routes."""
import logging
from uuid import uuid4

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError

from app.core.response import ok
from .errors import FeedError

logger = logging.getLogger(__name__)


def error_response(error: FeedError, request_id: str):
    data = {"error_code": error.error_code, "request_id": request_id, "field_errors": []}
    if error.field_path:
        data["field_errors"] = [{"field_path": error.field_path, "code": error.error_code}]
    headers = {"X-Request-ID": request_id, "Cache-Control": "no-store"}
    if error.retry_after is not None:
        headers["Retry-After"] = str(error.retry_after)
    if error.status_code == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(status_code=error.status_code,
                        content=ok(data, message="request rejected", code=error.status_code), headers=headers)


class FeedRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            request_id = uuid4().hex
            try:
                response = await original(request)
                response.headers["X-Request-ID"] = request_id
                response.headers["Cache-Control"] = "no-store"
                return response
            except FeedError as exc:
                return error_response(exc, request_id)
            except RequestValidationError:
                # Validation errors can include submitted values and unknown object keys.
                return error_response(FeedError(422, "REQUEST_INVALID"), request_id)
            except HTTPException as exc:
                code = {401: "TOKEN_INVALID", 403: "SOURCE_SCOPE_DENIED", 404: "SOURCE_NOT_FOUND",
                        409: "SOURCE_VERSION_CONFLICT", 422: "REQUEST_INVALID"}.get(exc.status_code, "REQUEST_REJECTED")
                return error_response(FeedError(exc.status_code, code), request_id)
            except SQLAlchemyError as exc:
                message = f"Alibaba feed request failed ({type(exc).__name__}), request_id={request_id}"
                logger.warning(message)
                print(message, flush=True)
                return error_response(FeedError(503, "INGEST_TEMPORARILY_UNAVAILABLE"), request_id)
        return handler
