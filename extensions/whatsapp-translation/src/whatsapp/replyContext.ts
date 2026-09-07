import { detectChatKind } from '@/whatsapp/chatDetector'
import { hasOnlyTextMessageStructure } from '@/whatsapp/messageParser'
import { WHATSAPP_SELECTORS } from '@/whatsapp/selectors'
import { ARK_MARKS } from '@/shared/marks'
import type { ReplyRequest } from '@/shared/contracts'

/** Mask contacts conservatively, preserving short dimensions and quantities. */
export function maskContacts(text: string): string {
  return text.replace(/[\w.+-]+@[\w.-]+\.[a-z]{2,}/giu, '[email]')
    .replace(/(?<![\w.+])(?:\+\d[\d ()-]{7,}\d|\d{10,15}|\(?\d{3}\)?[ -]\d{3}[ -]\d{4})(?![\w])/gu, value => {
      const count = value.replace(/\D/gu, '').length
      return count >= 10 && count <= 15 ? '[phone]' : value
    })
}
export type ReplyContext = {
  messages: ReplyRequest['messages']
  context_scope: ReplyRequest['context_scope']
  loadedCount: number
  skippedUnknown: boolean
  range: string
}
export type ReplyContextLimits = { maxMessages: number; maxChars: number }

/** Reply context retains list/paragraph boundaries; translation keeps its existing single-line normalization. */
function replyMessageText(element: Element): string {
  const plain = element.cloneNode(true) as Element
  for (const emoji of plain.querySelectorAll(WHATSAPP_SELECTORS.messageEmoji)) {
    emoji.replaceWith(element.ownerDocument.createTextNode(emoji.getAttribute('data-plain-text') || emoji.getAttribute('alt') || ''))
  }
  function read(node: Node): string {
    if (node.nodeType === 3) return node.textContent ?? ''
    if (node.nodeType !== 1) return ''
    const tag = (node as Element).tagName
    if (tag === 'BR') return '\n'
    const children = [...node.childNodes].map(read).join('')
    return ['P', 'DIV'].includes(tag) ? `\n${children}\n` : children
  }
  return read(plain).replace(/\r\n?/gu, '\n').split('\n')
    .map(line => line.replace(/[^\S\n]+/gu, ' ').trim()).join('\n').replace(/\n{3,}/gu, '\n\n').trim()
}

export function collectReplyContext(root: Document | HTMLElement, limit: 20 | 40 = 20, limits: ReplyContextLimits = { maxMessages: 40, maxChars: 12000 }): ReplyContext {
  if (!Number.isInteger(limits.maxMessages) || limits.maxMessages < 1 || !Number.isInteger(limits.maxChars) || limits.maxChars < 1) throw new Error('reply_configuration_invalid')
  const maxMessages = Math.min(limit, 40, limits.maxMessages)
  const maxChars = Math.min(12000, limits.maxChars)
  if (detectChatKind(root).kind !== 'direct') throw new Error('chat_unsupported')
  const rows = [...root.querySelectorAll(WHATSAPP_SELECTORS.message)]
  const parsed: { role: 'customer' | 'salesperson'; text: string; cost: number }[] = []
  let omittedMedia = false
  let skippedUnknown = false
  for (const row of rows) {
    if (row.closest(`[${ARK_MARKS.translationHost}], [${ARK_MARKS.toolbarHost}]`)) continue
    const align = row.parentElement && row.ownerDocument.defaultView?.getComputedStyle(row.parentElement).alignItems
    if (align !== 'flex-start' && align !== 'flex-end') { skippedUnknown = true; continue }
    const clean = row.cloneNode(true) as Element
    clean.querySelectorAll(`[${ARK_MARKS.translationHost}], [${ARK_MARKS.toolbarHost}], ${WHATSAPP_SELECTORS.quotedMessage}`).forEach(node => node.remove())
    if (clean.querySelector(WHATSAPP_SELECTORS.systemNotice)) continue
    if (clean.querySelector(WHATSAPP_SELECTORS.mediaMessage)) { omittedMedia = true; continue }
    const texts = clean.querySelectorAll(WHATSAPP_SELECTORS.messageText)
    const metadata = clean.querySelector(WHATSAPP_SELECTORS.messageMetadata)
    if (texts.length !== 1 || !metadata?.contains(texts[0]) || !hasOnlyTextMessageStructure(clean, texts[0], metadata, { allowParagraphs: true })) {
      skippedUnknown = true
      continue
    }
    const text = replyMessageText(texts[0])
    if (text) {
      const masked = maskContacts(text)
      parsed.push({ role: align === 'flex-start' ? 'customer' : 'salesperson', text: masked, cost: Math.max(text.length, masked.length) })
    }
  }
  let size = 0
  const kept: typeof parsed = []
  for (const message of parsed.slice(-maxMessages).reverse()) {
    if (size + message.cost > maxChars) {
      if (!kept.length) throw new Error('reply_latest_too_long')
      break
    }
    size += message.cost
    kept.unshift(message)
  }
  return {
    messages: kept.map(({ role, text }) => ({ role, text })),
    context_scope: { requested_limit: limit, truncated: kept.length < parsed.length, omitted_media: omittedMedia, latest_visible: false },
    loadedCount: parsed.length,
    skippedUnknown,
    range: kept.length ? `已加载文本第 ${parsed.indexOf(kept[0]) + 1}–${parsed.indexOf(kept[kept.length - 1]) + 1} 条` : '无可用文本',
  }
}
