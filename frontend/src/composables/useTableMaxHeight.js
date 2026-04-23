import { ref, onMounted, onUnmounted, nextTick } from 'vue'

export function useTableMaxHeight(bottomOffset = 72) {
  const tableRef = ref()
  const maxHeight = ref(400)

  function update() {
    const el = tableRef.value?.$el || tableRef.value
    if (el) {
      const top = el.getBoundingClientRect().top
      maxHeight.value = Math.max(200, window.innerHeight - top - bottomOffset)
    }
  }

  onMounted(() => {
    nextTick(update)
    window.addEventListener('resize', update)
  })

  onUnmounted(() => {
    window.removeEventListener('resize', update)
  })

  return { tableRef, maxHeight }
}
