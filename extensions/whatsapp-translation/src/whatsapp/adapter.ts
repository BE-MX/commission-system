import { createHistoryCollector } from './replyHistory'
import { detectChatKind } from '@/whatsapp/chatDetector'
import { parseIncomingMessages } from '@/whatsapp/messageParser'
import { WHATSAPP_SELECTORS } from '@/whatsapp/selectors'
import { ARK_MARKS } from '@/shared/marks'
import { collectReplyContext, MESSAGE_IDENTITY, maskContacts } from '@/whatsapp/replyContext'
import type { ReplyContextLimits } from '@/whatsapp/replyContext'

function normalizeComposerText(value: string): string {
  return value.replace(/\s+/gu, ' ').trim()
}

function composerText(node: Element | DocumentFragment): string {
  const copy = node.cloneNode(true) as Element | DocumentFragment
  for (const emoji of copy.querySelectorAll(WHATSAPP_SELECTORS.messageEmoji)) {
    emoji.replaceWith(node.ownerDocument!.createTextNode(emoji.getAttribute('data-plain-text') || emoji.getAttribute('alt') || ''))
  }
  return normalizeComposerText(copy.textContent ?? '')
}

export class WhatsAppAdapter {
  private writing = false
  private readonly history: ReturnType<typeof createHistoryCollector>
  constructor(private readonly root: Document | HTMLElement) { this.history = createHistoryCollector(root) }
  clearReplyHistory() { this.history.clear() }

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
    return composerText(composers[0])
  }
  conversationElement(): Element | null { return this.root.querySelector(WHATSAPP_SELECTORS.conversationTitle) }
  messageElements(): Element[] { return [...this.root.querySelectorAll(WHATSAPP_SELECTORS.message)] }

  composerElement(): Element | null { return this.root.querySelector(WHATSAPP_SELECTORS.composer) }
  hasToolbar(): boolean { return !!this.root.querySelector(`[${ARK_MARKS.toolbarHost}="1"]`) }
  private collectingHistory = false
  isCollectingHistory() { return this.collectingHistory }
  async collectReplyHistory(limits: ReplyContextLimits, current: () => boolean, progress: (context: ReturnType<typeof collectReplyContext>) => void) {
    if (this.collectingHistory) throw new Error('reply_history_busy')
    this.collectingHistory = true
    try { return await this.history.collect(limits, current, progress) }
    finally { this.collectingHistory = false }
  }
  collectReplyContext(limit: number = 2000, limits?: ReplyContextLimits) { return collectReplyContext(this.root, limit, limits) }

  /** Version observation excludes extension UI while retaining edits even when reverted. */
  isComposerMutation(record: MutationRecord): boolean {
    // Lexical changes presentation styles on blur (including opening our
    // details). That is not a draft edit; text/input and editability still count.
    if (record.type === 'attributes' && ['style', 'class'].includes(record.attributeName ?? '')) return false
    const composer = this.composerElement()
    return !!composer && (record.target === composer || composer.contains(record.target))
  }
  isMessageMutation(record: MutationRecord): boolean {
    const element = record.target.nodeType === 1 ? record.target as Element : record.target.parentElement
    if (!element || element.closest(`[${ARK_MARKS.translationHost}], [${ARK_MARKS.toolbarHost}]`)) return false
    const nodes = [...record.addedNodes, ...record.removedNodes]
    if (nodes.length && nodes.every(node => node.nodeType === 1 && (node as Element).matches(`[${ARK_MARKS.translationHost}], [${ARK_MARKS.toolbarHost}]`))) return false
    return !!element.closest(WHATSAPP_SELECTORS.message) || nodes.some(node => node.nodeType === 1 && (
      (node as Element).matches(WHATSAPP_SELECTORS.message) || !!(node as Element).querySelector(WHATSAPP_SELECTORS.message)
    ))
  }
  isWritingComposer(): boolean { return this.writing }

  async replaceComposer(text: string, isCurrent: () => boolean = () => true): Promise<boolean> {
    if (this.writing || !isCurrent()) return false
    this.writing = true
    try { return await this.writeComposer(text, isCurrent) }
    finally { this.writing = false }
  }

  private async writeComposer(text: string, isCurrent: () => boolean): Promise<boolean> {
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
    const belongsToComposer = (node: Node | null) => node === composer || (node !== null && composer.contains(node))

    const collapseFullSelection = () => {
      const anchor = selection.anchorNode
      const focus = selection.focusNode
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

    if (doc.activeElement !== composer) {
      composer.focus()
      // WhatsApp restores its saved caret after focus. Let that finish before
      // establishing the replacement selection, including keyboard activation.
      await new Promise<void>(resolve => view.requestAnimationFrame(() => resolve()))
      if (!composerContextIsCurrent() || this.readComposer() !== composerVersion || !isCurrent() || doc.activeElement !== composer) return false
    }
    const range = doc.createRange()
    range.selectNodeContents(composer)
    selection.removeAllRanges()
    selection.addRange(range)
    doc.dispatchEvent(new view.Event('selectionchange'))
    await new Promise<void>(resolve => view.requestAnimationFrame(() => resolve()))
    if (
      !composerContextIsCurrent() || this.readComposer() !== composerVersion || !isCurrent()
      || doc.activeElement !== composer || selection.rangeCount !== 1
      || !belongsToComposer(selection.anchorNode) || !belongsToComposer(selection.focusNode)
      || composerText(selection.getRangeAt(0).cloneContents()) !== composerVersion
    ) {
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

  autoSnapshot() {
    const context = this.collectReplyContext()
    const key = (m: typeof context.messages[number] | undefined) => m ? String((m as unknown as Record<symbol, string>)[MESSAGE_IDENTITY] ?? '') + JSON.stringify(m) : ''
    return { identity: [this.chatRootElement(), this.conversationElement(), this.chatTitle(), this.composerElement()],
      tail: key(context.messages.at(-1)), incoming: key(context.messages.filter(m => m.role === 'customer').at(-1)),
      role: context.messages.at(-1)?.role, draft: this.readComposer() }
  }
  isNativeSendTarget(target: EventTarget | null): boolean { return target instanceof Element && !!target.closest(WHATSAPP_SELECTORS.sendButton) }
  async sendAutomatic(text: string, current: () => boolean): Promise<boolean> {
    if (this.inspectChat().kind !== 'direct' || this.readComposer() || !current()) return false
    const snapshot = this.autoSnapshot()
    const same = () => current() && this.inspectChat().kind === 'direct' && !this.collectReplyContext().unrepresentedMessages
      && snapshot.identity.every((v, i) => this.autoSnapshot().identity[i] === v)
    if (!await this.replaceComposer(text, same)) return false
    // The editor commits before WhatsApp replaces its microphone with Send.
    // Wait for that render, rechecking cancellation, chat, tail and exact draft.
    let button: HTMLElement | undefined
    for (let i = 0; i <= 20; i++) {
      if (!same() || this.autoSnapshot().tail !== snapshot.tail || this.readComposer() !== normalizeComposerText(text)) return false
      const candidates = [...this.root.querySelectorAll<HTMLElement>(WHATSAPP_SELECTORS.sendButton)].filter(node => {
        const style = node.ownerDocument.defaultView?.getComputedStyle(node)
        return node.isConnected && !node.closest(WHATSAPP_SELECTORS.hiddenControl) && node.getClientRects().length
          && style?.visibility !== 'hidden' && style?.display !== 'none'
      })
      // Nested icon wrappers and their semantic button are one control.
      const buttons = candidates.filter(node => !candidates.some(other => other !== node && node.contains(other)))
      if (buttons.length > 1) throw new Error('reply_send_control_unavailable')
      const candidate = buttons[0]
      if (candidate?.isConnected && !candidate.closest(WHATSAPP_SELECTORS.disabledControl)) { button = candidate; break }
      if (i < 20) await new Promise<void>(resolve => setTimeout(resolve, 100))
    }
    if (!button) throw new Error('reply_send_control_unavailable')
    const previous = new Set(this.collectReplyContext().messages.map(m => String((m as unknown as Record<symbol, string>)[MESSAGE_IDENTITY])))
    button.click()
    // Never retry a click with an uncertain outcome. An outgoing bubble + cleared composer confirms local submission only.
    for (let i = 0; i < 20; i++) {
      await new Promise<void>(resolve => setTimeout(resolve, 250))
      if (!same()) return false
      const sent = this.collectReplyContext().messages.some(m => m.role === 'salesperson'
        && normalizeComposerText(m.text) === normalizeComposerText(maskContacts(text))
        && !previous.has(String((m as unknown as Record<symbol, string>)[MESSAGE_IDENTITY])))
      if (sent && !this.readComposer()) return true
    }
    return false
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
