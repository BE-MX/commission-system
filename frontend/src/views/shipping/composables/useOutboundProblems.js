import { ref } from 'vue'
import { getOutboundProblems } from '@/api/invoice'
import { useListPage } from '@/composables/useListPage'
import { clearListResource } from '@/composables/useListResourceScope'

let focusSequence = 0

export function useOutboundProblems() {
  const checkedAt = ref(null)
  const state = useListPage(async (params, { signal, isCurrent }) => {
    const data = await getOutboundProblems(params, { signal })
    if (isCurrent()) {
      checkedAt.value = data.checked_at
      window.dispatchEvent(new Event('ark-document-anomalies-changed'))
    }
    return data
  }, { immediate: false })
  function reset() { clearListResource(state); checkedAt.value = null }
  function changePage(page) { state.page.value = page; return state.refreshUpdate() }
  function location(item) {
    if (!item.target) return null
    return { path: '/shipping/outbound', query: { ...item.target, problem: item.key, problem_focus: String(++focusSequence) } }
  }
  return { state, checkedAt, reset, load: state.refreshUpdate, changePage, location }
}
