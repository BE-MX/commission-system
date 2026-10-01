import { watch } from 'vue'
import { clearListResource } from '../../composables/useListResourceScope.js'

export function designActorScope(auth) {
  return JSON.stringify([auth.user?.id ?? null, auth.user?.roles || [], auth.user?.permissions || []])
}

// Authority is a forced request scope, independent of the editable filter draft.
export function watchDesignActor(state, readScope, onReset = () => {}) {
  return watch(readScope, () => {
    const reload = state.hasLoaded.value || state.loading.value
    clearListResource(state)
    onReset()
    if (reload) state.fetchList()
  }, { flush: 'sync' })
}
