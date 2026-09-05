import { onActivated, ref } from 'vue'
import { useListPage } from '@/composables/useListPage'

export function useOperationsList(fetcher, options = {}) {
  const error = ref(null), summary = ref(null), dataAsOf = ref(null)
  let requestId = 0
  const state = useListPage(async params => {
    const request = ++requestId
    error.value = null
    try {
      const response = await fetcher(params)
      if (request === requestId) {
        summary.value = response.data?.summary ?? null
        dataAsOf.value = response.data?.data_as_of ?? null
      }
      return response.data
    } catch (caught) {
      if (request === requestId) { error.value = caught; summary.value = null }
      return { items: [], total: 0 }
    }
  }, options)
  let activated = false
  onActivated(() => {
    if (activated) state.fetchList()
    activated = true
  })
  return { ...state, error, summary, dataAsOf }
}
