"""邮件触达域稳定错误与 HTTP 异常映射。

模式对齐 app.whatsapp_translation.errors：域服务只抛 MailOutreachError，
HTTP 状态码与 error_code 由这里统一收口，异常处理器在 main.py 注册。
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class MailOutreachError(Exception):
    """域内稳定错误：status_code + error_code + 面向用户的安全 message。"""

    def __init__(self, status_code: int, error_code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


def not_found(message: str = "资源不存在或无权访问") -> MailOutreachError:
    return MailOutreachError(404, "not_found", message)


def bad_request(message: str, error_code: str = "bad_request") -> MailOutreachError:
    return MailOutreachError(400, error_code, message)


def forbidden(message: str = "无权限执行该操作", error_code: str = "forbidden") -> MailOutreachError:
    return MailOutreachError(403, error_code, message)


def conflict(message: str, error_code: str = "conflict") -> MailOutreachError:
    return MailOutreachError(409, error_code, message)


def unavailable(message: str, error_code: str = "service_unavailable") -> MailOutreachError:
    return MailOutreachError(503, error_code, message)


def register_mail_outreach_error_handler(app: FastAPI) -> None:
    @app.exception_handler(MailOutreachError)
    async def handle_mail_outreach_error(request: Request, exc: MailOutreachError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.status_code,
                "message": exc.message,
                "data": {"error_code": exc.error_code},
            },
        )
