"""Verified provider identity only. Never match by text, time or nickname."""
import hashlib
import json

from app.whatsapp.models import WhatsAppConversation, WhatsAppMessage, WhatsAppMessageSource


def canonical_chat(account_uid: str, chat_id: str) -> tuple[str, str]:
    chat_id = str(chat_id)
    # PN domains are an exact protocol identity correspondence; LIDs remain LIDs.
    if chat_id.endswith('@s.whatsapp.net'):
        chat_id = chat_id.removesuffix('@s.whatsapp.net') + '@c.us'
    combined = f'{account_uid}:{chat_id}'
    uid = combined if len(combined) <= 120 else 'wa_conv_' + hashlib.sha256(combined.encode()).hexdigest()
    return uid, chat_id


def resolve_conversation(db, account_uid: str, payload: dict) -> dict:
    payload = dict(payload)
    uid, chat_id = canonical_chat(account_uid, payload.get('chat_id') or payload.get('source_jid') or '')
    existing = db.query(WhatsAppConversation).filter_by(account_uid=account_uid, chat_id=chat_id).first()
    payload.update(conversation_uid=existing.conversation_uid if existing else uid, chat_id=chat_id)
    return payload


def resolve_message(db, account_uid: str, payload: dict) -> dict:
    payload = dict(payload)
    key = payload.get('source_key')
    if not isinstance(key, dict) or not isinstance(key.get('remoteJid'), str) or not key['remoteJid'] or not isinstance(key.get('id'), str) or not key['id'] or type(key.get('fromMe')) is not bool:
        raise ValueError('Baileys 消息缺少完整来源身份')
    if key.get('participant') is not None and not isinstance(key['participant'], str):
        raise ValueError('群成员来源身份不合法')
    # The alternative PN/LID values are alias evidence, not part of the stable
    # identity: an alias learned later must not produce a second message.
    identity = {name: key.get(name) for name in ('remoteJid', 'id', 'fromMe', 'participant')}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    mapping = db.query(WhatsAppMessageSource).filter_by(
        account_uid=account_uid, provider='baileys', source_digest=digest,
    ).first()
    conv_uid, chat_id = canonical_chat(account_uid, key['remoteJid'])
    conversation = db.query(WhatsAppConversation).filter_by(account_uid=account_uid, chat_id=chat_id).first()
    payload['conversation_uid'] = conversation.conversation_uid if conversation else conv_uid
    if mapping is None:
        legacy_external = f"{str(key['fromMe']).lower()}_{chat_id}_{key['id']}"
        candidate = None
        # Old serialized group keys omit participant: cannot prove complete identity.
        if not key['remoteJid'].endswith(('@g.us', '@lid')) and not key.get('participant'):
            candidate = db.query(WhatsAppMessage).filter_by(account_uid=account_uid, external_message_id=legacy_external).first()
        mapping = WhatsAppMessageSource(
            account_uid=account_uid, provider='baileys', source_digest=digest,
            source_key=key, message_uid=candidate.message_uid if candidate else f'{account_uid}:bai_{digest}',
            match_state='exact' if candidate else ('unverified' if key['remoteJid'].endswith(('@g.us', '@lid')) else 'new'),
        )
        db.add(mapping)
        db.flush()
    payload['message_uid'] = mapping.message_uid
    message = db.query(WhatsAppMessage).filter_by(message_uid=mapping.message_uid, account_uid=account_uid).first()
    payload['external_message_id'] = message.external_message_id if message else f'bai_{digest}'
    payload['identity_state'] = mapping.match_state
    return payload
