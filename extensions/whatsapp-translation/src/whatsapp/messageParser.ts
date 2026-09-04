import { ARK_MARKS } from '@/shared/marks'
import { WHATSAPP_SELECTORS } from '@/whatsapp/selectors'

export type ParsedMessage = {
  element: Element
  localKey: string
  text: string
}

const TEXT_MESSAGE_TEST_IDS = new Set([
  'addon-bubble-container',
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
  return element.textContent?.replace(/\s+/gu, ' ').trim() ?? ''
}

function hasOnlyTextMessageStructure(message: Element): boolean {
  return [...message.querySelectorAll('[data-testid]')].every((element) => {
    const testId = element.getAttribute('data-testid')
    return testId !== null && TEXT_MESSAGE_TEST_IDS.has(testId)
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
    if (!element.querySelector(WHATSAPP_SELECTORS.messageMetadata)) continue
    if (!hasOnlyTextMessageStructure(element)) continue

    const textElements = element.querySelectorAll(WHATSAPP_SELECTORS.messageText)
    if (textElements.length !== 1) continue

    const text = normalizeText(textElements[0])
    if (!text) continue

    parsed.push({
      element,
      localKey: await localMessageKey('incoming', text, parsed.length),
      text,
    })
  }

  return parsed
}
