import { onActivated, ref } from 'vue'
import { useListPage } from '@/composables/useListPage'
import { watchListResourceScope } from '@/composables/useListResourceScope'

export function useOperationsList(fetcher, options = {}) {
  const summary = ref(null), dataAsOf = ref(null)
  const state = useListPage(async (params, { signal, isCurrent }) => {
    const response = await fetcher(params, { signal, suppressToast: true })
    if (isCurrent()) {
      summary.value = response.data?.summary ?? null
      dataAsOf.value = response.data?.data_as_of ?? null
    }
    return response.data
  }, options)
  watchListResourceScope(state, options.resourceKeys || [], () => {
    summary.value = null
    dataAsOf.value = null
  })
  let activated = false
  onActivated(() => {
    if (activated) state.fetchList()
    activated = true
  })
  return { ...state, summary, dataAsOf }
}
