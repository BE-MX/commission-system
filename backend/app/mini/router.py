"""微信小程序端路由 — /api/mini/*"""

import logging
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.auth.models import ArkUser
from app.mini.auth import get_current_mini_user, create_mini_token, jscode2session
from app.mini import service
from app.mini.schemas import (
    MiniBindRequest, MiniLoginRequest,
    ScanSubmitRequest, RevokeRequest,
)

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()


# ── 认证 ──────────────────────────────────────────────────

@router.post("/auth/dev-login", summary="开发模式：用工号直接换 token")
async def mini_dev_login(body: dict, db: Session = Depends(get_db)):
    """开发调试用：输入工号或手机号，直接返回 JWT，不走微信。仅 APP_ENV != production 时可用。"""
    if settings.APP_ENV == "production":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "生产环境不可用"})

    identifier = body.get("identifier", "").strip()
    if not identifier:
        raise HTTPException(status_code=400, detail={"code": "MISSING_IDENTIFIER", "message": "请输入工号或手机号"})

    user = db.query(ArkUser).filter(
        (ArkUser.phone == identifier) | (ArkUser.username == identifier)
    ).first()

    if not user:
        raise HTTPException(status_code=404, detail={"code": "USER_NOT_FOUND", "message": "找不到该用户"})

    token = create_mini_token(user.id, user.wx_id or "")
    return {
        "token": token,
        "user": {"id": user.id, "name": user.real_name or user.username, "wx_id": user.wx_id},
    }


@router.post("/auth/login", summary="微信 code 换 token")
async def mini_login(body: MiniLoginRequest, db: Session = Depends(get_db)):
    """wx.login() code → jscode2session → 查绑定 → 返回 token"""
    try:
        wx_data = await jscode2session(body.code)
    except Exception as e:
        logger.error("jscode2session 失败: %s", e)
        raise HTTPException(status_code=500, detail={"code": "WX_API_ERROR", "message": "微信接口调用失败"})

    open_id = wx_data.get("openid")
    if not open_id:
        raise HTTPException(status_code=400, detail={"code": "WX_CODE_INVALID", "message": "微信 code 无效"})

    # 查是否已绑定
    user_dict = service.login_by_openid(db, open_id)
    if user_dict:
        token = create_mini_token(user_dict["id"], open_id)
        return {"bound": True, "token": token, "user": user_dict}

    return {"bound": False, "open_id": open_id}


@router.post("/auth/bind", summary="绑定微信与方舟用户")
async def mini_bind(body: MiniBindRequest, db: Session = Depends(get_db)):
    result = service.bind_user(db, body.open_id, body.identifier)
    if not result["success"]:
        error = result["error"]
        status_map = {
            "USER_NOT_FOUND": (404, "找不到匹配的用户，请检查工号或手机号"),
            "ALREADY_BOUND": (409, "该方舟用户已绑定其他微信"),
            "OPEN_ID_TAKEN": (409, "该微信已绑定其他方舟用户"),
        }
        status_code, msg = status_map.get(error, (400, "绑定失败"))
        raise HTTPException(status_code=status_code, detail={"code": error, "message": msg})

    user = result["user"]
    token = create_mini_token(user["id"], body.open_id)
    return {"bound": True, "token": token, "user": user}


@router.get("/auth/verify", summary="验证 token 有效性")
async def mini_verify(current_user: ArkUser = Depends(get_current_mini_user)):
    return {
        "valid": True,
        "user": {"id": current_user.id, "name": current_user.real_name or current_user.username, "wx_id": current_user.wx_id},
    }


# ── 扫码报工 ──────────────────────────────────────────────

@router.get("/scan/product/{order_product_id}", summary="扫码获取产品与工序信息")
async def scan_product(
    order_product_id: int,
    sign: str = Query(..., description="二维码 HMAC 签名"),
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    return service.scan_product(db, order_product_id, sign, current_user)


@router.post("/scan/submit", summary="提交报工")
async def scan_submit(
    body: ScanSubmitRequest,
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    result = service.submit_report(db, body.progress_id, body.order_product_id, current_user)
    if not result["success"]:
        raise HTTPException(status_code=422, detail={"code": "SUBMIT_FAILED", "message": result["message"]})
    db.commit()
    return result


@router.get("/scan/history", summary="今日报工记录")
async def scan_history(
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    return service.get_today_history(db, current_user.id)


@router.get("/scan/history/all", summary="历史报工记录（分页）")
async def scan_history_all(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    date_start: str = Query(None, description="开始日期 YYYY-MM-DD"),
    date_end: str = Query(None, description="结束日期 YYYY-MM-DD"),
    keyword: str = Query(None, description="产品型号模糊搜索"),
    order_no: str = Query(None, description="所属批次号"),
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    return service.get_history(db, current_user.id, page, page_size,
                               date_start=date_start, date_end=date_end,
                               keyword=keyword, order_no=order_no)


@router.get("/scan/overview", summary="报工总览（按日期+工序分组，全用户）")
async def scan_overview(
    date_start: str = Query(None, description="开始日期 YYYY-MM-DD"),
    date_end: str = Query(None, description="结束日期 YYYY-MM-DD"),
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    return service.get_overview(db, date_start=date_start, date_end=date_end)


@router.get("/scan/overview/detail", summary="报工总览 — 指定日期+工序的明细列表")
async def scan_overview_detail(
    date: str = Query(..., description="日期 YYYY-MM-DD"),
    process_id: int = Query(..., description="工序 ID"),
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    return service.get_overview_detail(db, date=date, process_id=process_id)


@router.post("/scan/revoke", summary="撤销报工")
async def scan_revoke(
    body: RevokeRequest,
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    result = service.revoke_report(db, body.progress_id, current_user)
    if not result["success"]:
        raise HTTPException(status_code=422, detail={"code": "REVOKE_FAILED", "message": result["message"]})
    db.commit()
    return result


# ── 语音转文字 ────────────────────────────────────────────

@router.post("/voice/transcribe", summary="语音转文字（预留）")
async def voice_transcribe(
    audio: UploadFile = File(...),
    current_user: ArkUser = Depends(get_current_mini_user),
):
    # TODO: 接入腾讯云 ASR 或 OpenAI Whisper
    _ = current_user  # 鉴权占位
    return {"text": "", "message": "语音识别功能即将上线"}


# ── 图片识别 ──────────────────────────────────────────────

@router.post("/vision/recognize", summary="图片识别（预留）")
async def vision_recognize(
    image: UploadFile = File(...),
    current_user: ArkUser = Depends(get_current_mini_user),
):
    _ = current_user
    return {"status": "coming_soon", "message": "图片识别功能即将上线"}
