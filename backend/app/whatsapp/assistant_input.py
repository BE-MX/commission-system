"""Complete, bounded time-range inputs and evidence version checks."""
import hashlib
import json
from datetime import timedelta

from sqlalchemy import func

from app.core.time import to_beijing_naive
from app.whatsapp import access
from app.whatsapp.models import WhatsAppAccount, WhatsAppConversation, WhatsAppMessage

LIMITS = {'max_days': 31, 'max_messages': 2000, 'max_conversations': 25, 'max_calls': 20}
MAX_CHARS = 200000
CHUNK_CHARS = 12000


def normalize_range(start, end):
    if any(value.tzinfo is None or value.utcoffset() is None for value in (start, end)):
        raise ValueError('起止时间必须带时区')
    start, end = to_beijing_naive(start), to_beijing_naive(end)
    if start > end or end - start > timedelta(days=LIMITS['max_days']):
        raise ValueError('请选择有效的起止时间，单次范围最多31天')
    return start, end


def authorized_account(db, user_id, uid, *, generate=False, fresh=False):
    query = db.query(WhatsAppAccount).filter_by(account_uid=uid).populate_existing()
    account = (query.with_for_update() if fresh else query).first()
    if account is None:
        raise LookupError('账号不存在')
    actor = access.require_body(db, account, user_id, fresh=fresh)
    if generate and (account.consent_state != 'active' or not account.ai_egress_allowed):
        raise PermissionError('请由持有人在授权范围中开启AI分析外发')
    return account, actor


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def capture(db, uid, start, end, conversation_uid=None, *, fresh=False):
    when = func.coalesce(WhatsAppMessage.sent_at, WhatsAppMessage.received_at)
    base = db.query(WhatsAppMessage).filter(WhatsAppMessage.account_uid == uid)
    if conversation_uid:
        base = base.filter(WhatsAppMessage.conversation_uid == conversation_uid)
        exists = db.query(WhatsAppConversation.id).filter_by(account_uid=uid, conversation_uid=conversation_uid).first()
        if exists is None:
            raise LookupError('会话不属于该账号')
    query = base.filter(when >= start, when <= end).order_by(when, WhatsAppMessage.id).limit(LIMITS['max_messages'] + 1).populate_existing()
    messages = (query.with_for_update(read=True) if fresh else query).all()
    if len(messages) > LIMITS['max_messages']:
        raise ValueError('时间范围内超过2000条消息，请缩短范围；未进行抽样')
    uids = {row.conversation_uid for row in messages}
    if None in uids or '' in uids:
        raise ValueError('部分消息尚未关联会话，请完成同步后重试')
    if len(uids) > LIMITS['max_conversations']:
        raise ValueError('时间范围内超过25个会话，请缩短范围或选择单个会话')
    conv_query = db.query(WhatsAppConversation).filter(WhatsAppConversation.account_uid == uid,
        WhatsAppConversation.conversation_uid.in_(uids)).order_by(WhatsAppConversation.conversation_uid).populate_existing()
    conversations = (conv_query.with_for_update(read=True) if fresh else conv_query).all()
    if len(conversations) != len(uids):
        raise ValueError('部分会话尚未完成同步，请稍后重试')
    groups = {row.conversation_uid: {
        'conversation_uid': row.conversation_uid, 'title': row.contact_name or row.contact_phone or row.chat_id,
        'is_group': row.is_group, 'coverage': {'history_state': row.history_state, 'gap_reason': row.gap_reason},
        'messages': [],
    } for row in conversations}
    manifest, chars = [], 0
    for row in messages:
        text = '[消息已撤回]' if row.deleted_at else row.content_text or row.content_preview or f'[非文本消息:{row.content_type}]'
        chars += len(text)
        item = {'message_uid': row.message_uid, 'direction': row.direction, 'sender': row.sender_name,
            'at': (row.sent_at or row.received_at).isoformat() + '+08:00', 'content_type': row.content_type, 'text': text}
        groups[row.conversation_uid]['messages'].append(item)
        manifest.append([row.message_uid, row.conversation_uid, row.source_revision, row.deleted_at, item])
    if chars > MAX_CHARS:
        raise ValueError('所选消息超过200000字符，请缩短范围；未截断聊天')
    missing_time = base.filter(when.is_(None)).count()
    warnings = ['仅总结方舟已同步的记录；平台历史缺口及媒体内容可能不完整。']
    if missing_time:
        warnings.append(f'账号范围中有{missing_time}条记录缺少消息时间，无法确定是否属于所选时间段。')
    return list(groups.values()), digest({'messages': manifest, 'conversations': [
        {key: value for key, value in group.items() if key != 'messages'} for group in groups.values()]}), warnings


def chunks(messages):
    """No silent truncation: long single text splits into ordered labeled parts."""
    result, current, size = [], [], 0
    for message in messages:
        text = message['text']
        parts = [text[n:n + 9000] for n in range(0, len(text), 9000)] or ['']
        for index, part in enumerate(parts):
            item = {**message, 'text': part, 'part': index + 1, 'parts': len(parts)}
            length = len(json.dumps(item, ensure_ascii=False))
            if current and size + length > CHUNK_CHARS:
                result.append(current); current, size = [], 0
            current.append(item); size += length
    if current:
        result.append(current)
    return result


def prompt_messages(messages):
    # Transport-local citations avoid repeating 120-160 character source UIDs
    # through every reduction. Stable identities remain in the stored manifest.
    return [{**message, 'message_uid': f'm{index}'} for index, message in enumerate(messages)]
