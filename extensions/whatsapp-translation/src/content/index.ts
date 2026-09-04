import { createIncomingTranslator } from '@/content/incomingTranslator'
import { createOutgoingComposer } from '@/content/outgoingComposer'
import { mountTranslation } from '@/content/render'
import { adapterFor } from '@/whatsapp/adapter'
import type { RuntimeRequest, RuntimeResponse } from '@/shared/contracts'
import type { IncomingBridge, IncomingBridgeRequest } from '@/content/incomingTranslator'

export const backgroundBridge: IncomingBridge = {
  async translate(request: IncomingBridgeRequest) {
    const message: RuntimeRequest = {
      request_id: request.request_id,
      source_language: 'auto',
      target_language: request.target_language,
      text: request.text,
      type: 'translation/incoming',
    }
    const response = await chrome.runtime.sendMessage(message) as RuntimeResponse | undefined
    if (response?.type !== 'translation/incoming') {
      const code = response?.type === 'error' ? response.message : 'unexpected_error'
      throw new Error(code)
    }
    return { translation: response.translation }
  },
}

export const outgoingBridge = {
  async translate(request: { request_id: string; source_language: string; target_language: string; text: string }) {
    const response = await chrome.runtime.sendMessage({
      request_id: request.request_id,
      sourceLanguage: request.source_language,
      targetLanguage: request.target_language,
      text: request.text,
      type: 'translation/outgoing',
    }) as RuntimeResponse | undefined
    if (response?.type !== 'translation/outgoing') throw new Error('unexpected_error')
    return { translation: response.translation }
  },
}

function startContentScript(): void {
  const adapter = adapterFor(document)
  const translator = createIncomingTranslator(adapter, backgroundBridge, {
    mountTranslation,
  })
  let chatRoot = adapter.chatRootElement()
  const outgoingComposer = createOutgoingComposer(adapter, outgoingBridge)
  const mountOutgoingControl = () => {
    adapter.attachOutgoingControl(() => outgoingComposer.translateAndReplace())
  }
  mountOutgoingControl()
  outgoingComposer.bindShortcut(document, () => {
    void outgoingComposer.translateAndReplace().catch(() => undefined)
  })

  const observer = new MutationObserver(() => {
    const currentChatRoot = adapter.chatRootElement()
    if (currentChatRoot !== chatRoot) {
      chatRoot = currentChatRoot
      translator.chatChanged()
      outgoingComposer.invalidateChat()
      mountOutgoingControl()
    }
    translator.notifyMutation()
  })
  observer.observe(document, {
    characterData: true,
    childList: true,
    subtree: true,
  })
}

if (document.readyState !== 'loading') startContentScript()
else document.addEventListener('DOMContentLoaded', startContentScript, { once: true })
