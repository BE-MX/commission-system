"""微信小程序端路由 — /api/mini/*"""

import logging
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.auth.models import ArkUser
from app.auth.service import get_user_permissions
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
from app.domestic import constants as domestic_constants
from app.shipping_inspection import file_service as shipping_file_service
from app.shipping_inspection import outbound_service as shipping_outbound_service
from app.shipping_inspection import qr_service as shipping_qr_service
from app.shipping_inspection import service as shipping_service
from app.shipping_inspection.schemas import ShippingScanRequest, ShippingSubmitRequest

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()


def _domestic_report_mode(user: ArkUser) -> str:
    """Two explicit permissions are mutually exclusive for ordinary worker roles.

    Both/none resolve to the legacy quantity mode, so existing workers and admin users
    are not silently switched to a different production behavior after deployment.
    """
    permissions = set(get_user_permissions(user))
    if (
        domestic_constants.REPORT_UNIT_PERMISSION in permissions
        and domestic_constants.REPORT_QUANTITY_PERMISSION not in permissions
    ):
        return "unit"
    return "quantity"


# ── 认证 ──────────────────────────────────────────────────

@router.post("/auth/dev-login", summary="开发模式：用工号直接换 token")
async def mini_dev_login(body: dict, db: Session = Depends(get_db)):
    """开发调试用：输入工号或手机号，直接返回 JWT，不走微信。仅 APP_ENV != production 时可用。"""
    if settings.APP_ENV == "production":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "生产环境不可用"})

    identifier = body.get("identifier", "").strip()
    if not identifier:
        raise HTTPException(status_code=400, detail={"code": "MISSING_IDENTIFIER", "message": "请输入工号"})

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
            # 文案只提工号：小程序隐私审核不允许出现"手机号"字样（2026-07-29）；
            # 匹配逻辑仍兼容手机号，老用户不受影响
            "USER_NOT_FOUND": (404, "找不到匹配的用户，请检查工号"),
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
# 与上面的外贸报工两点不同：二维码前缀是 ARK-D/ARK-DU、报工可按数量或逐件。
# 登录仍沿用 mini token；角色权限只用来决定报工模式。

@router.get("/domestic/scan/{item_id}", summary="内贸扫码：取明细与可报数量")
async def domestic_scan(
    item_id: int,
    sign: str = Query(..., description="二维码 HMAC 签名"),
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    valid, signed_id = domestic_report_service.verify_qr_data(
        f"{domestic_constants.QR_PREFIX}:{item_id}:{sign}"
    )
    if not valid or signed_id != item_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "SIGN_INVALID", "message": "二维码无效，请用系统打印的内贸流转卡"},
        )
    mode = _domestic_report_mode(current_user)
    if mode == "unit":
        return {
            "can_submit": False,
            "block_reason": "UNIT_QR_REQUIRED",
            "block_message": "当前账号已配置逐件扫码模式，请扫描 A1-01 这类单件二维码",
            "report_mode": mode,
        }
    data = domestic_report_service.scan_item(db, item_id, current_user.id)
    data["report_mode"] = mode
    return data


@router.get("/domestic/unit-scan/{unit_id}", summary="内贸逐件二维码扫码")
async def domestic_unit_scan(
    unit_id: int,
    sign: str = Query(..., description="逐件二维码 HMAC 签名"),
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    valid, signed_id = domestic_report_service.verify_unit_qr_data(
        f"{domestic_constants.UNIT_QR_PREFIX}:{unit_id}:{sign}"
    )
    if not valid or signed_id != unit_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "SIGN_INVALID", "message": "单件二维码无效，请用系统打印的逐件标签"},
        )
    mode = _domestic_report_mode(current_user)
    if mode == "unit":
        return domestic_report_service.scan_unit(db, unit_id, current_user.id)

    # Quantity-mode workers may scan any unit label to identify the product, but the
    # actual submission still consumes A1-01/A1-02/... in sequence.
    from app.domestic.models import DomesticItemUnit

    unit = db.query(DomesticItemUnit).get(unit_id)
    if not unit or unit.status != 1:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "单件二维码不存在或已失效"})
    data = domestic_report_service.scan_item(db, unit.item_id, current_user.id)
    data.update({"report_mode": mode, "scanned_unit_id": unit.id, "scanned_unit_no": unit.unit_no})
    return data


@router.post("/domestic/scan/submit", summary="内贸报工（带数量，可拆批）")
async def domestic_submit(
    body: DomesticSubmitRequest,
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    try:
        mode = _domestic_report_mode(current_user)
        if mode == "unit" and not body.unit_id:
            raise ValueError("逐件扫码模式必须提交单件二维码")
        if mode == "unit":
            valid, signed_id = domestic_report_service.verify_unit_qr_data(
                f"{domestic_constants.UNIT_QR_PREFIX}:{body.unit_id}:{body.unit_sign or ''}"
            )
            if not valid or signed_id != body.unit_id:
                raise ValueError("单件二维码签名无效，请重新扫描标签")
        if mode == "unit" and body.qty != 1:
            raise ValueError("逐件扫码模式每次只能报 1 件")
        return domestic_report_service.submit_report(
            db, item_id=body.item_id, progress_id=body.progress_id,
            qty=1 if mode == "unit" else body.qty,
            unit_id=body.unit_id if mode == "unit" else None,
            user_id=current_user.id, source="mini",
            request_id=body.request_id,
            outcomes=body.outcomes,
        )
    except ValueError as exc:
        message = str(exc)
        retryable = message == "该报工请求正在并发处理，请使用同一请求号重试"
        raise HTTPException(
            status_code=409 if retryable else 422,
            detail={"code": "SUBMIT_PENDING" if retryable else "SUBMIT_FAILED", "message": message},
        )


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
        include_finance=False,
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
        data = domestic_order_service.lookup_order(db, code, include_finance=False)
        db.commit()
        return data
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)})


@router.get("/domestic/track", summary="完整订单进度（小程序码免登录查看）")
async def domestic_track(
    scene: str = Query(..., description="小程序码 scene：i:<item_id>:<hmac16>"),
    db: Session = Depends(get_db),
):
    """无鉴权白名单端点：微信扫「进度小程序码」进来的客户没有方舟账号。
    授权凭证是 scene 里的 HMAC 签名——码只能由主站有 domestic 权限的人生成，
    拿到码 = 被授权看这一张订单；验签不过一律 403。
    亮哥 2026-07-28 拍板：进度信息对客户公开，字段不遮挡。
    2026-08-17 起返回完整订单详情和全部明细，但每条明细的工序仍由
    process.show_in_domestic_track 在服务端过滤。
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
        detail = domestic_order_service.get_order_detail(
            db, item.order_id, public_progress_only=True, include_finance=False,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "订单不存在或已删除"})
    db.commit()
    return detail


@router.get("/domestic/track-image", summary="进度码授权范围内的参考图")
async def domestic_track_image(
    scene: str = Query(...),
    rel_path: str = Query(...),
    db: Session = Depends(get_db),
):
    """无登录图片端点，但 scene 只能读取其明细真实引用的图片路径。"""
    if domestic_report_service.qr_secret_is_default():
        raise HTTPException(status_code=503, detail={"code": "NOT_CONFIGURED", "message": "服务未完成安全配置"})
    valid, item_id = domestic_report_service.verify_track_scene(scene)
    if not valid:
        raise HTTPException(status_code=403, detail={"code": "BAD_SCENE", "message": "二维码无效"})
    from app.domestic.models import DomesticOrder, DomesticOrderItem

    item = db.query(DomesticOrderItem).get(item_id)
    order = db.query(DomesticOrder).get(item.order_id) if item else None
    if not item or not order or order.deleted_flag:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "订单不存在"})
    order_items = db.query(DomesticOrderItem).filter(
        DomesticOrderItem.order_id == order.id,
    ).all()
    allowed = {
        path
        for order_item in order_items
        for field in ("hairstyle_images", "color_images", "style_images", "remark_images")
        for path in (getattr(order_item, field) or [])
    }
    if rel_path not in allowed:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "图片不属于该进度码"})
    try:
        abs_path = domestic_file_service.resolve_path(rel_path)
    except domestic_file_service.FileValidationError as exc:
        raise HTTPException(status_code=400, detail={"code": "BAD_PATH", "message": str(exc)})
    if not abs_path.is_file():
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "图片不存在"})
    return FileResponse(abs_path)


@router.get("/domestic/orders/{order_id}", summary="内贸订单明细进度")
async def domestic_order_detail(
    order_id: int,
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    _ = current_user
    try:
        data = domestic_order_service.get_order_detail(db, order_id, include_finance=False)
        db.commit()
        return data
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)})


# ── 发货检验 ──────────────────────────────────────────────
# 业务逻辑全在 app/shipping_inspection，这里只做薄路由。
# mini token 无 RBAC，登录绑定即可用（与上面 mini 页面同一口径）。

@router.post("/shipping-inspection/scan", summary="发货检验：扫出库单二维码")
async def shipping_scan(
    body: ShippingScanRequest,
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    _ = current_user
    valid, record_id = shipping_qr_service.verify_qr_data(body.qr_raw)
    if not valid:
        raise HTTPException(
            status_code=400,
            detail={"code": "SIGN_INVALID", "message": "二维码无效，请扫描系统打印的出库单二维码"},
        )
    try:
        return shipping_service.scan_payload(db, record_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "RECORD_NOT_FOUND", "message": str(exc)})
    except shipping_outbound_service.OutboundTableError:
        logger.exception("shipping-inspection scan: 业务库出库表结构异常")
        raise HTTPException(
            status_code=500,
            detail={"code": "OUTBOUND_SOURCE_ERROR", "message": "出库单数据源异常，请联系管理员"},
        )


@router.post("/shipping-inspection/photos", summary="发货检验：上传验货照片（逐张）")
async def shipping_upload_photo(
    file: UploadFile = File(...),
    outbound_record_id: str = Form(...),
    item_id: str | None = Form(None),
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    # 先拿声明大小挡一刀超大请求体，避免全量读进内存后才校验（M3）
    declared = getattr(file, "size", None)
    if declared is not None and declared > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail={"code": "BAD_FILE", "message": "图片不能超过 20MB"})
    content = await file.read()
    try:
        shipping_file_service.validate_upload(file.filename, file.content_type or "", len(content))
    except shipping_file_service.FileValidationError as exc:
        raise HTTPException(status_code=400, detail={"code": "BAD_FILE", "message": str(exc)})
    rel_path = shipping_file_service.store_bytes(file.filename, content)
    try:
        photo = shipping_service.add_photo(
            db,
            outbound_record_id=outbound_record_id,
            item_id=item_id or None,
            file_path=rel_path,
            user_id=current_user.id,
        )
    except ValueError as exc:
        # 业务校验失败（已提交/明细不存在等）：清掉刚落盘的文件，不留孤儿
        try:
            shipping_file_service.resolve_path(rel_path).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001 - 清理失败只记日志
            logger.warning("清理被拒的验货照片失败 path=%s", rel_path)
        raise HTTPException(status_code=400, detail={"code": "UPLOAD_REJECTED", "message": str(exc)})
    except shipping_outbound_service.OutboundTableError:
        try:
            shipping_file_service.resolve_path(rel_path).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            logger.warning("清理被拒的验货照片失败 path=%s", rel_path)
        logger.exception("shipping-inspection upload: 业务库出库表结构异常")
        raise HTTPException(
            status_code=500,
            detail={"code": "OUTBOUND_SOURCE_ERROR", "message": "出库单数据源异常，请联系管理员"},
        )
    return {"id": photo.id, "file_path": photo.file_path}


@router.delete("/shipping-inspection/photos/{photo_id}", summary="发货检验：删除照片（仅提交前）")
async def shipping_delete_photo(
    photo_id: int,
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    try:
        shipping_service.delete_photo(db, photo_id, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "DELETE_REJECTED", "message": str(exc)})
    return {"deleted": True}


@router.post("/shipping-inspection/submit", summary="发货检验：提交验货单")
async def shipping_submit(
    body: ShippingSubmitRequest,
    current_user: ArkUser = Depends(get_current_mini_user),
    db: Session = Depends(get_db),
):
    try:
        inspection = shipping_service.submit(
            db,
            outbound_record_id=body.outbound_record_id,
            user_id=current_user.id,
            remark=body.remark,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "SUBMIT_REJECTED", "message": str(exc)})
    return {
        "id": inspection.id,
        "outbound_record_id": inspection.outbound_record_id,
        "status": inspection.status,
        "photo_count": inspection.photo_count,
        "submitted_at": inspection.submitted_at.isoformat() if inspection.submitted_at else None,
    }


@router.get("/shipping-inspection/images/{rel_path:path}", summary="验货照片（小程序）")
async def shipping_image(
    rel_path: str,
    current_user: ArkUser = Depends(get_current_mini_user),
):
    """小程序 token 里没有 RBAC 声明，走不了主站那个 shipping_inspection:read 图片端点，
    所以这里给一个同源的 mini 版本——小程序显示缩略图用。"""
    _ = current_user
    try:
        abs_path = shipping_file_service.resolve_path(rel_path)
    except shipping_file_service.FileValidationError as exc:
        raise HTTPException(status_code=400, detail={"code": "BAD_PATH", "message": str(exc)})
    if not abs_path.is_file():
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "图片不存在"})
    return FileResponse(abs_path)
