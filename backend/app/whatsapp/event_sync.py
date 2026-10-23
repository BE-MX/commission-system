"""Commit normalized change batches and their checkpoint in one Ark transaction."""
import logging

from sqlalchemy.exc import DisconnectionError, OperationalError, SQLAlchemyError

from app.core.time import beijing_now
from app.whatsapp import access, identity
from app.whatsapp.connector_client import WhatsAppConnectorClient
from app.whatsapp.models import WhatsAppAccount, WhatsAppConversation, WhatsAppMessage, WhatsAppPullCursor

logger = logging.getLogger(__name__)


def pull_changes(db, account_uid: str, limit: int, resource: str = 'messages') -> tuple[int, str | None]:
    from app.whatsapp.service import _get_cursor, _upsert_account, _upsert_conversation, _upsert_message, _audit
    # The connector calls Ark back to lock/read this account's authorization.
    # Never hold that row lock while waiting for its HTTP response.
    account = db.query(WhatsAppAccount).filter_by(account_uid=account_uid).populate_existing().first()
    if account is None:
        raise LookupError('WhatsApp 账号不存在')
    if not access.owner_enabled(db, account):
        raise PermissionError('账号或员工已停止采集授权')
    expected = (account.session_generation, account.consent_version)
    expected_owner = account.ark_user_id
    checkpoint = db.query(WhatsAppPullCursor.cursor_value).filter_by(
        account_uid=account_uid, resource='events', scope_uid='global',
    ).first()
    fetched_cursor = checkpoint[0] if checkpoint else None
    page = WhatsAppConnectorClient().pull_changes(account_uid, fetched_cursor, limit)
    # Serialize only the apply phase: the cursor row (exclusive) orders concurrent pulls of
    # this account; the account row is share-locked so the connector's authorization callback
    # is not queued behind the batch, while consent changes (exclusive) still wait for commit.
    cursor = db.query(WhatsAppPullCursor).filter_by(
        account_uid=account_uid, resource='events', scope_uid='global',
    ).populate_existing().with_for_update().first()
    if (cursor.cursor_value if cursor else None) != fetched_cursor:
        raise ValueError('同步游标已变化，请重新同步')
    account = db.query(WhatsAppAccount).filter_by(account_uid=account_uid).populate_existing().with_for_update(read=True).first()
    if account is None or account.ark_user_id != expected_owner or (
        account.session_generation, account.consent_version
    ) != expected or not access.owner_enabled(db, account, fresh=True):
        raise PermissionError('批次应用前账号授权已失效')
    cursor = cursor or _get_cursor(db, account_uid, 'events', 'global')
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
    crm_failed = 0
    first_rejected = None
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
                        # CRM projection is derived data: its failure must not drop the source message.
                        try:
                            with db.begin_nested():
                                project_changed_message(db, account, msg)
                        except (OperationalError, DisconnectionError):
                            raise
                        except Exception as exc:
                            crm_failed += 1
                            logger.warning('WhatsApp CRM projection failed: %s', type(exc).__name__)
                            print(f'[WhatsApp] CRM projection failed: {type(exc).__name__}', flush=True)
                    count += 1
                elif event.get('kind') == 'account':
                    if str(payload.get('session_generation', expected[0])) != str(expected[0]) or str(payload.get('consent_version', expected[1])) != str(expected[1]):
                        raise PermissionError('变更账号授权已过期')
                else:
                    raise ValueError('不支持的 Connector 变更类型')
                db.flush()
        except PermissionError:
            raise  # Scope/consent violations reject the whole batch.
        except (OperationalError, DisconnectionError):
            raise  # Infrastructure failures retry the batch; never advance past them.
        except (ValueError, KeyError, TypeError, SQLAlchemyError) as exc:
            # Invalid or unstorable payloads are isolated without copying content into logs;
            # the source stays in the encrypted Connector store and can be replayed from
            # quarantine_from_sequence once the cause is fixed.
            rejected += 1
            first_rejected = first_rejected or last_sequence
            _audit(db, action='event_quarantined', result='invalid_payload', ark_user_id=account.ark_user_id,
                   account_uid=account_uid, detail=f'sequence={last_sequence},error={type(exc).__name__}')
            logger.warning('WhatsApp event quarantined: %s at sequence %s', type(exc).__name__, last_sequence)
            print(f'[WhatsApp] event quarantined: {type(exc).__name__} at sequence {last_sequence}', flush=True)
    # Recheck the employee at commit boundary, never a JWT snapshot. Locking the
    # account above serializes consent changes; an employee update is checked live.
    if not access.owner_enabled(db, account, fresh=True) or (account.session_generation, account.consent_version) != expected:
        raise PermissionError('批次提交前账号授权已失效')
    _upsert_account(db, metadata, account.ark_user_id, lock=False)
    next_cursor = page.get('next_cursor')
    if next_cursor is not None and (not isinstance(next_cursor, str) or len(next_cursor) > 500):
        raise ValueError('Connector 游标不合法')
    cursor.cursor_value = next_cursor or cursor.cursor_value
    cursor.last_pulled_at = beijing_now()
    cursor.last_error = 'invalid_payload' if rejected else None
    account.last_sync_at = beijing_now()
    previous = account.raw_payload or {}
    quarantine = previous.get('quarantine_from_sequence')
    if first_rejected and not quarantine:
        # Keep the earliest unreplayed sequence across batches.
        quarantine = first_rejected
    account.raw_payload = {**previous,
        'sync_state': 'gap' if quarantine else ('catching_up' if page.get('has_more') else 'synced_available'),
        'gap_reason': 'invalid_payload' if quarantine else (None if previous.get('gap_reason') == 'invalid_payload' else previous.get('gap_reason')),
        'quarantine_from_sequence': quarantine,
        'crm_projection_failed': int(previous.get('crm_projection_failed') or 0) + crm_failed}
    _audit(db, action='pull_events', result='partial' if rejected or crm_failed else 'success', ark_user_id=account.ark_user_id,
           account_uid=account_uid, detail=f'messages={count},events={len(items)},quarantined={rejected},crm_failed={crm_failed}')
    return (conversations_count if resource == 'conversations' else count), cursor.cursor_value


def replay_quarantined(db, account_uid: str, actor_user_id: int) -> int:
    """Rewind the event cursor to just before the earliest quarantined event.

    Upserts are revision-idempotent, so replaying already-applied events is safe; the next
    pulls re-read the retained Connector feed and re-attempt the quarantined items.
    """
    from app.whatsapp.service import _audit
    account = db.query(WhatsAppAccount).filter_by(account_uid=account_uid).populate_existing().with_for_update().first()
    if account is None:
        raise LookupError('WhatsApp 账号不存在')
    sequence = (account.raw_payload or {}).get('quarantine_from_sequence')
    if not isinstance(sequence, int) or sequence < 1:
        raise ValueError('该账号没有待重放的隔离事件')
    cursor = db.query(WhatsAppPullCursor).filter_by(
        account_uid=account_uid, resource='events', scope_uid='global',
    ).populate_existing().with_for_update().first()
    if cursor is None:
        raise ValueError('该账号尚未开始同步')
    cursor.cursor_value = str(sequence - 1)
    cursor.last_error = None
    account.raw_payload = {**(account.raw_payload or {}), 'quarantine_from_sequence': None,
                           'sync_state': 'catching_up', 'gap_reason': None}
    _audit(db, action='replay_quarantined', result='requested', ark_user_id=actor_user_id,
           account_uid=account_uid, detail=f'from_sequence={sequence}')
    return sequence
