import { onBeforeUnmount, ref, shallowRef } from 'vue'
import { factoryInboundApi } from '@/api/factoryInbound'
import { pendingRecognition } from '../inboundLabels'

export function useInboundRecognition() {
  const note = shallowRef(null)
  const waiting = ref(false)
  const delayed = ref(false)
  const readError = ref('')
  let timer
  let request

  function cancel() {
    request?.abort()
    request = null
    clearTimeout(timer)
    waiting.value = false
  }

  function open(id, { clear = true } = {}) {
    cancel()
    if (clear) note.value = null
    delayed.value = false
    readError.value = ''
    if (!id) return
    const controller = new AbortController()
    request = controller
    const started = Date.now()
    waiting.value = true
    async function tick() {
      try {
        const result = await factoryInboundApi.detail(id, {
          signal: controller.signal, suppressToast: true,
        })
        if (request !== controller) return
        note.value = result.data
        readError.value = ''
        if (!pendingRecognition(note.value)) return
        const elapsed = Date.now() - started
        delayed.value = elapsed >= 150000
        if (!delayed.value) timer = setTimeout(tick, elapsed < 15000 ? 2000 : 5000)
      } catch (error) {
        if (request !== controller) return
        readError.value = error.response?.data?.detail ?? '无法读取到货单，请重试。'
      } finally {
        if (request === controller) waiting.value = false
      }
    }
    tick()
  }

  onBeforeUnmount(cancel)
  return { note, waiting, delayed, readError, open, cancel }
}
