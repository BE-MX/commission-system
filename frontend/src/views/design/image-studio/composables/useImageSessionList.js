import { ref } from 'vue'
import { useAsyncResource } from '../../../../composables/useAsyncResource.js'

// Cursor history owns its append boundary and retains successful rows on read failure.
export function useImageSessionList(listSessions) {
  const sessions = ref([])
  const sessionsAppend = ref(false)
  const sessionsResource = useAsyncResource(async ({ append, cursor }, { signal, isCurrent }) => {
    const response = await listSessions(cursor ? { cursor } : {}, { signal, suppressToast: true })
    const page = response?.data ?? { items: [], next_cursor: null }
    if (isCurrent()) {
      mergeSessionPage(page.items || [], append)
      nextCursor.value = page.next_cursor ?? null
    }
    return page.items || []
  }, { initialData: [] })
  const nextCursor = ref(null)
  const sessionsLoading = sessionsResource.loading
  function mergeSession(session) {
    if (!session) return
    const index = sessions.value.findIndex(item => item.id === session.id)
    sessions.value = index === -1
      ? [session, ...sessions.value]
      : sessions.value.map(item => item.id === session.id ? { ...item, ...session } : item)
  }
  function mergeSessionPage(items, append) {
    const incomingIds = new Set(items.map(item => item.id))
    const existingById = new Map(sessions.value.map(item => [item.id, item]))
    const uniqueItems = [...new Map(items.map(item => [item.id, item])).values()]
    const incoming = uniqueItems.map(item => ({ ...existingById.get(item.id), ...item }))
    if (append) {
      const additions = incoming.filter(item => !existingById.has(item.id))
      sessions.value = [
        ...sessions.value.map(item => incomingIds.has(item.id)
          ? incoming.find(candidate => candidate.id === item.id)
          : item),
        ...additions,
      ]
      return
    }
    const locallyCreated = sessions.value.filter(item => !incomingIds.has(item.id))
    sessions.value = [...locallyCreated, ...incoming]
  }

  function loadSessions({ append = false } = {}) {
    if (sessionsLoading.value || (append && !nextCursor.value)) return false
    sessionsAppend.value = append
    return sessionsResource.load({ append, cursor: append ? nextCursor.value : null })
  }
  function retrySessions() { return sessionsResource.load() }
  function clearSessions() {
    sessionsResource.clear()
    sessions.value = []
    nextCursor.value = null
    sessionsAppend.value = false
  }
  return { sessions, nextCursor, sessionsAppend, sessionsResource, sessionsLoading, mergeSession, loadSessions, retrySessions, clearSessions }
}
