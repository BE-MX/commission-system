import { WHATSAPP_SELECTORS } from '@/whatsapp/selectors'

export type ParsedMessage = {
  element: Element
  localKey: string
  text: string
}

async function localMessageKey(direction: string, text: string, ordinal: number): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${direction}:${text}:${ordinal}`))
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('')
}

function normalizeText(element: Element): string {
  return element.textContent?.replace(/\s+/gu, ' ').trim() ?? ''
}

function isEligibleMessage(message: Element): boolean {
  const hasSelector = (selector: string): boolean =>
    message.matches(selector) || message.querySelector(selector) !== null

  return !hasSelector(WHATSAPP_SELECTORS.mediaMessage)
    && !hasSelector(WHATSAPP_SELECTORS.systemMessage)
    && !hasSelector(WHATSAPP_SELECTORS.revokedMessage)
}

export async function parseIncomingMessages(root: Document | HTMLElement): Promise<ParsedMessage[]> {
  const messages = root.querySelectorAll(WHATSAPP_SELECTORS.incomingMessage)
  const parsed: ParsedMessage[] = []

  for (let ordinal = 0; ordinal < messages.length; ordinal += 1) {
    const element = messages[ordinal]
    if (!isEligibleMessage(element)) continue

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
