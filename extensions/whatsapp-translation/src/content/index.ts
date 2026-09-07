import { createComposerController } from '@/content/composerController'
import { createIncomingTranslator, IncomingBridgeError } from '@/content/incomingTranslator'
import { createOutgoingComposer } from '@/content/outgoingComposer'
import { mountTranslation } from '@/content/render'
import { createToolbarView } from '@/content/toolbarView'
import { createLatestMountGuard } from '@/content/latestMountGuard'
import { createReplyAssistant } from '@/content/replyAssistant'
import { createReplyView } from '@/content/replyView'
import { adapterFor } from '@/whatsapp/adapter'
import { DEFAULT_OUTGOING_LANGUAGE, TARGET_LANGUAGES } from '@/shared/contracts'
import type { TargetLanguage } from '@/shared/contracts'
import type { RuntimeRequest, RuntimeResponse } from '@/shared/contracts'
import type { IncomingBridge, IncomingBridgeRequest } from '@/content/incomingTranslator'
import type { OutgoingBridge, OutgoingBridgeRequest } from '@/content/outgoingComposer'

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
  const outgoingComposer = createOutgoingComposer(adapter, outgoingBridge)
  let chatRoot = adapter.chatRootElement()
  let conversationElement = adapter.conversationElement()
  let chatKind = adapter.inspectChat().kind
  let currentTitle = ''
  let controller: ReturnType<typeof createComposerController> | undefined
  let reply: ReturnType<typeof createReplyAssistant> | undefined
  let composerElement: Element | null = null
  const mountGuard = createLatestMountGuard()
  const translator = createIncomingTranslator(adapter, backgroundBridge, {
    mountTranslation: (target, state, onRetry) => mountTranslation(target, state, onRetry, { dark: adapter.isDarkTheme() }),
  }, {
    onDetectedLanguage: (_message, language) => {
      if (!TARGET_LANGUAGES.includes(language as TargetLanguage)) return
      if (language !== outgoingComposer.getTargetLanguage()) reply?.optionsChanged()
      void controller?.onLanguageChange(language)
    },
  })

  const onComposerInput = (event: Event) => {
    if (adapter.isWritingComposer() && !event.isTrusted) return
    reply?.draftChanged()
    outgoingComposer.invalidateDraft()
    controller?.onComposerInput()
  }

  function watchComposer(): void {
    const next = adapter.composerElement()
    if (next === composerElement) return
    if (composerElement) {
      reply?.chatChanged()
      outgoingComposer.invalidateChat()
    }
    composerElement?.removeEventListener('input', onComposerInput)
    composerElement?.removeEventListener('beforeinput', onComposerInput)
    composerElement = next
    composerElement?.addEventListener('input', onComposerInput)
    composerElement?.addEventListener('beforeinput', onComposerInput)
  }

  async function mountToolbar(): Promise<void> {
    reply?.chatChanged()
    const mountGeneration = mountGuard.begin()
    const shadow = adapter.mountComposerToolbar()
    if (!shadow) {
      controller = undefined
      reply = undefined
      return
    }
    const title = adapter.chatTitle()
    currentTitle = title
    const language = await resolveChatLanguage(title)
    if (
      !mountGuard.isCurrent(mountGeneration)
      || !shadow.host.isConnected
      || adapter.chatTitle() !== title
    ) return
    outgoingComposer.setTargetLanguage(language)
    if (adapter.isDarkTheme()) (shadow.host as HTMLElement).setAttribute('data-ark-theme', 'dark')
    const view = createToolbarView(shadow, {
      onCancelPreview: () => controller?.onCancelPreview(),
      onLanguageChange: language => { reply?.optionsChanged(); void controller?.onLanguageChange(language) },
      onReplace: () => { reply?.draftChanged(); void controller?.onReplace() },
      onRestore: () => { reply?.draftChanged(); void controller?.onRestore() },
      onRetry: () => void controller?.onRetry(),
      onTranslate: () => void controller?.onTranslate(),
      onReply: () => {
        const current = reply
        current?.open()
        const revision = current?.getRevision()
        void send({ type: 'reply/disclosure' }).then(response => {
          if (current !== reply || !current?.getState().open || current.getRevision() !== revision) return
          if (response?.type === 'reply/disclosure' && response.acknowledged) void current.generate(replyView.options())
        }).catch(() => { /* Disclosure stays visible; explicit generation can retry. */ })
      },
    })
    controller = createComposerController(outgoingComposer, view, {
      save: async (language) => {
        if (!currentTitle) return
        await send({ chatTitle: currentTitle, targetLanguage: language, type: 'chat-language/set' })
      },
    })
    const replyView = createReplyView(shadow, {
      generate: (options, style) => {
        const current = reply
        const revision = current?.getRevision()
        void send({ type: 'reply/disclosure', acknowledged: true }).then(response => {
          if (current !== reply || !current?.getState().open || current.getRevision() !== revision) return
          if (response?.type === 'reply/disclosure' && response.acknowledged) void current.generate(options, style)
        }).catch(() => current?.cancel())
      },
      change: () => reply?.optionsChanged(), close: () => reply?.close(), cancel: () => reply?.cancel(),
      fill: () => { outgoingComposer.invalidateDraft(); controller?.onComposerInput(); void reply?.fill() },
      restore: () => { outgoingComposer.invalidateDraft(); controller?.onComposerInput(); void reply?.restore() },
    })
    reply = createReplyAssistant(adapter, {
      async capabilities() {
        const response = await send({ type: 'reply/capabilities' })
        if (response?.type !== 'reply/capabilities') throw bridgeError(response)
        return response.reply
      },
      async suggest(payload) {
        const response = await send({ type: 'reply/suggest', payload })
        if (response?.type !== 'reply/suggest') throw bridgeError(response)
        return response.result
      },
    }, () => outgoingComposer.getTargetLanguage() as TargetLanguage, state => replyView.render(state))
    controller.reset()
    watchComposer()
  }

  outgoingComposer.bindShortcut(document, () => {
    if (outgoingComposer.previewIsFresh()) reply?.draftChanged()
    void controller?.onShortcut()
  })

  void mountToolbar()

  const observer = new MutationObserver(records => {
    const currentChatRoot = adapter.chatRootElement()
    const title = adapter.chatTitle()
    const nextConversation = adapter.conversationElement()
    const nextKind = adapter.inspectChat().kind
    if (currentChatRoot !== chatRoot || title !== currentTitle || nextConversation !== conversationElement || nextKind !== chatKind) {
      chatRoot = currentChatRoot
      conversationElement = nextConversation
      chatKind = nextKind
      translator.chatChanged()
      outgoingComposer.invalidateChat()
      reply?.chatChanged()
      void mountToolbar()
    } else if (!adapter.hasToolbar() && adapter.inspectChat().kind === 'direct') {
      // WhatsApp re-rendered the footer and dropped our host.
      void mountToolbar()
    }
    if (records.some(record => adapter.isMessageMutation(record))) reply?.contextChanged()
    if (!adapter.isWritingComposer() && records.some(record => adapter.isComposerMutation(record))) {
      reply?.draftChanged()
      outgoingComposer.invalidateDraft()
      controller?.onComposerInput()
    }
    watchComposer()
    translator.notifyMutation()
  })
  observer.observe(document, {
    attributes: true,
    attributeFilter: ['aria-label', 'data-testid', 'style', 'class', 'contenteditable'],
    characterData: true,
    childList: true,
    subtree: true,
  })
  translator.notifyMutation()

  // Popup toggles / re-authorization happen out of band; re-arm on focus.
  window.addEventListener('focus', () => {
    translator.resume()
    translator.notifyMutation()
  })
}

if (document.readyState !== 'loading') startContentScript()
else document.addEventListener('DOMContentLoaded', startContentScript, { once: true })
