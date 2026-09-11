import { createComposerController } from '@/content/composerController'
import { createIncomingTranslator, IncomingBridgeError } from '@/content/incomingTranslator'
import { createOutgoingComposer } from '@/content/outgoingComposer'
import { mountTranslation } from '@/content/render'
import { createToolbarView } from '@/content/toolbarView'
import { createLatestMountGuard } from '@/content/latestMountGuard'
import { createAutoReply } from '@/content/autoReply'
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
  let auto: ReturnType<typeof createAutoReply> | undefined
  let autoActivation = 0, autoEnabling = false
  function stopAuto(note = '自动接管已关闭') { const engaged = autoEnabling || auto?.getState().active; autoActivation++; autoEnabling = false; if (engaged) auto?.stop(note) }
  const outgoingComposer = createOutgoingComposer(adapter, outgoingBridge)
  let chatRoot = adapter.chatRootElement()
  let conversationElement = adapter.conversationElement()
  let messageElements = adapter.messageElements()
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
      if (adapter.isCollectingHistory() || !TARGET_LANGUAGES.includes(language as TargetLanguage)) return
      if (language !== outgoingComposer.getTargetLanguage()) reply?.optionsChanged()
      void controller?.onLanguageChange(language)
    },
  })

  const onComposerInput = (event: Event) => {
    if (event.isTrusted) stopAuto('检测到人工输入，自动接管已关闭')
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
    stopAuto('聊天已切换，自动接管已关闭')
    adapter.clearReplyHistory()
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
    let releaseAuto: (() => void) | undefined
    const view = createToolbarView(shadow, {
      onCancelPreview: () => controller?.onCancelPreview(),
      onLanguageChange: language => { stopAuto('发送语言已修改，请重新开启接管'); reply?.optionsChanged(); void controller?.onLanguageChange(language) },
      onReplace: () => { reply?.draftChanged(); void controller?.onReplace() },
      onRestore: () => { reply?.draftChanged(); void controller?.onRestore() },
      onRetry: () => void controller?.onRetry(),
      onTranslate: () => { stopAuto('已切换到人工翻译'); void controller?.onTranslate() },
      onAutoReply: () => {
        if (auto?.getState().active || autoEnabling) { stopAuto(); return }
        const target = auto, activation = ++autoActivation
        autoEnabling = true; view.setAutoStatus?.(true, '正在开启当前聊天自动接管…')
        reply?.cancel()
        void send({ type: 'reply/disclosure', acknowledged: true }).then(response => {
          if (activation !== autoActivation) return
          autoEnabling = false
          if (target !== auto || document.hidden || !shadow.host.isConnected || adapter.inspectChat().kind !== 'direct' || response?.type !== 'reply/disclosure' || !response.acknowledged) { target?.stop('未能开启接管，请重试'); return }
          if (!navigator.locks) { target?.stop('浏览器无法锁定接管实例，请更新浏览器'); return }
          autoEnabling = true
          void navigator.locks.request('leshine-whatsapp-auto-takeover', { ifAvailable: true }, async lock => {
            if (activation !== autoActivation || target !== auto || document.hidden) return
            autoEnabling = false
            if (!lock) { target?.stop('另一个窗口正在自动接管，请先关闭它'); return }
            await new Promise<void>(resolve => { releaseAuto = resolve; target?.start(); if (!target?.getState().active) resolve() })
            releaseAuto = undefined
          }).catch(() => { if (activation === autoActivation) { autoEnabling = false; target?.stop('无法锁定接管实例，已停止') } })
        }).catch(() => { if (activation === autoActivation) { autoEnabling = false; target?.stop('授权检查失败，请重试') } })
      },
      onReply: () => {
        stopAuto('已切换到手动话术')
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
        stopAuto('已切换到手动话术')
        const current = reply
        const revision = current?.getRevision()
        void send({ type: 'reply/disclosure', acknowledged: true }).then(response => {
          if (current !== reply || !current?.getState().open || current.getRevision() !== revision) return
          if (response?.type === 'reply/disclosure' && response.acknowledged) void current.generate(options, style)
        }).catch(() => current?.cancel())
      },
      change: () => { stopAuto('生成要求已修改，请重新开启接管'); reply?.optionsChanged() }, close: () => reply?.close(), cancel: () => reply?.cancel(),
      fill: () => { outgoingComposer.invalidateDraft(); controller?.onComposerInput(); void reply?.fill() },
      restore: () => { outgoingComposer.invalidateDraft(); controller?.onComposerInput(); void reply?.restore() },
      memory: {
        list: () => { void reply?.listInquiries() }, preview: id => { void reply?.previewInquiry(id) }, usePreview: () => reply?.usePreview(),
        create: label => { void reply?.newInquiry(label) }, enabled: enabled => reply?.setMemoryEnabled(enabled),
        refresh: () => { void reply?.refreshMemory() }, remove: () => { void reply?.deleteMemory() }, save: () => { void reply?.saveMemory() },
        correct: (id, status, note) => { void reply?.correctMemory(id, status, note) }, pause: paused => { stopAuto('已由业务员接管'); reply?.setPaused(paused) },
      },
    })
    reply = createReplyAssistant(adapter, {
      async memory(payload) {
        const response = await send({ type: 'reply/memory', payload })
        if (response?.type !== 'reply/memory') throw bridgeError(response)
        return response.result
      },
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
    auto = createAutoReply({
      snapshot: () => adapter.autoSnapshot(),
      collect: (caps, current) => adapter.collectReplyHistory({ maxMessages: caps.max_messages, maxChars: caps.max_context_chars }, current, () => {}),
      send: (text, current) => adapter.sendAutomatic(text, current),
    }, {
      async capabilities() { const response = await send({ type: 'reply/capabilities' }); if (response?.type !== 'reply/capabilities') throw bridgeError(response); return response.reply },
      async suggest(payload) { const response = await send({ type: 'reply/suggest', payload }); if (response?.type !== 'reply/suggest') throw bridgeError(response); return response.result },
    }, () => ({ language: replyView.options().language, fallback: outgoingComposer.getTargetLanguage() as TargetLanguage, goal: replyView.options().goal }), state => { view.setAutoStatus?.(state.active, state.note, state); if (!state.active) releaseAuto?.() })
    controller.reset()
    watchComposer()
  }

  outgoingComposer.bindShortcut(document, () => {
    if (outgoingComposer.previewIsFresh()) reply?.draftChanged()
    void controller?.onShortcut()
  })

  document.addEventListener('keydown', event => { if (event.isTrusted && adapter.composerElement()?.contains(event.target as Node)) stopAuto('检测到人工操作，自动接管已关闭') }, true)
  document.addEventListener('click', event => { if (event.isTrusted && adapter.isNativeSendTarget(event.target)) stopAuto('检测到人工发送，自动接管已关闭') }, true)
  document.addEventListener('visibilitychange', () => { if (document.hidden) stopAuto('页面已切到后台，自动接管已关闭') })
  void mountToolbar()

  const observer = new MutationObserver(records => {
    const currentChatRoot = adapter.chatRootElement()
    const title = adapter.chatTitle()
    const nextConversation = adapter.conversationElement()
    const nextKind = adapter.inspectChat().kind
    const nextMessages = adapter.messageElements()
    const transcriptReplaced = messageElements.length > 0 && !nextMessages.some(node => messageElements.includes(node))
    messageElements = nextMessages
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
    } else if (transcriptReplaced && !adapter.isCollectingHistory()) {
      stopAuto('聊天记录已替换，自动接管已关闭')
      adapter.clearReplyHistory()
      // Titles and containers may be reused for another contact. With no stable
      // identity, wholesale transcript replacement disconnects inquiry memory.
      // A full history remount may also disconnect; explicit restore is safer.
      reply?.chatChanged()
    }
    if (!adapter.isCollectingHistory() && records.some(record => adapter.isMessageMutation(record))) reply?.contextChanged()
    if (!adapter.isWritingComposer() && records.some(record => adapter.isComposerMutation(record))) {
      reply?.draftChanged()
      outgoingComposer.invalidateDraft()
      controller?.onComposerInput()
    }
    watchComposer()
    if (!adapter.isCollectingHistory()) translator.notifyMutation()
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
    if (!adapter.isCollectingHistory()) translator.notifyMutation()
  })
}

if (document.readyState !== 'loading') startContentScript()
else document.addEventListener('DOMContentLoaded', startContentScript, { once: true })
