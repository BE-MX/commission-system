import { ref, readonly } from 'vue'

const visible = ref(false)
const text = ref('')
let count = 0

export function useLoading() {
  function show(msg = '') {
    count++
    text.value = msg
    visible.value = true
  }

  function hide() {
    count = Math.max(0, count - 1)
    if (count === 0) {
      visible.value = false
      text.value = ''
    }
  }

  function forceHide() {
    count = 0
    visible.value = false
    text.value = ''
  }

  return {
    visible: readonly(visible),
    text: readonly(text),
    show,
    hide,
    forceHide,
  }
}
