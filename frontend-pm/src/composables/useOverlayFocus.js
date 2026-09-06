import { nextTick, onBeforeUnmount, watch } from 'vue'

// Drawers can open confirmation dialogs. Only the top layer owns focus and Escape.
const layers = []
let previousOverflow = ''
const focusableSelector = 'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'

export function useOverlayFocus(isOpen, root, close) {
  let layer = null
  let generation = 0

  function focusable() {
    return [...(root.value?.querySelectorAll(focusableSelector) || [])]
      .filter(element => element.getClientRects().length && !element.closest('[inert]'))
  }

  function onKeydown(event) {
    if (!layer || layers.at(-1) !== layer || event.defaultPrevented) return
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      close()
    } else if (event.key === 'Tab') {
      const elements = focusable()
      const first = elements[0] || root.value
      const last = elements.at(-1) || root.value
      const active = document.activeElement
      if (!root.value?.contains(active) || !elements.length
          || (event.shiftKey ? active === first : active === last)) {
        event.preventDefault()
        ;(event.shiftKey ? last : first)?.focus()
      }
    }
  }

  function release() {
    generation++
    if (!layer) return
    const wasTop = layers.at(-1) === layer
    const restoreFocus = layer.trigger
    layers.splice(layers.indexOf(layer), 1)
    layer = null
    window.removeEventListener('keydown', onKeydown)
    if (!layers.length) document.body.style.overflow = previousOverflow
    if (wasTop && restoreFocus?.isConnected) restoreFocus.focus()
  }

  watch(isOpen, async open => {
    release()
    if (!open) return
    const current = generation
    const trigger = document.activeElement
    await nextTick()
    if (current !== generation || !isOpen() || !root.value) return
    if (!layers.length) {
      previousOverflow = document.body.style.overflow
      document.body.style.overflow = 'hidden'
    }
    layer = { trigger }
    layers.push(layer)
    window.addEventListener('keydown', onKeydown)
    ;(focusable()[0] || root.value).focus()
  }, { immediate: true, flush: 'post' })

  onBeforeUnmount(release)
}
