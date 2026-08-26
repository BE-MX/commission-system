"""钉钉集成 — API 路由"""


from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.api.deps import get_db
from app.auth.dependencies import require_permission
from app.core.response import ok
from app.dingtalk import gmv_daily_config, gmv_daily_service
from app.dingtalk.gmv_daily_schemas import (
    GmvDailyConfigUpdate,
    GmvDailyPreviewRequest,
    GmvDailySendRequest,
)
from app.schemas.common import ResponseModel, PageResponse
from app.dingtalk.models import DingTalkMessageLog, DingTalkCallbackLog
from app.dingtalk.schemas import (
    WebhookMarkdownRequest,
    WebhookTextRequest,
    WebhookActionCardRequest,
    MessageLogItem,
    CallbackLogItem,
)
from app.dingtalk.webhook import get_webhook_sender

router = APIRouter()


# ── 每日 GMV 点对点推送 ─────────────────────────────────


@router.get("/gmv-daily/config", summary="GMV 日报配置与候选项")
def get_gmv_daily_config(
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_permission("dingtalk:admin")),
):
    return ok({
        "config": gmv_daily_config.decorate_config(db),
        "options": gmv_daily_config.config_options(db),
    })


@router.put("/gmv-daily/config", summary="保存 GMV 日报配置")
def update_gmv_daily_config(
    request: GmvDailyConfigUpdate,
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_permission("dingtalk:admin")),
):
    try:
        saved = gmv_daily_config.save_config(db, request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ok(saved, "GMV 日报配置已保存")


@router.post("/gmv-daily/preview", summary="预览 GMV 日报")
def preview_gmv_daily_report(
    request: GmvDailyPreviewRequest,
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_permission("dingtalk:admin")),
):
    return ok(gmv_daily_service.preview_report(db, request.report_date))


@router.post("/gmv-daily/send", summary="手动发送或补发 GMV 日报")
async def send_gmv_daily_report(
    request: GmvDailySendRequest,
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_permission("dingtalk:admin")),
):
    try:
        result = await gmv_daily_service.send_daily_report(db, request.report_date, request.scope)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ok(result, "GMV 日报发送任务已完成")


# ── 手动发送消息（测试用）───────────────────────────────


@router.post("/webhook/text", summary="发送文本消息")
async def send_text(
    req: WebhookTextRequest,
    _current_user: dict = Depends(require_permission("dingtalk:admin")),
):
    sender = get_webhook_sender()
    result = await sender.send_text(
        content=req.content,
        at_mobiles=req.at_mobiles,
        is_at_all=req.is_at_all,
    )
    return ResponseModel(data=result)


@router.post("/webhook/markdown", summary="发送 Markdown 消息")
async def send_markdown(
    req: WebhookMarkdownRequest,
    _current_user: dict = Depends(require_permission("dingtalk:admin")),
):
    sender = get_webhook_sender()
    result = await sender.send_markdown(
        title=req.title,
        text=req.text,
        at_mobiles=req.at_mobiles,
        is_at_all=req.is_at_all,
    )
    return ResponseModel(data=result)


@router.post("/webhook/action-card", summary="发送 ActionCard 消息")
async def send_action_card(
    req: WebhookActionCardRequest,
    _current_user: dict = Depends(require_permission("dingtalk:admin")),
):
    sender = get_webhook_sender()
    result = await sender.send_action_card(
        title=req.title,
        text=req.text,
        btns=req.btns,
        btn_orientation=req.btn_orientation,
    )
    return ResponseModel(data=result)


# ── 消息发送日志 ──────────────────────────────────────────


@router.get("/messages", summary="消息发送记录")
def list_messages(
    msg_type: str = Query("", description="消息类型过滤"),
    send_status: str = Query("", description="发送状态过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_permission("dingtalk:admin")),
) -> ResponseModel:
    query = db.query(DingTalkMessageLog)
    if msg_type:
        query = query.filter(DingTalkMessageLog.msg_type == msg_type)
    if send_status:
        query = query.filter(DingTalkMessageLog.send_status == send_status)

    total = query.with_entities(func.count()).scalar()
    rows = query.order_by(desc(DingTalkMessageLog.id)).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    items = [
        MessageLogItem(
            id=r.id,
            msg_type=r.msg_type,
            title=r.title,
            send_status=r.send_status,
            error_msg=r.error_msg,
            related_type=r.related_type,
            related_id=r.related_id,
            created_at=r.created_at.isoformat() if r.created_at else "",
            sent_at=r.sent_at.isoformat() if r.sent_at else None,
        )
        for r in rows
    ]

    return ResponseModel(data=PageResponse(
        items=items, total=total, page=page, page_size=page_size,
    ))


# ── 回调日志 ──────────────────────────────────────────────


@router.get("/callbacks", summary="回调接收记录")
def list_callbacks(
    event_type: str = Query("", description="事件类型过滤"),
    processed: int = Query(-1, description="处理状态: -1全部 0未处理 1已处理"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_permission("dingtalk:admin")),
) -> ResponseModel:
    query = db.query(DingTalkCallbackLog)
    if event_type:
        query = query.filter(DingTalkCallbackLog.event_type == event_type)
    if processed >= 0:
        query = query.filter(DingTalkCallbackLog.processed == bool(processed))

    total = query.with_entities(func.count()).scalar()
    rows = query.order_by(desc(DingTalkCallbackLog.id)).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    items = [
        CallbackLogItem(
            id=r.id,
            event_type=r.event_type,
            processed=r.processed,
            process_result=r.process_result,
            created_at=r.created_at.isoformat() if r.created_at else "",
            processed_at=r.processed_at.isoformat() if r.processed_at else None,
        )
        for r in rows
    ]

    return ResponseModel(data=PageResponse(
        items=items, total=total, page=page, page_size=page_size,
    ))
