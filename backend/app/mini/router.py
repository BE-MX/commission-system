"""微信小程序端路由 — /api/mini/*"""

import logging
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.auth.models import ArkUser
from app.mini.auth import get_current_mini_user, create_mini_token, jscode2session
from app.mini import service
from app.mini.schemas import (
    MiniBindRequest, MiniLoginRequest,
    ScanSubmitRequest, RevokeRequest,
    DomesticSubmitRequest, DomesticRevokeRequest,
)
from app.domestic import file_service as domestic_file_service
from app.domestic import order_service as domestic_order_service
from app.domestic import report_service as domestic_report_service
from app.domestic.constants import QR_PREFIX as DOMESTIC_QR_PREFIX

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
    db.commit()   # bind_user 只 flush；不 commit 的话 session 关闭时回滚，绑定静默丢失
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


# ── 内贸报工 ──────────────────────────────────────────────
# 业务逻辑全在 app/domestic/report_service，这里只做薄路由。
# 与上面的外贸报工两点不同：二维码前缀是 ARK-D、报工带数量（支持拆批）。
# 鉴权沿用 get_current_mini_user（小程序端一贯不接 RBAC，见 docs/api-reference.md）。

@router.get("/domestic/scan/{item_id}", summary="内贸扫码：取明细与可报数量")
async def domestic_scan(
    item_id: int,
    sign: str = Query(..., description="二维码 HMAC 签名"),
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    valid, signed_id = domestic_report_service.verify_qr_data(
        f"{DOMESTIC_QR_PREFIX}:{item_id}:{sign}"
    )
    if not valid or signed_id != item_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "SIGN_INVALID", "message": "二维码无效，请用系统打印的内贸流转卡"},
        )
    return domestic_report_service.scan_item(db, item_id, current_user.id)


@router.post("/domestic/scan/submit", summary="内贸报工（带数量，可拆批）")
async def domestic_submit(
    body: DomesticSubmitRequest,
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    try:
        return domestic_report_service.submit_report(
            db, item_id=body.item_id, progress_id=body.progress_id,
            qty=body.qty, user_id=current_user.id, source="mini",
            request_id=body.request_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "SUBMIT_FAILED", "message": str(exc)})


@router.post("/domestic/scan/revoke", summary="内贸撤销报工")
async def domestic_revoke(
    body: DomesticRevokeRequest,
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    try:
        return domestic_report_service.revoke_report(db, body.log_id, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "REVOKE_FAILED", "message": str(exc)})


@router.get("/domestic/history", summary="内贸今日报工记录")
async def domestic_history(
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    records = domestic_report_service.list_today_reports(db, current_user.id)
    active = [r for r in records if not r["revoked"]]
    return {
        "today_count": len(active),
        "today_qty": sum(r["report_qty"] for r in active),
        "records": records,
    }


@router.get("/domestic/history/all", summary="内贸历史报工记录（分页）")
async def domestic_history_all(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    items, total = domestic_report_service.list_reports(
        db, page=page, page_size=page_size, user_id=current_user.id,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/domestic/images/{rel_path:path}", summary="内贸参考图（小程序）")
async def domestic_image(
    rel_path: str,
    current_user: ArkUser = Depends(get_current_mini_user),
):
    """小程序 token 里没有 RBAC 声明，走不了主站那个 domestic:read 图片端点，
    所以这里给一个同源的 mini 版本——车间要在手机上看清参考图才能做对活。"""
    _ = current_user
    try:
        abs_path = domestic_file_service.resolve_path(rel_path)
    except domestic_file_service.FileValidationError as exc:
        raise HTTPException(status_code=400, detail={"code": "BAD_PATH", "message": str(exc)})
    if not abs_path.is_file():
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "图片不存在"})
    return FileResponse(abs_path)


@router.get("/domestic/orders", summary="内贸订单进度（车间/跟单查看）")
async def domestic_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query(""),
    status: int | None = Query(None),
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    _ = current_user
    items, total = domestic_order_service.list_orders(
        db, page=page, page_size=page_size, keyword=keyword, status=status,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/domestic/lookup", summary="订单速查：单号或扫码直接查进度")
async def domestic_lookup(
    code: str = Query(..., description="二维码内容 / 系统单号 / 客户订单号，服务端自行分辨"),
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    _ = current_user
    try:
        return domestic_order_service.lookup_order(db, code)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)})


@router.get("/domestic/track", summary="订单产品进度（小程序码免登录查看）")
async def domestic_track(
    scene: str = Query(..., description="小程序码 scene：i:<item_id>:<hmac16>"),
    db: Session = Depends(get_db),
):
    """无鉴权白名单端点：微信扫「进度小程序码」进来的客户没有方舟账号。
    授权凭证是 scene 里的 HMAC 签名——码只能由主站有 domestic 权限的人生成，
    拿到码 = 被授权看这一个订单产品；验签不过一律 403。
    亮哥 2026-07-28 拍板：进度信息对客户公开，字段不遮挡。
    返回形状与订单详情一致，但 items 只含码指向的那一条明细（码是明细级授权，
    不能连带看到同单其他产品）。
    """
    # 密钥还是仓库默认值时签名可被离线伪造，验证侧同样必须拒绝服务
    if domestic_report_service.qr_secret_is_default():
        raise HTTPException(status_code=503, detail={"code": "NOT_CONFIGURED", "message": "服务未完成安全配置，请联系莱莎跟单"})
    valid, item_id = domestic_report_service.verify_track_scene(scene)
    if not valid:
        raise HTTPException(status_code=403, detail={"code": "BAD_SCENE", "message": "二维码无效，请扫产品进度码"})

    from app.domestic.models import DomesticOrderItem

    item = db.query(DomesticOrderItem).get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "订单明细不存在"})
    try:
        detail = domestic_order_service.get_order_detail(db, item.order_id)
    except ValueError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "订单不存在或已删除"})
    detail["items"] = [i for i in detail["items"] if i["id"] == item_id]
    return detail


@router.get("/domestic/orders/{order_id}", summary="内贸订单明细进度")
async def domestic_order_detail(
    order_id: int,
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    _ = current_user
    try:
        return domestic_order_service.get_order_detail(db, order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)})
