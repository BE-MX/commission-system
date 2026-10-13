"""Version-aware current message projection, including irreversible tombstones."""
from typing import Any
from sqlalchemy.orm import Session
from app.whatsapp.models import WhatsAppMessage, WhatsAppAttachment
from app.whatsapp.payload import parse_dt as _parse_dt


def _validate_payload(payload):
    for field, length in {'message_uid': 160, 'external_message_id': 180, 'conversation_uid': 120,
        'sender_wa_id': 180, 'sender_id': 180, 'sender_phone': 80, 'sender_name': 160,
        'sender_display_name': 160, 'content_type': 40, 'type': 40, 'content_preview': 500,
        'raw_payload_hash': 80}.items():
        value = payload.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > length):
            raise ValueError('标准消息字段类型或长度不合法')
    for field in ('content_text', 'text'):
        value = payload.get(field)
        if value is not None and (not isinstance(value, str) or len(value.encode('utf-8')) > 65535):
            raise ValueError('标准消息正文类型或容量不合法')
    if payload.get('direction') is not None and payload['direction'] not in ('inbound', 'outbound', 'in', 'out'):
        raise ValueError('标准消息方向不合法')
    for field in ('sent_at', 'received_at', 'deleted_at'):
        value = payload.get(field)
        if value is not None and _parse_dt(value) is None:
            raise ValueError('标准消息时间不合法')
    attachments = payload.get('attachments')
    if attachments is not None:
        if not isinstance(attachments, list) or len(attachments) > 50:
            raise ValueError('标准消息附件类型或数量不合法')
        for item in attachments:
            if not isinstance(item, dict):
                raise ValueError('标准消息附件结构不合法')
            for key, length in {'file_name': 255, 'name': 255, 'mime_type': 120, 'storage_url': 2048, 'url': 2048}.items():
                value = item.get(key)
                if value is not None and (not isinstance(value, str) or len(value) > length):
                    raise ValueError('标准消息附件字段不合法')
            size = item.get('file_size')
            if size is not None and (type(size) is not int or size < 0 or size > 2**63 - 1):
                raise ValueError('标准消息附件大小不合法')


def upsert_message(db: Session, account_uid: str, payload: dict[str, Any]) -> WhatsAppMessage:
    _validate_payload(payload)
    external_id = payload.get("external_message_id") or payload.get("message_id") or payload.get("id")
    if not external_id:
        raise ValueError("message 缺少 external_message_id")
    message_uid = payload.get("message_uid") or f"{account_uid}:{external_id}"
    if len(message_uid) > 160 or len(external_id) > 180:
        raise ValueError("消息身份超出已登记范围")
    msg = db.query(WhatsAppMessage).filter(WhatsAppMessage.message_uid == message_uid).first()
    if not msg:
        msg = WhatsAppMessage(message_uid=message_uid, account_uid=account_uid, external_message_id=external_id)
        db.add(msg)
    if msg.account_uid != account_uid:
        raise ValueError("消息身份跨账号")
    revision = payload.get("source_revision", 0)
    if type(revision) is not int or revision < 0:
        raise ValueError('消息来源版本不合法')
    if msg.deleted_at or (revision and msg.source_revision and revision <= msg.source_revision):
        return msg
    msg.source_revision = revision
    msg.deleted_at = _parse_dt(payload.get("deleted_at"))

    msg.conversation_uid = payload.get("conversation_uid") or msg.conversation_uid
    msg.direction = payload.get("direction") or msg.direction or "inbound"
    msg.sender_wa_id = payload.get("sender_wa_id") or payload.get("sender_id") or msg.sender_wa_id
    msg.sender_phone = payload.get("sender_phone")
    msg.sender_name = payload.get("sender_name") or payload.get("sender_display_name")
    msg.content_type = payload.get("content_type") or payload.get("type") or "text"
    msg.content_text = payload.get("content_text", payload.get("text"))
    if msg.deleted_at:
        msg.content_text = None
    msg.content_preview = payload.get("content_preview") or (msg.content_text[:500] if msg.content_text else None)
    msg.sent_at = _parse_dt(payload.get("sent_at")) or _parse_dt(payload.get("timestamp")) or msg.sent_at
    msg.received_at = _parse_dt(payload.get("received_at")) or msg.received_at
    msg.raw_payload_hash = payload.get("raw_payload_hash")
    msg.raw_payload = {**payload, 'content_text': None, 'content_preview': None, 'attachments': []} if msg.deleted_at else payload
    if msg.deleted_at:
        msg.content_preview = None
        msg.raw_payload_hash = None

    attachments = [] if msg.deleted_at else payload.get("attachments")
    if isinstance(attachments, list):
        db.query(WhatsAppAttachment).filter(WhatsAppAttachment.message_uid == message_uid).delete()
        for item in attachments:
            if not isinstance(item, dict):
                continue
            db.add(
                WhatsAppAttachment(
                    message_uid=message_uid,
                    file_name=item.get("file_name") or item.get("name"),
                    mime_type=item.get("mime_type"),
                    file_size=item.get("file_size"),
                    storage_url=item.get("storage_url") or item.get("url"),
                )
            )
    return msg
