import { WHATSAPP_SELECTORS } from '@/whatsapp/selectors'

export type ChatKind = 'direct' | 'group' | 'no_chat' | 'unknown'

export type ChatState = {
  kind: ChatKind
}

export function detectChatKind(root: Document | HTMLElement): ChatState {
  if (!root.querySelector(WHATSAPP_SELECTORS.chatRoot)) return { kind: 'no_chat' }

  const directCount = root.querySelectorAll(WHATSAPP_SELECTORS.directIdentity).length
  const groupCount = root.querySelectorAll(WHATSAPP_SELECTORS.groupIdentity).length

  if (directCount > 0 && groupCount === 0) return { kind: 'direct' }
  if (groupCount > 0 && directCount === 0) return { kind: 'group' }
  return { kind: 'unknown' }
}
