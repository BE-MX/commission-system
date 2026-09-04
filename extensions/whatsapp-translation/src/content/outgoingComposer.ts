export type OutgoingBridgeRequest = {
  direction: 'outgoing'
  request_id: string
  source_language: string
  target_language: string
  text: string
}

export type OutgoingBridge = {
  translate: (request: OutgoingBridgeRequest) => Promise<{ translation: string }>
}

export type OutgoingPreview = {
  composerVersion: string
  original: string
  translated: string
}

const MAX_TEXT_CODE_POINTS = 4_000

function codePointLength(value: string): number {
  return [...value].length
}

export function createOutgoingComposer(
  adapter: {
    inspectChat: () => { kind: string }
    readComposer: () => string
    replaceComposer: (text: string) => Promise<boolean>
  },
  bridge: OutgoingBridge,
) {
  let preview: OutgoingPreview | undefined
  let targetLanguage = 'zh-CN'
  let chatGeneration = 0
  let previewGeneration = 0

  async function translateForPreview(): Promise<OutgoingPreview> {
    const requestedGeneration = chatGeneration
    if (adapter.inspectChat().kind !== 'direct') throw new Error('chat_unsupported')
    const original = adapter.readComposer()
    if (!original) throw new Error('empty_composer')
    if (codePointLength(original) > MAX_TEXT_CODE_POINTS) throw new Error('text_too_long')

    const response = await bridge.translate({
      direction: 'outgoing',
      request_id: crypto.randomUUID(),
      source_language: 'auto',
      target_language: targetLanguage,
      text: original,
    })
    preview = {
      composerVersion: original,
      original,
      translated: response.translation,
    }
    previewGeneration = requestedGeneration
    return preview
  }

  async function replaceWithPreview(): Promise<boolean> {
    if (!preview || previewGeneration !== chatGeneration || adapter.readComposer() !== preview.composerVersion) return false
    return adapter.replaceComposer(preview.translated)
  }

  async function translateAndReplace(): Promise<void> {
    await translateForPreview()
    if (!await replaceWithPreview()) throw new Error('composer_changed')
  }

  return {
    bindShortcut(ownerDocument: Document, handler: () => void): () => void {
      const listener = (event: KeyboardEvent) => {
        if (event.altKey && event.key.toLowerCase() === 't') {
          event.preventDefault()
          handler()
        }
      }
      ownerDocument.addEventListener('keydown', listener)
      return () => ownerDocument.removeEventListener('keydown', listener)
    },
    invalidateChat(): void {
      chatGeneration += 1
      preview = undefined
    },
    getPreview: () => preview,
    replaceWithPreview,
    setTargetLanguage(language: string): void {
      targetLanguage = language
      preview = undefined
    },
    translateAndReplace,
    translateForPreview,
  }
}
