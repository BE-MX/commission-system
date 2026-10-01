import { computed, getCurrentInstance, onUnmounted, ref } from 'vue'
import { errorMessage } from '../utils/errors.js'

/** Latest-request contract for independent detail/summary resources. */
export function useAsyncResource(loader, { initialData = null } = {}) {
  const initial = () => initialData === null ? null : JSON.parse(JSON.stringify(initialData))
  const data = ref(initial()), loading = ref(false), error = ref(null), hasLoaded = ref(false)
  let sequence = 0, controller, lastParams
  function cancel() {
    sequence++; controller?.abort()
    loading.value = false
  }
  function clear() {
    cancel()
    data.value = initial(); hasLoaded.value = false; error.value = null
  }
  async function load(params = lastParams, { clear = false } = {}) {
    lastParams = params == null ? params : JSON.parse(JSON.stringify(params))
    const requestParams = lastParams == null ? lastParams : JSON.parse(JSON.stringify(lastParams))
    const id = ++sequence
    controller?.abort()
    controller = new AbortController()
    const active = controller, isCurrent = () => id === sequence && !active.signal.aborted
    if (clear) { data.value = initial(); hasLoaded.value = false }
    loading.value = true; error.value = null
    try {
      const result = await loader(requestParams, { signal: active.signal, isCurrent })
      if (!isCurrent()) return false
      data.value = result
      hasLoaded.value = true
      return true
    } catch (caught) {
      if (isCurrent()) error.value = caught
      return false
    } finally { if (isCurrent()) loading.value = false }
  }
  if (getCurrentInstance()) onUnmounted(cancel)
  const hasData = computed(() => Array.isArray(data.value) ? data.value.length > 0 : data.value !== null)
  return {
    data, loading, error, hasLoaded, hasData,
    isStale: computed(() => hasLoaded.value && !!error.value),
    isEmpty: computed(() => hasLoaded.value && !loading.value && !error.value && !hasData.value),
    errorMessage: computed(() => error.value ? errorMessage(error.value) : ''), load, clear, cancel,
  }
}
