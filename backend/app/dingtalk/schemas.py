"""钉钉模块请求/响应模型"""

from typing import Optional
from pydantic import BaseModel, Field


# ── Webhook 消息 ──────────────────────────────────────────


class WebhookMarkdownRequest(BaseModel):
    """发送 Markdown 消息"""
    title: str = Field(..., max_length=128, description="消息标题")
    text: str = Field(..., description="Markdown 内容")
    at_mobiles: Optional[list[str]] = Field(default=None, description="@的手机号列表")
    is_at_all: bool = Field(default=False, description="是否@所有人")


class WebhookTextRequest(BaseModel):
    """发送文本消息"""
    content: str = Field(..., description="文本内容")
    at_mobiles: Optional[list[str]] = Field(default=None, description="@的手机号列表")
    is_at_all: bool = Field(default=False, description="是否@所有人")


class WebhookActionCardRequest(BaseModel):
    """发送 ActionCard 消息"""
    title: str = Field(..., max_length=128)
    text: str = Field(..., description="Markdown 内容")
    btns: list[dict] = Field(..., description="按钮列表 [{title, action_url}]")
    btn_orientation: str = Field(default="1", description="0-按钮竖直排列, 1-横向排列")


# ── 审批（Phase 2）───────────────────────────────────────


class ApprovalCreateRequest(BaseModel):
    """发起钉钉审批"""
    process_code: str = Field(..., description="审批流模板编码")
    form_values: dict = Field(..., description="表单字段值")
    approver_user_ids: list[str] = Field(..., description="审批人 UserID 列表")
    cc_user_ids: Optional[list[str]] = Field(default=None, description="抄送人 UserID 列表")


# ── 消息日志查询 ──────────────────────────────────────────


class MessageLogItem(BaseModel):
    id: int
    msg_type: str
    title: str
    send_status: str
    error_msg: Optional[str] = None
    related_type: Optional[str] = None
    related_id: Optional[str] = None
    created_at: str
    sent_at: Optional[str] = None


class CallbackLogItem(BaseModel):
    id: int
    event_type: str
    processed: bool
    process_result: Optional[str] = None
    created_at: str
    processed_at: Optional[str] = None
