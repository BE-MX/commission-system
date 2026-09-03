import { detectChatKind } from '@/whatsapp/chatDetector'
import { parseIncomingMessages } from '@/whatsapp/messageParser'
import { WHATSAPP_SELECTORS } from '@/whatsapp/selectors'

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
}

export function adapterFor(root: Document | HTMLElement): WhatsAppAdapter {
  return new WhatsAppAdapter(root)
}
