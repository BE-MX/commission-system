import { onBeforeUnmount, onMounted } from 'vue'

const SEQUENCE_GAP_MS = 250
const IDLE_SUBMIT_MS = 180

function isEditableTarget(target) {
  const tag = String(target?.tagName || '').toLowerCase()
  return target?.isContentEditable || ['input', 'textarea', 'select'].includes(tag)
}

export function useScannerWedge(onCode) {
  let buffer = ''
  let lastKeyAt = 0
  let timer = 0

  function reset() {
    globalThis.clearTimeout(timer)
    buffer = ''
    lastKeyAt = 0
  }

  function submit() {
    globalThis.clearTimeout(timer)
    const value = buffer.trim()
    reset()
    if (value.length >= 8) onCode(value)
  }

  function handleKeydown(event) {
    if (isEditableTarget(event.target) || event.ctrlKey || event.metaKey || event.altKey) return
    if (event.key === 'Enter' || event.key === 'Tab') {
      if (!buffer) return
      event.preventDefault()
      submit()
      return
    }
    if (event.key.length !== 1) return

    const now = performance.now()
    if (lastKeyAt && now - lastKeyAt > SEQUENCE_GAP_MS) buffer = ''
    lastKeyAt = now
    buffer += event.key
    event.preventDefault()
    globalThis.clearTimeout(timer)
    timer = globalThis.setTimeout(submit, IDLE_SUBMIT_MS)
  }

  onMounted(() => globalThis.addEventListener('keydown', handleKeydown, true))
  onBeforeUnmount(() => {
    globalThis.removeEventListener('keydown', handleKeydown, true)
    reset()
  })
}
