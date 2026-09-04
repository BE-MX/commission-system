import { codeFromError } from '@/content/messages'
import type { OutgoingPreview } from '@/content/outgoingComposer'
import type { ToolbarModel, ToolbarStatus, ToolbarView } from '@/content/toolbarView'

export type OutgoingComposerController = {
  canRestore: () => boolean
  clearPreview: () => void
  getPreview: () => OutgoingPreview | undefined
  getTargetLanguage: () => string
  previewIsFresh: () => boolean
  replaceWithPreview: () => Promise<boolean>
  restoreOriginal: () => Promise<boolean>
  setTargetLanguage: (language: string) => void
  translateForPreview: () => Promise<OutgoingPreview>
}

/**
 * Glue between the outgoing composer state machine and the toolbar view.
 * Owns the visible status; the composer owns preview/restore validity.
 */
export function createComposerController(
  composer: OutgoingComposerController,
  view: ToolbarView,
  languageStore: { save: (language: string) => Promise<void> },
) {
  let status: ToolbarStatus = { kind: 'idle' }
  let busy = false

  function model(): ToolbarModel {
    return {
      canRestore: composer.canRestore(),
      preview: composer.getPreview(),
      status,
      targetLanguage: composer.getTargetLanguage(),
    }
  }

  function paint(options?: { animatePreview?: boolean }): void {
    view.render(model(), options)
  }

  async function translate(options: { animate: boolean }): Promise<void> {
    if (busy) return
    busy = true
    status = { kind: 'busy' }
    paint()
    try {
      await composer.translateForPreview()
      status = { kind: 'idle' }
      paint({ animatePreview: options.animate })
    } catch (error) {
      status = { kind: 'error', code: codeFromError(error) }
      paint()
    } finally {
      busy = false
    }
  }

  async function replace(): Promise<void> {
    if (busy) return
    busy = true
    status = { kind: 'replacing' }
    paint()
    try {
      const replaced = await composer.replaceWithPreview()
      status = replaced ? { kind: 'replaced' } : { kind: 'error', code: 'composer_write_failed' }
    } catch (error) {
      status = { kind: 'error', code: codeFromError(error) }
    } finally {
      busy = false
      paint()
    }
  }

  async function restore(): Promise<void> {
    await composer.restoreOriginal()
    status = { kind: 'idle' }
    paint()
  }

  return {
    async onLanguageChange(language: string): Promise<void> {
      composer.setTargetLanguage(language)
      status = { kind: 'idle' }
      paint()
      await languageStore.save(language)
    },
    /** Composer text changed by the user: the "replaced" status is stale once they edit. */
    onComposerInput(): void {
      if (status.kind === 'replaced' && !composer.canRestore()) {
        status = { kind: 'idle' }
        paint()
      }
      if (status.kind === 'idle' && composer.getPreview() === undefined) paint()
    },
    /** Alt+T: translate when there is no fresh preview, replace when there is. No animation either way. */
    async onShortcut(): Promise<void> {
      if (composer.previewIsFresh()) {
        await replace()
        return
      }
      await translate({ animate: false })
    },
    onCancelPreview(): void {
      composer.clearPreview()
      status = { kind: 'idle' }
      paint()
    },
    onReplace: replace,
    onRestore: restore,
    onRetry: () => translate({ animate: true }),
    onTranslate: () => translate({ animate: true }),
    reset(): void {
      status = { kind: 'idle' }
      paint()
    },
  }
}

export type ComposerController = ReturnType<typeof createComposerController>
