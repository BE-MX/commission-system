"""Operations center API."""

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from app.auth.dependencies import require_any_permission, require_permission
from app.core.response import ok
from app.operations.observability import (
    allow_runtime_heartbeat,
    ingest_runtime_heartbeat,
    verify_runtime_heartbeat_token,
)
from app.operations.schemas import (
    JobActionResult,
    JobRunView,
    OperationsOverview,
    RuntimeHeartbeatAck,
    RuntimeHeartbeatPayload,
)
from app.operations.service import control_job, get_job_runs, get_overview

router = APIRouter()


@router.get("/overview")
async def operations_overview(
    _current_user: dict = Depends(require_any_permission("operations:read", "operations:admin")),
):
    data: OperationsOverview = await get_overview()
    return ok(data.model_dump())


@router.get("/job-runs")
def operations_job_runs(
    job_id: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=30, ge=1, le=100),
    _current_user: dict = Depends(require_any_permission("operations:read", "operations:admin")),
):
    data: list[JobRunView] = get_job_runs(job_id, status, limit)
    return ok([item.model_dump() for item in data])


@router.post("/heartbeats")
def runtime_heartbeat(
    payload: RuntimeHeartbeatPayload,
    authorization: str | None = Header(default=None),
):
    """Machine-only endpoint; a service-and-instance-bound bearer token is the credential."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not verify_runtime_heartbeat_token(
        payload.service_id, payload.instance_id, token,
    ):
        raise HTTPException(status_code=401, detail="心跳凭证无效")
    if not allow_runtime_heartbeat(payload.service_id, payload.instance_id):
        raise HTTPException(status_code=429, detail="心跳上报过于频繁")
    data: RuntimeHeartbeatAck = ingest_runtime_heartbeat(payload)
    return ok(data.model_dump(), "心跳已接收")


@router.post("/jobs/{job_id}/{action}")
def operations_job_action(
    request: Request,
    job_id: str,
    action: str,
    current_user: dict = Depends(require_permission("operations:admin")),
):
    actor_name = str(current_user.get("username") or current_user.get("sub") or "unknown")
    actor_user_id = int(current_user["sub"]) if str(current_user.get("sub") or "").isdigit() else None
    # ProxyHeadersMiddleware/Uvicorn may replace request.client only for trusted
    # proxies. Never trust a raw X-Real-IP header supplied by the caller.
    source_ip = request.client.host if request.client else None
    data: JobActionResult = control_job(
        job_id, action, actor_name, actor_user_id=actor_user_id, source_ip=source_ip,
    )
    return ok(data.model_dump(), data.message)
