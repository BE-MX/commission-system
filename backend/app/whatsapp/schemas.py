"""Schemas for WhatsApp Connector integration."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BindSessionCreate(BaseModel):
    ark_user_id: int | None = Field(default=None, description="管理员可指定绑定到哪个方舟用户")


class BindSessionOut(BaseModel):
    id: int | None = None
    bind_session_uid: str
    account_uid: str | None = None
    ark_user_id: int
    status: str
    qr_code_url: str | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AccountOut(BaseModel):
    id: int
    account_uid: str
    ark_user_id: int
    phone_number: str | None = None
    display_name: str | None = None
    status: str
    connector_status: str | None = None
    last_sync_at: datetime | None = None
    last_message_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SyncPullRequest(BaseModel):
    account_uid: str
    resource: str = Field(default="messages", pattern="^(conversations|messages)$")
    limit: int = Field(default=100, ge=1, le=500)


class SyncPullResponse(BaseModel):
    account_uid: str
    resource: str
    pulled: int
    next_cursor: str | None = None


class ConversationOut(BaseModel):
    id: int
    conversation_uid: str
    account_uid: str
    chat_id: str
    contact_phone: str | None = None
    contact_name: str | None = None
    is_group: bool = False
    last_message_at: datetime | None = None
    last_message_preview: str | None = None


class MessageOut(BaseModel):
    id: int
    message_uid: str
    account_uid: str
    conversation_uid: str | None = None
    external_message_id: str
    direction: str
    sender_phone: str | None = None
    content_type: str = "text"
    content_text: str | None = None
    content_preview: str | None = None
    sent_at: datetime | None = None
    received_at: datetime | None = None


class ConnectorPage(BaseModel):
    items: list[dict[str, Any]] = []
    next_cursor: str | None = None
