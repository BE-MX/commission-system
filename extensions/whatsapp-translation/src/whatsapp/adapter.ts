import { detectChatKind } from '@/whatsapp/chatDetector'
import { parseIncomingMessages } from '@/whatsapp/messageParser'
import { WHATSAPP_SELECTORS } from '@/whatsapp/selectors'

export async function runOutgoingTranslation(
  button: HTMLButtonElement,
  onTranslate: () => void | Promise<void>,
): Promise<void> {
  button.disabled = true
  button.textContent = '翻译中…'
  try {
    await onTranslate()
    button.textContent = '翻译'
  } catch {
    button.textContent = '翻译失败，重试'
  } finally {
    button.disabled = false
  }
}

export class WhatsAppAdapter {
  constructor(private readonly root: Document | HTMLElement) {}

  inspectChat() {
    return detectChatKind(this.root)
  }

  chatRootElement(): Element | null {
    return this.root.querySelector(WHATSAPP_SELECTORS.chatRoot)
  }

  async listUntranslatedIncomingMessages() {
    if (this.inspectChat().kind !== 'direct') return []
    return parseIncomingMessages(this.root)
  }

  readComposer(): string {
    if (this.inspectChat().kind !== 'direct') return ''
    const composers = this.root.querySelectorAll(WHATSAPP_SELECTORS.composer)
    if (composers.length !== 1) return ''
    return composers[0].textContent?.replace(/\s+/gu, ' ').trim() ?? ''
  }

  async replaceComposer(text: string): Promise<boolean> {
    if (this.inspectChat().kind !== 'direct') return false
    const composers = this.root.querySelectorAll(WHATSAPP_SELECTORS.composer)
    if (composers.length !== 1) return false

    const composer = composers[0]
    const eventInit = {
      bubbles: true,
      cancelable: true,
      data: text,
      inputType: 'insertText',
    }
    const inputEventConstructor = composer.ownerDocument.defaultView?.InputEvent ?? composer.ownerDocument.defaultView?.Event
    if (!inputEventConstructor) return false
    composer.dispatchEvent(new inputEventConstructor('beforeinput', eventInit))
    composer.textContent = text
    composer.dispatchEvent(new inputEventConstructor('input', eventInit))
    return true
  }

  attachOutgoingControl(onTranslate: () => void | Promise<void>): HTMLElement | null {
    for (const existing of [...this.root.querySelectorAll('[data-ark-outgoing-control="1"]')]) existing.remove()
    if (this.inspectChat().kind !== 'direct') return null
    const composer = this.root.querySelector(WHATSAPP_SELECTORS.composer)
    if (composer?.parentElement == null) return null
    const host = composer.ownerDocument.createElement('div')
    host.dataset.arkOutgoingControl = '1'
    const shadow = host.attachShadow({ mode: 'closed' })
    const style = composer.ownerDocument.createElement('style')
    style.textContent = `
      :host { all: initial; }
      button { background: transparent; border: none; color: #2563eb; cursor: pointer; font: inherit; padding: 0; }
      button:disabled { cursor: wait; opacity: 0.75; }
    `
    const button = composer.ownerDocument.createElement('button')
    button.type = 'button'
    button.textContent = '翻译'
    button.addEventListener('click', () => {
      void runOutgoingTranslation(button, onTranslate)
    })
    shadow.append(style, button)
    composer.parentElement.insertBefore(host, composer)
    return host
  }
}

export function adapterFor(root: Document | HTMLElement): WhatsAppAdapter {
  return new WhatsAppAdapter(root)
}
