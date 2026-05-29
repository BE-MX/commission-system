"""
积木报表（jimureport）Token 中转接口

设计要点（与 outputs/jimureport-集成开发文档/03-fastapi-token.md 对齐）：
1. 不换发 token：jimureport 的 JmReportTokenServiceImpl 用同一份 JWT_SECRET_KEY
   解析方舟 access_token，方舟 JWT 本身就是入场券。
2. 仅做权限校验 + 从 Authorization Header 取原始 token + 返回前端 iframe 用的拼接信息。
3. 探活 jimureport /internal/health 失败时只记日志不阻断 —— Java 冷启动 30-60s。
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import require_any_permission, require_permission
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────

class ReportTokenResponse(BaseModel):
    token: str           # 方舟 JWT，直接喂给 jimureport
    jmreport_url: str    # jimureport 服务公网地址
    expire_in: int       # token 有效期（秒）
    user_id: str
    username: str


class ReportEmbedRequest(BaseModel):
    report_code: Optional[str] = None
    report_id: Optional[str] = None
    mode: str = "view"   # "view" | "design"


# ── Helpers ──────────────────────────────────────────────

def _extract_bearer(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    return authorization[len("Bearer "):].strip()


async def _probe_jmreport() -> None:
    """探活：失败只记日志，不阻断主流程"""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(
                f"{settings.JMREPORT_INTERNAL_URL}/internal/health"
            )
            if resp.status_code != 200:
                logger.warning(
                    "jmreport health returned %s", resp.status_code
                )
    except Exception as exc:  # pragma: no cover
        logger.warning("jmreport health probe failed: %s", exc)


# ── Endpoints ────────────────────────────────────────────

@router.get("/token", response_model=ReportTokenResponse)
async def get_report_token(
    authorization: str = Header(..., alias="Authorization"),
    user: dict = Depends(
        require_any_permission("report:read", "report:design", "report:admin")
    ),
):
    """
    打开报表前调用，拿到 token 拼成 iframe URL：
        <jmreport_url>/index?token=<token>

    super_admin 自动绕过权限。
    """
    raw_token = _extract_bearer(authorization)
    await _probe_jmreport()
    return ReportTokenResponse(
        token=raw_token,
        jmreport_url=settings.JMREPORT_PUBLIC_URL,
        expire_in=settings.JWT_EXPIRE_MINUTES * 60,
        user_id=user["sub"],          # JWT payload sub = user.id 字符串
        username=user["username"],
    )


@router.post("/token/for-embed", response_model=ReportTokenResponse)
async def get_report_token_for_embed(
    body: ReportEmbedRequest,
    authorization: str = Header(..., alias="Authorization"),
    user: dict = Depends(
        require_any_permission("report:read", "report:design", "report:admin")
    ),
):
    """获取指定报表的嵌入 URL"""
    raw_token = _extract_bearer(authorization)

    report_url = settings.JMREPORT_PUBLIC_URL
    if body.report_code:
        # report_code 由前端 encodeURIComponent 处理
        report_url += (
            f"/index#/reportView?token={raw_token}"
            f"&reportCode={body.report_code}"
        )

    return ReportTokenResponse(
        token=raw_token,
        jmreport_url=report_url,
        expire_in=settings.JWT_EXPIRE_MINUTES * 60,
        user_id=user["sub"],
        username=user["username"],
    )


@router.get("/health")
async def check_report_service_health(
    _user: dict = Depends(require_permission("report:read")),
):
    """前端用此判断报表服务是否在线"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.JMREPORT_INTERNAL_URL}/internal/health"
            )
            if resp.status_code == 200:
                return {"status": "available", "detail": resp.json()}
    except Exception as exc:
        logger.warning("jmreport service unavailable: %s", exc)

    return {
        "status": "unavailable",
        "detail": "报表服务暂时不可用，请稍后再试",
    }
