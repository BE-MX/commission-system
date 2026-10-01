import { watch } from 'vue'

export function clearListResource(state) {
  state.cancel()
  state.list.value = []
  state.total.value = 0
  state.page.value = 1
  state.dataPage.value = 1
  state.hasLoaded.value = false
  state.error.value = null
}

// Scope keys are part of the submitted query. A failed switch must never show
// another customer's/application's/permission scope's retained rows.
export function watchListResourceScope(state, keys, onReset = () => {}) {
  return watch(() => JSON.stringify(keys.map(key => state.appliedSearchForm.value[key])), () => {
    clearListResource(state)
    onReset()
  }, { flush: 'sync' })
}
