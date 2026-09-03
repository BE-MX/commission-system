import { WHATSAPP_SELECTORS } from '@/whatsapp/selectors'

export type ChatKind = 'direct' | 'no_chat' | 'unknown'

export type ChatState = {
  kind: ChatKind
}

export function detectChatKind(root: Document | HTMLElement): ChatState {
  if (!root.querySelector(WHATSAPP_SELECTORS.chatRoot)) return { kind: 'no_chat' }

  const conversationTitle = root.querySelector(WHATSAPP_SELECTORS.conversationTitle)?.textContent?.trim()
  if (!conversationTitle) return { kind: 'unknown' }

  return root.querySelector(WHATSAPP_SELECTORS.directChat)
    ? { kind: 'direct' }
    : { kind: 'unknown' }
}
