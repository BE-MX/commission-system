"""私海客户工作台（PCW）稳定错误与 HTTP 异常映射。

模式对齐 app.mail_outreach.errors：域服务只抛 PcwError，
HTTP 状态码与 error_code 由这里统一收口，异常处理器在 main.py 注册。
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class PcwError(Exception):
    """域内稳定错误：status_code + error_code + 面向用户的安全 message。

    details 携带结构性冲突上下文（如 409 的当前可见版本），随响应 data 返回。
    """

    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.details = details or {}


def not_found(
    message: str = "资源不存在或无权访问",
    error_code: str = "not_found",
    details: dict | None = None,
) -> PcwError:
    return PcwError(404, error_code, message, details)


def customer_not_found(message: str = "客户不存在或无权访问") -> PcwError:
    return PcwError(404, "CUSTOMER_NOT_FOUND_OR_FORBIDDEN", message)


def bad_request(
    message: str,
    error_code: str = "bad_request",
    details: dict | None = None,
) -> PcwError:
    return PcwError(400, error_code, message, details)


def forbidden(
    message: str = "无权限执行该操作",
    error_code: str = "forbidden",
    details: dict | None = None,
) -> PcwError:
    return PcwError(403, error_code, message, details)


def conflict(
    message: str,
    error_code: str = "conflict",
    details: dict | None = None,
) -> PcwError:
    return PcwError(409, error_code, message, details)


def unavailable(message: str, error_code: str = "service_unavailable") -> PcwError:
    return PcwError(503, error_code, message)


def register_pcw_error_handler(app: FastAPI) -> None:
    @app.exception_handler(PcwError)
    async def handle_pcw_error(request: Request, exc: PcwError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.status_code,
                "message": exc.message,
                "data": {"error_code": exc.error_code, **exc.details},
            },
        )
