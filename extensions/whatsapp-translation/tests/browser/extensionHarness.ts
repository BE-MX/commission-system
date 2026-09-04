import { createComposerController } from '../../src/content/composerController'
import { createOutgoingComposer } from '../../src/content/outgoingComposer'
import { createToolbarView } from '../../src/content/toolbarView'
import { WhatsAppAdapter } from '../../src/whatsapp/adapter'

const adapter = new WhatsAppAdapter(document)
const composer = createOutgoingComposer(adapter, {
  async translate() {
    return { translation: 'Your sample is ready.', backTranslation: '您的样品已准备好。' }
  },
})
composer.setTargetLanguage('en')
const shadow = adapter.mountComposerToolbar()
if (!shadow) throw new Error('Synthetic direct-chat fixture was not recognized')
const view = createToolbarView(shadow, {
  onCancelPreview: () => controller.onCancelPreview(),
  onLanguageChange: language => { void controller.onLanguageChange(language) },
  onReplace: () => { void controller.onReplace() },
  onRestore: () => { void controller.onRestore() },
  onRetry: () => { void controller.onRetry() },
  onTranslate: () => { void controller.onTranslate() },
})
const controller = createComposerController(composer, view, { async save() {} })
composer.bindShortcut(document, () => { void controller.onShortcut() })
document.getElementById('editor')!.addEventListener('input', () => controller.onComposerInput())
controller.reset()
document.documentElement.dataset.extensionReady = 'true'
