"""钉钉回调处理 — 接收审批状态变更等事件"""

import json
import logging
from app.core.time import beijing_now

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.dingtalk.callback_crypto import CallbackCryptoError, DingTalkCallbackCrypto
from app.dingtalk.config import get_dingtalk_settings
from app.dingtalk.models import DingTalkCallbackLog

logger = logging.getLogger("commission.dingtalk")

router = APIRouter(prefix="/dingtalk", tags=["钉钉回调"])

# 钉钉事件推送是几 KB 的加密串，远超即视为异常请求
MAX_BODY_BYTES = 256 * 1024


def _reject(status_code: int, reason: str) -> PlainTextResponse:
    logger.warning("拒绝钉钉回调: %s", reason)
    print(f"[dingtalk-callback] rejected: {reason}", flush=True)
    return PlainTextResponse(reason, status_code=status_code)


# 机器对机器端点：不走 RBAC，身份由钉钉签名 + AES 加密 + 接收方 AppKey 证明；未配置时拒绝一切请求
@router.post("/callback")
async def dingtalk_callback(request: Request, db: Session = Depends(get_db)):
    """
    钉钉事件回调入口（HTTP 推送，加密模式）。

    钉钉会 POST {"encrypt": ...} 到此 URL，query 带签名、时间戳和随机串，需要：
    1. URL 公网可达（或内网穿透）
    2. 后端配置 DINGTALK_CALLBACK_TOKEN / DINGTALK_CALLBACK_AES_KEY / DINGTALK_CALLBACK_RECEIVER_ID，
       与钉钉开放平台「事件订阅」页填写的一致，再在平台上验证此 URL

    主要事件:
    - bpms_instance_change: 审批实例状态变更
    - check_url: URL 验证（钉钉首次验证回调地址）
    """
    settings = get_dingtalk_settings()
    try:
        crypto = DingTalkCallbackCrypto(
            settings.DINGTALK_CALLBACK_TOKEN,
            settings.DINGTALK_CALLBACK_AES_KEY,
            settings.DINGTALK_CALLBACK_RECEIVER_ID,
        )
    except CallbackCryptoError as exc:
        return _reject(503, f"callback_{exc}")

    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return _reject(413, "body_too_large")
    try:
        envelope = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return _reject(400, "invalid_json")
    if not isinstance(envelope, dict) or not isinstance(envelope.get("encrypt"), str):
        return _reject(400, "missing_encrypt")

    params = request.query_params
    try:
        body = crypto.decrypt(
            params.get("signature") or params.get("msg_signature") or "",
            params.get("timestamp", ""),
            params.get("nonce", ""),
            envelope["encrypt"],
        )
    except CallbackCryptoError as exc:
        return _reject(403, str(exc))

    event_type = body.get("EventType", "")
    logger.info("收到钉钉回调: %s", event_type)

    # URL 验证（钉钉首次配置回调时发送）：只需加密应答 success
    if event_type == "check_url":
        return JSONResponse(crypto.encrypt("success"))

    # 记录回调日志
    log = DingTalkCallbackLog(
        event_type=event_type,
        raw_data=json.dumps(body, ensure_ascii=False),
        processed=False,
    )
    db.add(log)
    db.commit()

    # 分发处理
    if event_type == "bpms_instance_change":
        await _handle_approval_change(body, log, db)
    elif event_type == "bpms_task_change":
        await _handle_task_change(body, log, db)
    else:
        logger.info("未处理的钉钉事件类型: %s", event_type)

    # 钉钉要求返回加密后的 "success"
    return JSONResponse(crypto.encrypt("success"))


async def _handle_approval_change(body: dict, log: DingTalkCallbackLog, db: Session):
    """
    处理审批实例状态变更。

    body 中包含:
    - processInstanceId: 审批实例 ID
    - corpId: 企业 ID
    - title: 审批标题
    - type: finish/agree/refuse/revoke/redirect
    - result: agree/refuse（type=finish 时）
    - createTime: 创建时间
    - finishTime: 完成时间
    """
    process_instance_id = body.get("processInstanceId", "")
    action_type = body.get("type", "")
    result = body.get("result", "")

    logger.info(
        "审批状态变更: instance=%s, action=%s, result=%s",
        process_instance_id,
        action_type,
        result,
    )

    # TODO: 根据 processInstanceId 找到对应的业务记录（设计预约等）
    # TODO: 更新业务状态
    # 示例:
    # if action_type == "finish" and result == "agree":
    #     # 审批通过
    #     await approve_design_request(process_instance_id, db)
    # elif action_type == "finish" and result == "refuse":
    #     # 审批拒绝
    #     await reject_design_request(process_instance_id, db)

    log.processed = True
    log.process_result = f"action={action_type}, result={result}"
    log.processed_at = beijing_now()
    db.commit()


async def _handle_task_change(body: dict, log: DingTalkCallbackLog, db: Session):
    """处理审批任务状态变更（如任务到达、任务完成）"""
    logger.info("审批任务变更: %s", body.get("taskId", ""))

    log.processed = True
    log.process_result = "task_change_recorded"
    log.processed_at = beijing_now()
    db.commit()
