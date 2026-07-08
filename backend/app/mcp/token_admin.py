"""MCP 个人 token 管理端点(内部) — 发放 / 列出 / 吊销。

权限:mcp:admin(super_admin 自动绕过)。明文 token 仅发放时返回一次。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import ok
from app.auth.dependencies import require_permission
from app.auth.models import ArkUser
from app.auth.utils import generate_refresh_token
from app.mcp.models import MCPToken

router = APIRouter()
logger = logging.getLogger("commission.mcp.token_admin")


class IssueTokenRequest(BaseModel):
    user_id: int = Field(..., description="归属业务员 ark_users.id")
    label: str | None = Field(default=None, max_length=100, description="用途备注/接入的 agent 名")


@router.post("/tokens", summary="发放 MCP 个人 token（明文仅返回一次）")
def issue_token(
    req: IssueTokenRequest,
    db: Session = Depends(get_db),
    operator: dict = Depends(require_permission("mcp:admin")),
):
    user = db.query(ArkUser).filter(
        ArkUser.id == req.user_id, ArkUser.deleted_at.is_(None)
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="目标用户不存在")

    plain, token_hash = generate_refresh_token()
    row = MCPToken(
        token_hash=token_hash,
        user_id=user.id,
        label=req.label,
        created_by=int(operator.get("sub")) if operator.get("sub") else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return ok({
        "id": row.id,
        "user_id": user.id,
        "username": user.username,
        "label": row.label,
        "token": plain,  # ⚠️ 仅此一次返回，请立即保存
        "note": "明文 token 仅本次返回，丢失只能吊销后重新发放",
    })


@router.get("/tokens", summary="列出 MCP token（不含明文）")
def list_tokens(
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("mcp:admin")),
):
    rows = (
        db.query(MCPToken, ArkUser.username)
        .join(ArkUser, ArkUser.id == MCPToken.user_id)
        .order_by(MCPToken.created_at.desc())
        .all()
    )
    items = [
        {
            "id": t.id,
            "user_id": t.user_id,
            "username": username,
            "label": t.label,
            "is_active": t.is_active,
            "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t, username in rows
    ]
    return ok({"total": len(items), "items": items})


@router.delete("/tokens/{token_id}", summary="吊销 MCP token")
def revoke_token(
    token_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("mcp:admin")),
):
    row = db.query(MCPToken).filter(MCPToken.id == token_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="token 不存在")
    row.is_active = False
    db.commit()
    return ok({"id": token_id, "is_active": False}, message="已吊销")
