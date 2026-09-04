export const WHATSAPP_SELECTORS = {
  chatRoot: '#main',
  composer: '#main footer div[contenteditable="true"][data-tab]',
  conversationTitle: '#main [data-testid="conversation-info-header-chat-title"]',
  darkTheme: 'body.dark',
  directChat: '#main [data-testid="conversation-header"] [aria-label="个人主页详情"][role="button"]',
  footer: '#main footer',
  message: '#main [data-testid="msg-container"]',
  messageMetadata: '.copyable-text[data-pre-plain-text]',
  messageText: 'span[data-testid="selectable-text"]',
} as const
