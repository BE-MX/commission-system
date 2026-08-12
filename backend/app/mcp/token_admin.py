"""MCP personal-token administration endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.auth.models import ArkUser
from app.auth.service import get_user_permissions, get_user_roles
from app.auth.utils import generate_refresh_token
from app.core.database import get_db
from app.core.response import ok
from app.knowledge.models import KnowledgeLibrary, KnowledgeLibraryMember
from app.mcp.models import MCPToken

router = APIRouter()
logger = logging.getLogger("commission.mcp.token_admin")


class IssueTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    user_id: int = Field(..., ge=1, description="Bound ark_users.id")
    label: str = Field(..., min_length=2, max_length=100, description="Agent purpose")


def _user_summaries(db: Session, users: list[ArkUser]) -> dict[int, dict]:
    user_ids = [user.id for user in users]
    if not user_ids:
        return {}

    library_counts = dict(
        db.query(KnowledgeLibraryMember.user_id, func.count(KnowledgeLibraryMember.id))
        .filter(KnowledgeLibraryMember.user_id.in_(user_ids))
        .group_by(KnowledgeLibraryMember.user_id)
        .all()
    )
    token_counts = dict(
        db.query(MCPToken.user_id, func.count(MCPToken.id))
        .filter(MCPToken.user_id.in_(user_ids), MCPToken.is_active.is_(True))
        .group_by(MCPToken.user_id)
        .all()
    )
    summaries = {}
    for user in users:
        permissions = set(get_user_permissions(user))
        roles = set(get_user_roles(user))
        is_super_admin = "super_admin" in roles
        library_count = int(library_counts.get(user.id, 0))
        if is_super_admin:
            library_count = int(db.query(func.count()).select_from(KnowledgeLibrary).filter(
                KnowledgeLibrary.deleted_at.is_(None), KnowledgeLibrary.status == "active"
            ).scalar() or 0)
        summaries[user.id] = {
            "user_id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "user_is_active": bool(user.is_active and user.deleted_at is None),
            "has_knowledge_read": is_super_admin or bool(permissions.intersection({
                "knowledge:read", "knowledge:write", "knowledge:review", "knowledge:admin",
            })),
            "knowledge_library_count": library_count,
            "active_token_count": int(token_counts.get(user.id, 0)),
        }
    return summaries


def _active_user(db: Session, user_id: int) -> ArkUser:
    user = db.query(ArkUser).filter(ArkUser.id == user_id, ArkUser.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="目标账号不存在")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="目标账号已停用，不能发放凭证")
    return user


def _issue_row(db: Session, user: ArkUser, label: str, operator_id: int | None) -> tuple[MCPToken, str]:
    plain, token_hash = generate_refresh_token()
    row = MCPToken(
        token_hash=token_hash,
        user_id=user.id,
        label=label,
        created_by=operator_id,
    )
    db.add(row)
    db.flush()
    return row, plain


def _issued_payload(row: MCPToken, user: ArkUser, plain: str, replaced_token_id: int | None = None) -> dict:
    payload = {
        "id": row.id,
        "user_id": user.id,
        "username": user.username,
        "real_name": user.real_name,
        "label": row.label,
        "token": plain,
        "note": "明文 Token 仅本次返回，关闭后无法再次查看",
    }
    if replaced_token_id is not None:
        payload["replaced_token_id"] = replaced_token_id
    return payload


@router.get("/token-candidates", summary="Search eligible MCP token owners")
def list_token_candidates(
    q: str = Query(default="", max_length=50),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("mcp:admin")),
):
    query = db.query(ArkUser).filter(ArkUser.deleted_at.is_(None), ArkUser.is_active.is_(True))
    keyword = q.strip()
    if keyword:
        pattern = f"%{keyword}%"
        query = query.filter(or_(ArkUser.username.ilike(pattern), ArkUser.real_name.ilike(pattern)))
    users = query.order_by(ArkUser.real_name, ArkUser.username).limit(limit).all()
    summaries = _user_summaries(db, users)
    return ok({"items": [summaries[user.id] for user in users]})


@router.post("/tokens", summary="Issue MCP personal token; plaintext is returned once")
def issue_token(
    req: IssueTokenRequest,
    db: Session = Depends(get_db),
    operator: dict = Depends(require_permission("mcp:admin")),
):
    user = _active_user(db, req.user_id)
    row, plain = _issue_row(db, user, req.label, int(operator["sub"]) if operator.get("sub") else None)
    db.commit()
    db.refresh(row)
    return ok(_issued_payload(row, user, plain))


@router.get("/tokens", summary="List MCP tokens without plaintext")
def list_tokens(
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("mcp:admin")),
):
    rows = (
        db.query(MCPToken, ArkUser)
        .join(ArkUser, ArkUser.id == MCPToken.user_id)
        .order_by(MCPToken.created_at.desc(), MCPToken.id.desc())
        .all()
    )
    summaries = _user_summaries(db, [user for _, user in rows])
    items = []
    for token, user in rows:
        items.append({
            "id": token.id,
            "label": token.label,
            "is_active": token.is_active,
            "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None,
            "created_at": token.created_at.isoformat() if token.created_at else None,
            **summaries[user.id],
        })
    return ok({"total": len(items), "items": items})


@router.post("/tokens/{token_id}/rotate", summary="Atomically replace an active MCP token")
def rotate_token(
    token_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    operator: dict = Depends(require_permission("mcp:admin")),
):
    old = db.query(MCPToken).filter(MCPToken.id == token_id).with_for_update().first()
    if not old:
        raise HTTPException(status_code=404, detail="凭证不存在")
    if not old.is_active:
        raise HTTPException(status_code=409, detail="凭证已吊销，不能重复轮换")
    user = _active_user(db, old.user_id)
    replacement, plain = _issue_row(
        db, user, old.label, int(operator["sub"]) if operator.get("sub") else None
    )
    old.is_active = False
    db.commit()
    db.refresh(replacement)
    return ok(_issued_payload(replacement, user, plain, replaced_token_id=old.id))


@router.delete("/tokens/{token_id}", summary="Revoke MCP token")
def revoke_token(
    token_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("mcp:admin")),
):
    row = db.query(MCPToken).filter(MCPToken.id == token_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="凭证不存在")
    row.is_active = False
    db.commit()
    return ok({"id": token_id, "is_active": False}, message="已吊销")
