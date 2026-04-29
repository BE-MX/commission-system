"""钉钉回调处理 — 接收审批状态变更等事件"""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.dingtalk.models import DingTalkCallbackLog

logger = logging.getLogger("commission.dingtalk")

router = APIRouter(prefix="/dingtalk", tags=["钉钉回调"])


@router.post("/callback")
async def dingtalk_callback(request: Request, db: Session = Depends(get_db)):
    """
    钉钉事件回调入口。

    钉钉会 POST JSON 到此 URL，需要：
    1. URL 公网可达（或内网穿透）
    2. 在钉钉开放平台配置此 URL 并验证通过

    主要事件:
    - bpms_instance_change: 审批实例状态变更
    - check_url: URL 验证（钉钉首次验证回调地址）
    """
    body = await request.json()
    logger.info("收到钉钉回调: %s", json.dumps(body, ensure_ascii=False)[:200])

    # URL 验证（钉钉首次配置回调时发送）
    if "encrypt" in body:
        # TODO: 解密 encrypt 字段，返回验证响应
        return PlainTextResponse("success")

    event_type = body.get("EventType", "")

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

    # 钉钉要求返回 "success"
    return PlainTextResponse("success")


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
    log.processed_at = datetime.now()
    db.commit()


async def _handle_task_change(body: dict, log: DingTalkCallbackLog, db: Session):
    """处理审批任务状态变更（如任务到达、任务完成）"""
    logger.info("审批任务变更: %s", body.get("taskId", ""))

    log.processed = True
    log.process_result = "task_change_recorded"
    log.processed_at = datetime.now()
    db.commit()
