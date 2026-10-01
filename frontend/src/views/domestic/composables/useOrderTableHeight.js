import { ref, nextTick, onMounted, onActivated, onUnmounted, watch } from 'vue'

// Keep the horizontal scrollbar above pagination; filters can wrap or disappear.
export function useOrderTableHeight(listError) {
  const tableRef = ref()
  const filtersRef = ref()
  const tableHeight = ref(400)
  let observer
  function update() {
    const el = tableRef.value?.$el
    if (el) tableHeight.value = Math.max(200, window.innerHeight - el.getBoundingClientRect().top - 84)
  }
  if (listError) watch(listError, () => nextTick(update))
  onMounted(() => {
    nextTick(update)
    observer = new ResizeObserver(update)
    const filters = filtersRef.value?.$el || filtersRef.value
    if (filters) observer.observe(filters)
    window.addEventListener('resize', update)
  })
  onActivated(() => nextTick(update))
  onUnmounted(() => {
    observer?.disconnect()
    window.removeEventListener('resize', update)
  })
  return { tableRef, filtersRef, tableHeight }
}
