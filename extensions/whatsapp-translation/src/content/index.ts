import { createIncomingTranslator } from '@/content/incomingTranslator'
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

function startContentScript(): void {
  const adapter = adapterFor(document)
  const translator = createIncomingTranslator(adapter, backgroundBridge, {
    mountTranslation,
  })
  let chatRoot = adapter.chatRootElement()

  const observer = new MutationObserver(() => {
    const currentChatRoot = adapter.chatRootElement()
    if (currentChatRoot !== chatRoot) {
      chatRoot = currentChatRoot
      translator.chatChanged()
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
