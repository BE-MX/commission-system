export type OutgoingBridgeRequest = {
  direction: 'outgoing'
  request_id: string
  source_language: string
  target_language: string
  text: string
}

export type OutgoingBridgeResult = {
  backTranslation?: string
  sourceLanguage?: string
  translation: string
}

export type OutgoingBridge = {
  translate: (request: OutgoingBridgeRequest) => Promise<OutgoingBridgeResult>
}

export type OutgoingPreview = {
  backTranslation?: string
  composerVersion: string
  original: string
  targetLanguage: string
  translated: string
}

/** What was in the composer before we replaced it, so the user can undo. */
export type OutgoingRestorePoint = {
  original: string
  translated: string
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
  let restorePoint: OutgoingRestorePoint | undefined
  let targetLanguage = 'zh-CN'
  let chatGeneration = 0
  let previewGeneration = 0

  async function translateForPreview(): Promise<OutgoingPreview> {
    const requestedGeneration = chatGeneration
    const requestedLanguage = targetLanguage
    if (adapter.inspectChat().kind !== 'direct') throw new Error('chat_unsupported')
    const original = adapter.readComposer()
    if (!original) throw new Error('empty_composer')
    const response = await bridge.translate({
      direction: 'outgoing',
      request_id: crypto.randomUUID(),
      source_language: 'auto',
      target_language: requestedLanguage,
      text: original,
    })
    if (requestedGeneration !== chatGeneration || requestedLanguage !== targetLanguage) throw new Error('composer_changed')
    preview = {
      backTranslation: response.backTranslation,
      composerVersion: original,
      original,
      targetLanguage: requestedLanguage,
      translated: response.translation,
    }
    previewGeneration = requestedGeneration
    return preview
  }

  function previewIsFresh(): boolean {
    return preview !== undefined
      && previewGeneration === chatGeneration
      && adapter.readComposer() === preview.composerVersion
  }

  async function replaceWithPreview(): Promise<boolean> {
    if (!preview || !previewIsFresh()) return false
    const replaced = await adapter.replaceComposer(preview.translated)
    if (replaced) {
      restorePoint = { original: preview.original, translated: preview.translated }
      preview = undefined
    }
    return replaced
  }

  /** Put the Chinese draft back. Only valid while the composer still holds the translated text untouched. */
  async function restoreOriginal(): Promise<boolean> {
    if (!restorePoint) return false
    if (adapter.readComposer() !== restorePoint.translated) {
      restorePoint = undefined
      return false
    }
    const restored = await adapter.replaceComposer(restorePoint.original)
    if (restored) restorePoint = undefined
    return restored
  }

  function canRestore(): boolean {
    return restorePoint !== undefined && adapter.readComposer() === restorePoint.translated
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
    canRestore,
    clearPreview(): void {
      preview = undefined
    },
    getPreview: () => (previewIsFresh() ? preview : undefined),
    getTargetLanguage: () => targetLanguage,
    invalidateChat(): void {
      chatGeneration += 1
      preview = undefined
      restorePoint = undefined
    },
    previewIsFresh,
    replaceWithPreview,
    restoreOriginal,
    setTargetLanguage(language: string): void {
      if (language === targetLanguage) return
      targetLanguage = language
      preview = undefined
    },
    translateAndReplace,
    translateForPreview,
  }
}
