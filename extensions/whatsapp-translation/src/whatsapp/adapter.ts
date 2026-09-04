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

  async replaceComposer(text: string, isCurrent: () => boolean = () => true): Promise<boolean> {
    if (this.inspectChat().kind !== 'direct') return false
    const composers = this.root.querySelectorAll(WHATSAPP_SELECTORS.composer)
    if (composers.length !== 1) return false

    const composer = composers[0] as HTMLElement
    const doc = composer.ownerDocument
    const view = doc.defaultView
    const selection = view?.getSelection()
    if (!view || !selection || !view.InputEvent) return false
    const chatRoot = this.chatRootElement()
    const chatTitle = this.chatTitle()
    const composerVersion = this.readComposer()

    const collapseFullSelection = () => {
      const anchor = selection.anchorNode
      const focus = selection.focusNode
      const belongsToComposer = (node: Node | null) => node === composer || (node !== null && composer.contains(node))
      if (selection.isCollapsed || !composer.isConnected || !belongsToComposer(anchor) || !belongsToComposer(focus)) return
      const caret = doc.createRange()
      caret.selectNodeContents(composer)
      caret.collapse(false)
      selection.removeAllRanges()
      selection.addRange(caret)
    }

    const composerContextIsCurrent = () => {
      const current = this.root.querySelectorAll(WHATSAPP_SELECTORS.composer)
      return current.length === 1
        && current[0] === composer
        && composer.isConnected
        && this.chatRootElement() === chatRoot
        && this.chatTitle() === chatTitle
    }

    composer.focus()
    const range = doc.createRange()
    range.selectNodeContents(composer)
    selection.removeAllRanges()
    selection.addRange(range)
    doc.dispatchEvent(new view.Event('selectionchange'))
    await new Promise<void>(resolve => view.requestAnimationFrame(() => resolve()))
    if (!composerContextIsCurrent() || this.readComposer() !== composerVersion || !isCurrent()) {
      collapseFullSelection()
      return false
    }

    try {
      composer.dispatchEvent(new view.InputEvent('beforeinput', {
        bubbles: true,
        cancelable: true,
        data: text,
        inputType: 'insertText',
      }))
    } catch {
      collapseFullSelection()
      return false
    }
    await Promise.resolve()
    const replaced = composerContextIsCurrent()
      && isCurrent()
      && this.readComposer() === normalizeComposerText(text)
    if (!replaced) collapseFullSelection()
    return replaced
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
