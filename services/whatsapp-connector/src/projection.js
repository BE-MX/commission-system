import { createHash } from 'node:crypto'
import { proto } from 'baileys'
import { error } from './crypto.js'

export const hash = (...parts) => createHash('sha256').update(JSON.stringify(parts)).digest('hex')
export const conversationId = (account, jid) => `wa_c_${hash(account, jid)}`
export const messageId = (account, key) => `wa_m_${hash(account, key.remoteJid, key.id, Boolean(key.fromMe), key.participant || '')}`
export function phone(jid) {
  const match = String(jid || '').match(/^(\d{6,15})(?::\d+)?@(s\.whatsapp\.net|c\.us)$/)
  return match ? `+${match[1]}` : null
}
function sourceKey(key) {
  if (!key?.remoteJid || !key.id) throw error('invalid_message_key')
  for (const value of Object.values(key)) if (typeof value === 'string' && value.length > 255) throw error('message_key_size_limit')
  return { fromMe: Boolean(key.fromMe), ...Object.fromEntries(['remoteJid', 'id', 'fromMe', 'participant', 'remoteJidAlt', 'participantAlt',
    'remoteJidUsername', 'participantUsername', 'server_id', 'addressingMode', 'isViewOnce']
    .filter(name => key[name] !== undefined && key[name] !== null).map(name => [name, name === 'fromMe' ? Boolean(key[name]) : key[name]])) }
}
function sentAt(timestamp) {
  const seconds = Number(timestamp)
  return Number.isFinite(seconds) && seconds > 0 && seconds < 8640000000000 ? new Date(seconds * 1000).toISOString() : null
}
function content(raw) {
  let message = raw
  for (let depth = 0; depth < 6; depth++) {
    if (message?.ephemeralMessage?.message) message = message.ephemeralMessage.message
    else if (message?.documentWithCaptionMessage?.message) message = message.documentWithCaptionMessage.message
    else if (message?.editedMessage?.message) message = message.editedMessage.message
    else break
  }
  if (typeof message?.conversation === 'string') return { content_type: 'text', content_text: message.conversation, attachments: [] }
  if (message?.extendedTextMessage?.text !== undefined) return { content_type: 'text', content_text: message.extendedTextMessage.text, attachments: [] }
  for (const [name, type] of [['imageMessage', 'image'], ['videoMessage', 'video'], ['audioMessage', 'audio'],
    ['documentMessage', 'document'], ['stickerMessage', 'sticker']]) {
    const media = message?.[name]
    if (media) return { content_type: type, content_text: media.caption || '', attachments: [{ mime_type: media.mimetype || null,
      file_name: media.fileName || null, media_state: 'metadata_only' }] }
  }
  return { content_type: 'unsupported', content_text: '[Unsupported WhatsApp message]', attachments: [] }
}
export class Projector {
  constructor(store) { this.store = store }
  ingest(lease, kind, event, eventId, bytes) {
    return this.store.ingest(lease, kind, () => {
      if (kind === 'messages.upsert') for (const message of event.messages || []) this.message(lease, message,
        { live: event.type === 'notify', history: event.type === 'append' })
      else if (kind === 'messaging-history.set') {
        for (const contact of event.contacts || []) this.contact(lease, contact)
        for (const chat of event.chats || []) this.chat(lease, chat)
        for (const message of event.messages || []) this.message(lease, message, { history: true })
        this.coverage(lease, { history_state: 'partial', history_batch_complete: Boolean(event.isLatest),
          history_progress: event.progress ?? null })
      } else if (kind === 'messaging-history.status') this.coverage(lease, {
        history_state: event.status === 'paused' ? 'stalled' : 'partial',
        history_batch_complete: event.status === 'complete', history_completion_explicit: Boolean(event.explicit),
      })
      else if (['chats.upsert', 'chats.update'].includes(kind)) for (const chat of event) this.chat(lease, chat)
      else if (kind === 'chats.delete') for (const jid of event) {
        this.chat(lease, { id: jid }, { deleted: true })
        for (const message of this.store.iterEntities(lease.uid, 'message', hash(jid))) this.deleteMessage(lease, message.source_key)
      } else if (['contacts.upsert', 'contacts.update'].includes(kind)) for (const contact of event) this.contact(lease, contact)
      else if (kind === 'messages.update') for (const item of event) this.updateMessage(lease, item)
      else if (kind === 'messages.delete') {
        if (event.all) {
          for (const message of this.store.iterEntities(lease.uid, 'message', hash(event.jid))) this.deleteMessage(lease, message.source_key)
          // Prevent delayed history repopulating the explicitly deleted chat.
          this.chat(lease, { id: event.jid }, { deleted: true })
        } else for (const key of event.keys || []) this.deleteMessage(lease, key)
      }
      this.coverage(lease, {}, true)
    }, eventId, bytes)
  }
  coverage(lease, patch = {}, ingestion = false, timestamp = null) {
    const account = this.store.account(lease.uid)
    const coverage = { ...account.coverage, ...patch.coverage }
    if (ingestion) coverage.last_ingest_at = new Date().toISOString()
    if (timestamp) {
      if (!coverage.earliest_message_at || timestamp < coverage.earliest_message_at) coverage.earliest_message_at = timestamp
      if (!coverage.latest_message_at || timestamp > coverage.latest_message_at) coverage.latest_message_at = timestamp
    }
    Object.assign(account, patch, { coverage, last_sync_at: coverage.last_ingest_at, last_message_at: coverage.latest_message_at })
    this.store.writeAccount(account)
    this.store.change(lease, 'account', lease.uid)
  }
  contact(lease, contact) {
    if (!contact.id) throw error('invalid_contact_key')
    const id = hash(contact.id)
    const previous = this.store.entity(lease.uid, 'contact', id) || {}
    this.store.putEntity(lease, 'contact', id, { ...previous, ...contact }, {}, true)
    const existing = this.store.entity(lease.uid, 'conversation', conversationId(lease.uid, contact.id))
    if (existing) this.chat(lease, { id: contact.id, name: contact.name || contact.notify || contact.verifiedName })
  }
  chat(lease, chat, { deleted = false, live = false } = {}) {
    if (!chat?.id) throw error('invalid_chat_key')
    const id = conversationId(lease.uid, chat.id)
    const previous = this.store.entity(lease.uid, 'conversation', id) || {}
    const contact = this.store.entity(lease.uid, 'contact', hash(chat.id))
    const value = { ...previous, conversation_uid: id, chat_id: chat.id, source_jid: chat.id,
      contact_phone: phone(chat.id) || phone(contact?.phoneNumber), contact_name: chat.name || contact?.name || contact?.notify || previous.contact_name || null,
      is_group: chat.id.endsWith('@g.us'), last_message_at: previous.last_message_at || sentAt(chat.conversationTimestamp),
      last_message_preview: previous.last_message_preview || '', is_deleted: deleted || (previous.is_deleted && !live) || false,
      history_blocked: deleted || previous.history_blocked || false,
      history_resume_after: deleted ? null : previous.history_resume_after || null }
    delete value.source_revision
    if (value.is_deleted) { value.last_message_preview = ''; value.deleted_at = previous.deleted_at || new Date().toISOString() }
    else if (live && previous.is_deleted) {
      value.deleted_at = null; value.last_message_at = null; value.last_message_uid = null
    }
    this.store.putEntity(lease, 'conversation', id, value, { chat: hash(chat.id), reopen: live })
    return value
  }
  message(lease, raw, { history = false, edited = false, live = false } = {}) {
    const key = sourceKey(raw.key)
    const protocol = raw.message?.protocolMessage
    if (protocol?.type === proto.Message.ProtocolMessage.Type.REVOKE && protocol.key) {
      return this.deleteMessage(lease, { ...protocol.key, remoteJid: protocol.key.remoteJid || key.remoteJid })
    }
    if (protocol?.type === proto.Message.ProtocolMessage.Type.MESSAGE_EDIT && protocol.key && protocol.editedMessage) {
      return this.updateMessage(lease, { key: { ...protocol.key, remoteJid: protocol.key.remoteJid || key.remoteJid,
        participant: protocol.key.participant || key.participant },
        update: { message: protocol.editedMessage, messageTimestamp: raw.messageTimestamp } })
    }
    const id = messageId(lease.uid, key)
    const previous = this.store.entity(lease.uid, 'message', id)
    const tombstones = this.store.findMessages(lease, { chat: hash(key.remoteJid), externalId: hash(key.id), fromMe: key.fromMe })
    if (previous?.is_deleted || tombstones.some(item => item.is_deleted && !item.source_key.participant)
      || (!edited && previous?.is_edited)) return
    const timestamp = previous?.sent_at || sentAt(raw.messageTimestamp)
    const conversation = this.chat(lease, { id: key.remoteJid }, { live })
    if (conversation.is_deleted) {
      this.coverage(lease, { coverage: { gap_reason: 'deleted_chat_history_ambiguous' } })
      return
    }
    if (conversation.history_blocked && !previous && !live && (edited || !timestamp
      || !conversation.history_resume_after || timestamp <= conversation.history_resume_after)) {
      this.coverage(lease, { coverage: { gap_reason: 'deleted_chat_history_ambiguous' } })
      return
    }
    if (live && conversation.history_blocked && !conversation.history_resume_after) {
      conversation.history_resume_after = timestamp
      if (!timestamp) this.coverage(lease, { coverage: { gap_reason: 'deleted_chat_history_ambiguous' } })
    }
    const sender = key.participant || (key.fromMe ? this.store.account(lease.uid).self_jid : key.remoteJid) || null
    const senderAlt = key.participantAlt || (!key.fromMe ? key.remoteJidAlt : null)
    const mapped = content(raw.message)
    if (mapped.content_text.length > 65536) throw error('message_size_limit')
    const value = { ...previous, message_uid: id, conversation_uid: conversation.conversation_uid,
      external_message_id: key.id, source_key: { ...previous?.source_key, ...key }, direction: key.fromMe ? 'outbound' : 'inbound',
      sender_wa_id: sender, sender_phone: phone(sender) || phone(senderAlt), sender_name: raw.pushName || previous?.sender_name || null,
      ...mapped, content_preview: mapped.content_text.slice(0, 500), sent_at: timestamp,
      is_deleted: false, deleted_at: null, is_edited: edited || previous?.is_edited || false }
    delete value.source_revision
    this.store.putEntity(lease, 'message', id, value, { chat: hash(key.remoteJid), externalId: hash(key.id),
      fromMe: key.fromMe, participant: key.participant && hash(key.participant) })
    if (!conversation.last_message_at || !timestamp || timestamp >= conversation.last_message_at) {
      this.store.putEntity(lease, 'conversation', conversation.conversation_uid, { ...conversation,
        last_message_at: timestamp || conversation.last_message_at, last_message_preview: value.content_preview,
        last_message_uid: id }, { chat: hash(key.remoteJid) })
    }
    this.coverage(lease, {}, false, timestamp)
  }
  updateMessage(lease, { key, update }) {
    if (update.message === null || update.messageStubType === proto.WebMessageInfo.StubType.REVOKE) return this.deleteMessage(lease, key)
    if (!update.message) return
    const matches = this.store.findMessages(lease, { chat: hash(key.remoteJid), externalId: hash(key.id),
      fromMe: key.fromMe, participant: key.participant })
    if (matches.length) for (const previous of matches) this.message(lease,
      { key: { ...previous.source_key, ...key }, message: update.message, messageTimestamp: update.messageTimestamp }, { edited: true })
    else this.message(lease, { key, ...update }, { edited: true })
  }
  deleteMessage(lease, rawKey) {
    const key = sourceKey(rawKey)
    this.chat(lease, { id: key.remoteJid })
    const matches = this.store.findMessages(lease, { chat: hash(key.remoteJid), externalId: hash(key.id),
      fromMe: key.fromMe, participant: key.participant })
    // Even when history has not arrived yet, retain a bodyless tombstone.
    if (!matches.length) matches.push({ message_uid: messageId(lease.uid, key), source_key: key,
      conversation_uid: conversationId(lease.uid, key.remoteJid), external_message_id: key.id,
      direction: key.fromMe ? 'outbound' : 'inbound', sent_at: null })
    for (const old of matches) {
      const value = { ...old, is_deleted: true, deleted_at: old.deleted_at || new Date().toISOString(),
        content_text: '', content_preview: '', content_type: 'revoked', attachments: [] }
      delete value.source_revision
      this.store.putEntity(lease, 'message', old.message_uid, value, { chat: hash(key.remoteJid),
        externalId: hash(key.id), fromMe: key.fromMe, participant: key.participant && hash(key.participant) })
      const conv = this.store.entity(lease.uid, 'conversation', old.conversation_uid)
      if (conv?.last_message_uid === old.message_uid) {
        delete conv.source_revision
        this.store.putEntity(lease, 'conversation', old.conversation_uid, { ...conv, last_message_preview: '' }, { chat: hash(key.remoteJid) })
      }
    }
  }
}
