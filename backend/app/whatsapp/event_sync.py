"""Commit normalized change batches and their checkpoint in one Ark transaction."""
import logging

from app.core.time import beijing_now
from app.whatsapp import access, identity
from app.whatsapp.connector_client import WhatsAppConnectorClient
from app.whatsapp.models import WhatsAppAccount, WhatsAppConversation, WhatsAppMessage

logger = logging.getLogger(__name__)


def pull_changes(db, account_uid: str, limit: int, resource: str = 'messages') -> tuple[int, str | None]:
    from app.whatsapp.service import _get_cursor, _upsert_account, _upsert_conversation, _upsert_message, _audit
    # Serialize manual/scheduler consumers and consent changes through this row.
    account = db.query(WhatsAppAccount).filter_by(account_uid=account_uid).populate_existing().with_for_update().first()
    if account is None:
        raise LookupError('WhatsApp 账号不存在')
    if not access.owner_enabled(db, account):
        raise PermissionError('账号或员工已停止采集授权')
    expected = (account.session_generation, account.consent_version)
    cursor = _get_cursor(db, account_uid, 'events', 'global')
    page = WhatsAppConnectorClient().pull_changes(account_uid, cursor.cursor_value, limit)
    metadata = page.get('account') or {}
    if (str(metadata.get('session_generation')), str(metadata.get('consent_version'))) != tuple(map(str, expected)):
        raise PermissionError('连接器返回过期接入代次或授权版本')
    if metadata.get('account_uid') != account_uid or metadata.get('ark_user_id') != account.ark_user_id:
        raise ValueError('Connector 账号范围不匹配')
    items = page.get('items')
    if not isinstance(items, list) or len(items) > limit:
        raise ValueError('Connector 变更批次结构不合法')
    count = 0
    rejected = 0
    conversations_count = 0
    last_sequence = 0
    for event in items:
        if not isinstance(event, dict) or not isinstance(event.get('sequence'), int) or event['sequence'] <= last_sequence:
            raise ValueError('Connector 变更顺序不合法')
        last_sequence = event['sequence']
        try:
            payload = event.get('payload')
            if not isinstance(payload, dict):
                raise ValueError('Connector 变更缺少载荷')
            if payload.get('account_uid', account_uid) != account_uid:
                raise PermissionError('Connector 变更跨账号')
            with db.begin_nested():
                if event.get('kind') == 'conversation':
                    _upsert_conversation(db, account_uid, identity.resolve_conversation(db, account_uid, payload))
                    conversations_count += 1
                elif event.get('kind') == 'message':
                    normalized = identity.resolve_message(db, account_uid, payload)
                    conv = db.query(WhatsAppConversation).filter_by(conversation_uid=normalized['conversation_uid'], account_uid=account_uid).first()
                    if conv is None:
                        key = normalized['source_key']
                        conv = _upsert_conversation(db, account_uid, identity.resolve_conversation(db, account_uid, {
                            'chat_id': key['remoteJid'], 'is_group': key['remoteJid'].endswith('@g.us'),
                            'history_state': 'partial',
                        }))
                    previous = db.query(WhatsAppMessage).filter_by(
                        account_uid=account_uid, message_uid=normalized['message_uid'],
                    ).first()
                    previous_revision = previous.source_revision if previous else None
                    msg = _upsert_message(db, account_uid, normalized)
                    conv.last_ingested_at = beijing_now()
                    if conv.history_state in (None, 'unknown'):
                        conv.history_state = 'partial'
                    if msg.sent_at:
                        conv.earliest_seen_at = min(conv.earliest_seen_at, msg.sent_at) if conv.earliest_seen_at else msg.sent_at
                        conv.latest_seen_at = max(conv.latest_seen_at, msg.sent_at) if conv.latest_seen_at else msg.sent_at
                        if conv.last_message_at is None or msg.sent_at >= conv.last_message_at:
                            conv.last_message_at = msg.sent_at
                            conv.last_message_preview = '[消息已撤回]' if msg.deleted_at else msg.content_preview
                        if account.last_message_at is None or msg.sent_at > account.last_message_at:
                            account.last_message_at = msg.sent_at
                    if previous_revision != msg.source_revision:
                        db.flush()  # Production SessionLocal uses autoflush=False.
                        from app.whatsapp.crm_sync import project_changed_message
                        project_changed_message(db, account, msg)
                    count += 1
                elif event.get('kind') == 'account':
                    if str(payload.get('session_generation', expected[0])) != str(expected[0]) or str(payload.get('consent_version', expected[1])) != str(expected[1]):
                        raise PermissionError('变更账号授权已过期')
                else:
                    raise ValueError('不支持的 Connector 变更类型')
                db.flush()
        except ValueError:
            # Invalid protocol payloads are isolated without copying content into
            # logs; source remains in the encrypted Connector store for reconcile.
            rejected += 1
            _audit(db, action='event_quarantined', result='invalid_payload', ark_user_id=account.ark_user_id,
                   account_uid=account_uid, detail=f'sequence={last_sequence}')
            logger.warning('WhatsApp event quarantined: invalid normalized payload')
            print('[WhatsApp] event quarantined: invalid normalized payload', flush=True)
    # Recheck the employee at commit boundary, never a JWT snapshot. Locking the
    # account above serializes consent changes; an employee update is checked live.
    if not access.owner_enabled(db, account, fresh=True) or (account.session_generation, account.consent_version) != expected:
        raise PermissionError('批次提交前账号授权已失效')
    _upsert_account(db, metadata, account.ark_user_id)
    next_cursor = page.get('next_cursor')
    if next_cursor is not None and (not isinstance(next_cursor, str) or len(next_cursor) > 500):
        raise ValueError('Connector 游标不合法')
    cursor.cursor_value = next_cursor or cursor.cursor_value
    cursor.last_pulled_at = beijing_now()
    cursor.last_error = 'invalid_payload' if rejected else None
    account.last_sync_at = beijing_now()
    account.raw_payload = {**(account.raw_payload or {}), 'sync_state': 'gap' if rejected else ('catching_up' if page.get('has_more') else 'synced_available'), 'gap_reason': 'invalid_payload' if rejected else (account.raw_payload or {}).get('gap_reason')}
    _audit(db, action='pull_events', result='partial' if rejected else 'success', ark_user_id=account.ark_user_id,
           account_uid=account_uid, detail=f'messages={count},events={len(items)},quarantined={rejected}')
    return (conversations_count if resource == 'conversations' else count), cursor.cursor_value
