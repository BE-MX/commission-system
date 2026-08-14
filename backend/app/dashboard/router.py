"""工作台配置 — API 路由

鉴权豁免说明（宪法 3）：三端点均为个人域数据——user_id 一律取自 JWT sub，
每个用户只能读写自己那一行，天然行级隔离，与 /api/auth/me 同模式用
get_current_user 而非 require_permission。工作台是全员落地页（navigation.js
的 /dashboard entry 无权限声明），不存在对应页面权限码。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.core.response import ok
from app.dashboard import greeting_service, service
from app.dashboard.schemas import DashboardPrefs, GreetingRequest

router = APIRouter()


@router.get("/preference", summary="读当前用户工作台布局配置")
def get_preference(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # JWT 用户 ID 在 sub（字符串），cerebrum 2026-07-13
    prefs = service.get_prefs(db, int(current_user["sub"]))
    return ok(prefs)


@router.put("/preference", summary="保存当前用户工作台布局配置")
def save_preference(
    payload: DashboardPrefs,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    saved = service.upsert_prefs(db, int(current_user["sub"]), payload)
    return ok(saved)


@router.delete("/preference", summary="重置当前用户工作台布局（恢复默认）")
def reset_preference(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    service.reset_prefs(db, int(current_user["sub"]))
    return ok()


@router.post("/greeting", summary="获取今日 AI 问候（未配置模型时规则兜底）")
def get_greeting(
    payload: GreetingRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # 与 preference 同模式：个人域文案，user_id 取自 JWT sub，无页面权限码
    user_name = payload.context.user_name or "同事"
    return ok(
        greeting_service.get_greeting(db, int(current_user["sub"]), user_name, payload)
    )
