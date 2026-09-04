/** Attributes the extension writes onto page nodes. Never WhatsApp's own attributes. */
export const ARK_MARKS = {
  toolbarHost: 'data-ark-outgoing-control',
  translationHost: 'data-ark-translation-host',
  translationState: 'data-ark-translation-state',
} as const

export type TranslationHostState = 'loading' | 'success' | 'error' | 'blocked'
