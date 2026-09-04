import { createComposerController } from '@/content/composerController'
import { createIncomingTranslator, IncomingBridgeError } from '@/content/incomingTranslator'
import { createOutgoingComposer } from '@/content/outgoingComposer'
import { mountTranslation } from '@/content/render'
import { createToolbarView } from '@/content/toolbarView'
import { adapterFor } from '@/whatsapp/adapter'
import { DEFAULT_OUTGOING_LANGUAGE } from '@/shared/contracts'
import type { RuntimeRequest, RuntimeResponse } from '@/shared/contracts'
import type { IncomingBridge, IncomingBridgeRequest } from '@/content/incomingTranslator'
import type { OutgoingBridge, OutgoingBridgeRequest } from '@/content/outgoingComposer'
import { WHATSAPP_SELECTORS } from '@/whatsapp/selectors'

async function send(message: RuntimeRequest): Promise<RuntimeResponse | undefined> {
  return await chrome.runtime.sendMessage(message) as RuntimeResponse | undefined
}

function bridgeError(response: RuntimeResponse | undefined): IncomingBridgeError {
  const code = response?.type === 'error' ? response.message : 'unexpected_error'
  return new IncomingBridgeError(code, code)
}

export const backgroundBridge: IncomingBridge = {
  async translate(request: IncomingBridgeRequest) {
    const response = await send({
      request_id: request.request_id,
      source_language: 'auto',
      target_language: request.target_language,
      text: request.text,
      type: 'translation/incoming',
    })
    if (response?.type !== 'translation/incoming') throw bridgeError(response)
    return { sourceLanguage: response.sourceLanguage, translation: response.translation }
  },
}

export const outgoingBridge: OutgoingBridge = {
  async translate(request: OutgoingBridgeRequest) {
    const response = await send({
      request_id: request.request_id,
      sourceLanguage: request.source_language,
      targetLanguage: request.target_language,
      text: request.text,
      type: 'translation/outgoing',
    })
    if (response?.type !== 'translation/outgoing') throw bridgeError(response)
    return {
      backTranslation: response.backTranslation,
      sourceLanguage: response.sourceLanguage,
      translation: response.translation,
    }
  },
}

async function resolveChatLanguage(chatTitle: string): Promise<string> {
  if (chatTitle) {
    const stored = await send({ chatTitle, type: 'chat-language/get' })
    if (stored?.type === 'chat-language/get') return stored.targetLanguage
  }
  const preferences = await send({ type: 'preferences/get' })
  return preferences?.type === 'preferences/get' ? preferences.targetLanguage : DEFAULT_OUTGOING_LANGUAGE
}

function startContentScript(): void {
  const adapter = adapterFor(document)
  const translator = createIncomingTranslator(adapter, backgroundBridge, {
    mountTranslation: (target, state, onRetry) => mountTranslation(target, state, onRetry, { dark: adapter.isDarkTheme() }),
  })
  const outgoingComposer = createOutgoingComposer(adapter, outgoingBridge)

  let chatRoot = adapter.chatRootElement()
  let currentTitle = ''
  let controller: ReturnType<typeof createComposerController> | undefined
  let composerElement: Element | null = null

  const onComposerInput = () => controller?.onComposerInput()

  function watchComposer(): void {
    const next = document.querySelector(WHATSAPP_SELECTORS.composer)
    if (next === composerElement) return
    composerElement?.removeEventListener('input', onComposerInput)
    composerElement = next
    composerElement?.addEventListener('input', onComposerInput)
  }

  async function mountToolbar(): Promise<void> {
    const shadow = adapter.mountComposerToolbar()
    if (!shadow) {
      controller = undefined
      return
    }
    const title = adapter.chatTitle()
    currentTitle = title
    outgoingComposer.setTargetLanguage(await resolveChatLanguage(title))
    if (adapter.isDarkTheme()) (shadow.host as HTMLElement).setAttribute('data-ark-theme', 'dark')
    const view = createToolbarView(shadow, {
      onCancelPreview: () => controller?.onCancelPreview(),
      onLanguageChange: language => void controller?.onLanguageChange(language),
      onReplace: () => void controller?.onReplace(),
      onRestore: () => void controller?.onRestore(),
      onRetry: () => void controller?.onRetry(),
      onTranslate: () => void controller?.onTranslate(),
    })
    controller = createComposerController(outgoingComposer, view, {
      save: async (language) => {
        if (!currentTitle) return
        await send({ chatTitle: currentTitle, targetLanguage: language, type: 'chat-language/set' })
      },
    })
    controller.reset()
    watchComposer()
  }

  outgoingComposer.bindShortcut(document, () => {
    void controller?.onShortcut()
  })

  void mountToolbar()

  const observer = new MutationObserver(() => {
    const currentChatRoot = adapter.chatRootElement()
    const title = adapter.chatTitle()
    if (currentChatRoot !== chatRoot || title !== currentTitle) {
      chatRoot = currentChatRoot
      translator.chatChanged()
      outgoingComposer.invalidateChat()
      void mountToolbar()
    } else if (!document.querySelector('[data-ark-outgoing-control="1"]') && adapter.inspectChat().kind === 'direct') {
      // WhatsApp re-rendered the footer and dropped our host.
      void mountToolbar()
    }
    watchComposer()
    translator.notifyMutation()
  })
  observer.observe(document, {
    characterData: true,
    childList: true,
    subtree: true,
  })

  // Popup toggles / re-authorization happen out of band; re-arm on focus.
  window.addEventListener('focus', () => {
    translator.resume()
    translator.notifyMutation()
  })
}

if (document.readyState !== 'loading') startContentScript()
else document.addEventListener('DOMContentLoaded', startContentScript, { once: true })
