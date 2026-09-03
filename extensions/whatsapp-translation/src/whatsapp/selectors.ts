export const WHATSAPP_SELECTORS = {
  chatRoot: '#main',
  composer: '#main footer div[contenteditable="true"][data-tab]',
  directIdentity: '#main[data-id$="@c.us"], #main [data-id$="@c.us"]',
  groupIdentity: '#main[data-id$="@g.us"], #main [data-id$="@g.us"]',
  incomingMessage: '#main .message-in',
  mediaMessage: '.media-panel',
  messageText: '.copyable-text .selectable-text',
  outgoingMessage: '#main .message-out',
  revokedMessage: '.message-revoked',
  systemMessage: '.message-system',
} as const
