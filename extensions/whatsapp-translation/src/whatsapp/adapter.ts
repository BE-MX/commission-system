import { detectChatKind } from '@/whatsapp/chatDetector'
import { parseIncomingMessages } from '@/whatsapp/messageParser'
import { WHATSAPP_SELECTORS } from '@/whatsapp/selectors'
import { ARK_MARKS } from '@/shared/marks'

function normalizeComposerText(value: string): string {
  return value.replace(/\s+/gu, ' ').trim()
}

export class WhatsAppAdapter {
  constructor(private readonly root: Document | HTMLElement) {}

  inspectChat() {
    return detectChatKind(this.root)
  }

  chatRootElement(): Element | null {
    return this.root.querySelector(WHATSAPP_SELECTORS.chatRoot)
  }

  /** Normalized title; only ever hashed with a per-device salt before storage. */
  chatTitle(): string {
    if (this.inspectChat().kind !== 'direct') return ''
    return this.root.querySelector(WHATSAPP_SELECTORS.conversationTitle)?.textContent?.replace(/\s+/gu, ' ').trim() ?? ''
  }

  isDarkTheme(): boolean {
    const doc = 'defaultView' in this.root ? (this.root as Document) : this.root.ownerDocument
    if (doc.querySelector(WHATSAPP_SELECTORS.darkTheme)) return true
    return doc.defaultView?.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
  }

  async listUntranslatedIncomingMessages() {
    if (this.inspectChat().kind !== 'direct') return []
    return parseIncomingMessages(this.root)
  }

  readComposer(): string {
    if (this.inspectChat().kind !== 'direct') return ''
    const composers = this.root.querySelectorAll(WHATSAPP_SELECTORS.composer)
    if (composers.length !== 1) return ''
    return normalizeComposerText(composers[0].textContent ?? '')
  }

  async replaceComposer(text: string): Promise<boolean> {
    if (this.inspectChat().kind !== 'direct') return false
    const composers = this.root.querySelectorAll(WHATSAPP_SELECTORS.composer)
    if (composers.length !== 1) return false

    const composer = composers[0] as HTMLElement
    const doc = composer.ownerDocument
    const selection = doc.defaultView?.getSelection()
    if (!selection || typeof doc.execCommand !== 'function') return false

    composer.focus()
    const range = doc.createRange()
    range.selectNodeContents(composer)
    selection.removeAllRanges()
    selection.addRange(range)
    try {
      if (!doc.execCommand('insertText', false, text)) return false
    } finally {
      selection.removeAllRanges()
    }
    await Promise.resolve()
    return this.readComposer() === normalizeComposerText(text)
  }

  /**
   * Mount a closed shadow host as the first child of the WhatsApp footer so the
   * toolbar occupies its own row above the compose line instead of sitting inside
   * WhatsApp's flex row. Returns the shadow root to render into, or null when the
   * current chat is unsupported (any stale host is removed).
   */
  mountComposerToolbar(): ShadowRoot | null {
    for (const existing of [...this.root.querySelectorAll(`[${ARK_MARKS.toolbarHost}="1"]`)]) existing.remove()
    if (this.inspectChat().kind !== 'direct') return null
    const footer = this.root.querySelector(WHATSAPP_SELECTORS.footer)
    if (!footer) return null
    const host = footer.ownerDocument.createElement('div')
    host.setAttribute(ARK_MARKS.toolbarHost, '1')
    host.style.display = 'block'
    const shadow = host.attachShadow({ mode: 'closed' })
    footer.prepend(host)
    return shadow
  }
}

export function adapterFor(root: Document | HTMLElement): WhatsAppAdapter {
  return new WhatsAppAdapter(root)
}
