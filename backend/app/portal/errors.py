"""Stable customer-safe errors, without database parameters or internal identities."""


class PortalError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, *, issues=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.issues = issues or []


def reject(code, message, status=409):
    raise PortalError(code, message, status)


class TransactionBusy(PortalError):
    """A recognized MySQL row wait in a participating authorization transaction."""
    def __init__(self):
        super().__init__('TRANSACTION_BUSY',
            'The service is busy. Check the original request before retrying.', 503)


def register_portal_error_handler(app):
    """Upstream Ark routes may time out after their initial authority check.

    Portal routes already localize PortalError. Register only this dedicated
    exception globally; other database/domain errors keep their existing contract.
    The request's Session dependency owns rollback/close, never this handler.
    """
    from uuid import uuid4
    from fastapi.responses import JSONResponse
    from app.core.response import ok

    async def transaction_busy_handler(request, error):
        return JSONResponse(status_code=503, content=ok(code=503,
            message='交易服务繁忙，请先核对原操作结果后再重试。',
            data={'error_code':'TRANSACTION_BUSY', 'trace_id':str(uuid4()),
                'retryable':True, 'issues':[]}),
            headers={'Cache-Control':'private, no-store', 'Pragma':'no-cache'})
    app.add_exception_handler(TransactionBusy, transaction_busy_handler)
