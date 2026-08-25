"""Stable application errors for Agent Runtime APIs."""


class AgentRuntimeError(ValueError):
    status_code = 400
    error_code = "AGENT_RUNTIME_ERROR"


class NotFoundError(AgentRuntimeError):
    status_code = 404
    error_code = "NOT_FOUND"


class ForbiddenError(AgentRuntimeError):
    status_code = 403
    error_code = "FORBIDDEN"


class ConflictError(AgentRuntimeError):
    status_code = 409
    error_code = "CONFLICT"


class LeaseError(ConflictError):
    error_code = "LEASE_INVALID"


class RuntimeDisabledError(AgentRuntimeError):
    status_code = 503
    error_code = "RUNTIME_DISABLED"
