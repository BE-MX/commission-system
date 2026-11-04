from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from .reports import redeem

router = APIRouter(tags=["私海早报"])


class RedeemRequest(BaseModel):
    ticket: str = Field(min_length=1, max_length=1400)


@router.get("/reports/handoff")
def handoff(response: Response):
    """Public, constant shell for previews. Holds no data and consumes no ticket."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return ok({"action": "continue", "login_required": True})


@router.post("/reports/redeem")
def exchange(
    body: RedeemRequest,
    response: Response,
    db=Depends(get_db),
    user=Depends(require_permission("client_desk:read")),
):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return ok(redeem(db, user, body.ticket))
