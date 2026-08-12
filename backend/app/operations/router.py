"""Operations center API."""

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import require_any_permission, require_permission
from app.core.response import ok
from app.operations.schemas import JobActionResult, OperationsOverview
from app.operations.service import control_job, get_overview

router = APIRouter()


@router.get("/overview")
async def operations_overview(
    _current_user: dict = Depends(require_any_permission("operations:read", "operations:admin")),
):
    data: OperationsOverview = await get_overview()
    return ok(data.model_dump())


@router.post("/jobs/{job_id}/{action}")
def operations_job_action(
    request: Request,
    job_id: str,
    action: str,
    current_user: dict = Depends(require_permission("operations:admin")),
):
    actor_name = str(current_user.get("username") or current_user.get("sub") or "unknown")
    actor_user_id = int(current_user["sub"]) if str(current_user.get("sub") or "").isdigit() else None
    source_ip = request.headers.get("X-Real-IP", "").strip() or (
        request.client.host if request.client else None
    )
    data: JobActionResult = control_job(
        job_id, action, actor_name, actor_user_id=actor_user_id, source_ip=source_ip,
    )
    return ok(data.model_dump(), data.message)
