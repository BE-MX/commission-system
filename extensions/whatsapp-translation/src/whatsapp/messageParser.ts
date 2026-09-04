import { ARK_MARKS } from '@/shared/marks'
import { WHATSAPP_SELECTORS } from '@/whatsapp/selectors'

export type ParsedMessage = {
  element: Element
  localKey: string
  text: string
}

const TEXT_MESSAGE_TEST_IDS = new Set([
  'addon-bubble-container',
  'forwarded',
  'msg-meta',
  'reaction-bubble',
  'reaction-bubble-item',
  'selectable-text',
  'tail-in',
  'tail-out',
])

/** Hosts in these states are settled; only errors get rescanned. */
const SETTLED_STATES = new Set(['loading', 'success'])

async function localMessageKey(direction: string, text: string, ordinal: number): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${direction}:${text}:${ordinal}`))
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('')
}

function normalizeText(element: Element): string {
  const text = element.cloneNode(true) as Element
  for (const emoji of text.querySelectorAll(WHATSAPP_SELECTORS.messageEmoji)) {
    emoji.replaceWith(element.ownerDocument.createTextNode(emoji.getAttribute('data-plain-text') || emoji.getAttribute('alt') || ''))
  }
  for (const lineBreak of text.querySelectorAll('br')) lineBreak.replaceWith(element.ownerDocument.createTextNode(' '))
  return text.textContent?.replace(/\s+/gu, ' ').trim() ?? ''
}

function isNeutralLayout(element: Element): boolean {
  if (!['DIV', 'SPAN'].includes(element.tagName) || element.hasAttribute('role')) return false
  const background = element.ownerDocument.defaultView?.getComputedStyle(element).backgroundImage
  return !background || background === 'none'
}

function hiddenTimeDecorations(message: Element, textRoot: Element, metadata: Element): Element[] {
  const visibleTimes = message.querySelectorAll(WHATSAPP_SELECTORS.messageTime)
  if (visibleTimes.length !== 1) return []
  const time = visibleTimes[0].textContent?.trim() ?? ''
  if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/u.test(time)) return []
  return [...metadata.querySelectorAll(WHATSAPP_SELECTORS.messageHiddenTime)].filter(element => (
    !textRoot.contains(element)
    && element.textContent?.trim() === time
    && [element, ...element.querySelectorAll('*')].every(node => (
      node.tagName === 'SPAN' && !node.hasAttribute('data-testid') && isNeutralLayout(node)
    ))
  ))
}

function hasOnlyTextMessageStructure(message: Element, textRoot: Element, metadata: Element): boolean {
  const decorations = [
    ...message.querySelectorAll(WHATSAPP_SELECTORS.messageDecoration),
    ...hiddenTimeDecorations(message, textRoot, metadata),
  ]
  const structureRoots = [textRoot, metadata, ...decorations]
  return [...message.querySelectorAll('*')].every((element) => {
    const translationHost = element.closest(`[${ARK_MARKS.translationHost}="1"]`)
    if (translationHost && message.contains(translationHost)) return true
    const tag = element.tagName.toUpperCase()
    if (tag === 'IMG') return textRoot.contains(element) && element.matches(WHATSAPP_SELECTORS.messageEmoji)
    if (['AUDIO', 'VIDEO', 'CANVAS', 'IFRAME', 'OBJECT', 'EMBED'].includes(tag)) return false
    const testId = element.getAttribute('data-testid')
    if (testId !== null) return TEXT_MESSAGE_TEST_IDS.has(testId)
    if (textRoot.contains(element)) return ['A', 'B', 'BR', 'CODE', 'EM', 'I', 'S', 'SPAN', 'STRONG'].includes(tag)
    if (decorations.some(root => root.contains(element))) return ['DIV', 'SPAN', 'SVG', 'TITLE', 'PATH'].includes(tag)
    // Empty DIV/SPAN placeholders carry no message content. Nonempty wrappers
    // must connect recognized parts without introducing standalone text.
    return isNeutralLayout(element)
      && (!element.textContent?.trim() || (
        structureRoots.some(root => element === root || element.contains(root))
        && [...element.childNodes].every(node => node.nodeType !== 3 || !node.textContent?.trim())
      ))
  })
}

function isIncomingMessage(message: Element): boolean {
  const row = message.parentElement
  const view = message.ownerDocument.defaultView
  return row !== null && view?.getComputedStyle(row).alignItems === 'flex-start'
}

function isAlreadyHandled(message: Element): boolean {
  const host = message.querySelector(`:scope > [${ARK_MARKS.translationHost}="1"]`)
  if (!host) return false
  return SETTLED_STATES.has(host.getAttribute(ARK_MARKS.translationState) ?? '')
}

export async function parseIncomingMessages(root: Document | HTMLElement): Promise<ParsedMessage[]> {
  const messages = root.querySelectorAll(WHATSAPP_SELECTORS.message)
  const parsed: ParsedMessage[] = []

  for (let ordinal = 0; ordinal < messages.length; ordinal += 1) {
    const element = messages[ordinal]
    if (!isIncomingMessage(element)) continue
    if (isAlreadyHandled(element)) continue
    const textElements = element.querySelectorAll(WHATSAPP_SELECTORS.messageText)
    if (textElements.length !== 1) continue
    const metadata = element.querySelector(WHATSAPP_SELECTORS.messageMetadata)
    if (!metadata?.contains(textElements[0])) continue
    if (!hasOnlyTextMessageStructure(element, textElements[0], metadata)) continue

    const text = normalizeText(textElements[0])
    if (!text) continue

    parsed.push({
      element,
      localKey: await localMessageKey('incoming', text, ordinal),
      text,
    })
  }

  return parsed
}
