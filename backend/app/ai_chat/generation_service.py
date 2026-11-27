"""Durable progress and expiry fencing; never retries an upstream request."""
from datetime import timedelta

from sqlalchemy import and_, or_

from app.ai.billing_service import terminal_failed_fields
from app.ai.models import AiCallLog
from app.ai_chat.models import AiChatMessage, AiChatSession
from app.core.config import get_settings
from app.core.time import beijing_now


class GenerationLost(RuntimeError):
    pass


def lease_deadline(now=None):
    return (now or beijing_now()) + timedelta(seconds=get_settings().AI_CHAT_LEASE_SECONDS)


def live_condition(now=None):
    now = now or beijing_now()
    return and_(AiChatMessage.status == 'streaming',
        or_(and_(AiChatMessage.lease_expires_at.is_not(None), AiChatMessage.lease_expires_at > now),
            and_(AiChatMessage.lease_expires_at.is_(None),
                 AiChatMessage.updated_at > now - timedelta(seconds=get_settings().AI_CHAT_LEASE_SECONDS))),
        AiChatMessage.created_at > now - timedelta(seconds=get_settings().AI_CHAT_GENERATION_MAX_SECONDS))


def recover_expired(db, owner_id, *, commit=True):
    now = beijing_now()
    sessions = db.query(AiChatSession.id).filter(AiChatSession.owner_user_id == owner_id)
    rows = db.query(AiChatMessage).filter(AiChatMessage.session_id.in_(sessions),
        AiChatMessage.status == 'streaming', ~live_condition(now)).populate_existing().with_for_update().all()
    for row in rows:
        row.status = 'failed'
        row.finish_reason = 'lease_expired'
        row.error_message = '上次生成已中断，已保留收到的内容。可以重新生成。'
        row.lease_expires_at = None
        row.updated_at = now
        if row.ai_call_log_id:
            db.query(AiCallLog).filter(AiCallLog.id == row.ai_call_log_id, AiCallLog.status == 'pending').update(
                {'status': 'error', 'error_code': 'generation_interrupted',
                 'error_message': '生成租约已过期', 'updated_at': now,
                 **terminal_failed_fields(now)}, synchronize_session=False)
    if commit:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
    return len(rows)


def checkpoint(db, owner_id, assistant_id, content, reasoning, *, log_id=None, first_token_ms=None):
    now = beijing_now()
    sessions = db.query(AiChatSession.id).filter(AiChatSession.owner_user_id == owner_id,
                                                AiChatSession.deleted_at.is_(None))
    values = {'content': content, 'reasoning_content': reasoning or None,
              'lease_expires_at': lease_deadline(now), 'updated_at': now}
    if log_id is not None:
        values['ai_call_log_id'] = log_id
    if first_token_ms is not None:
        values['first_token_ms'] = first_token_ms
    try:
        changed = db.query(AiChatMessage).filter(AiChatMessage.id == assistant_id,
            AiChatMessage.session_id.in_(sessions), AiChatMessage.role == 'assistant', live_condition(now)).update(
                values, synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    if not changed:
        recover_expired(db, owner_id)
        raise GenerationLost('生成已结束或租约失效，请刷新查看已保存的回答')
