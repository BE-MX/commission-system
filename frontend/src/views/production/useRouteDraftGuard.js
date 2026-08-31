import { onBeforeUnmount, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'


export function createDraftUnloadGuard(isDirty, target = window) {
  let listening = false
  const handler = event => {
    if (!isDirty()) return
    event.preventDefault()
    event.returnValue = ''
  }
  const sync = dirty => {
    if (dirty && !listening) {
      target.addEventListener('beforeunload', handler)
      listening = true
    } else if (!dirty && listening) {
      target.removeEventListener('beforeunload', handler)
      listening = false
    }
  }
  const dispose = () => {
    if (!listening) return
    target.removeEventListener('beforeunload', handler)
    listening = false
  }
  return { sync, dispose }
}


export function createDraftLeaveGuard(isDirty, confirmDiscard) {
  let pending = null
  return () => {
    if (!isDirty()) return Promise.resolve(true)
    if (!pending) {
      pending = Promise.resolve()
        .then(confirmDiscard)
        .then(() => true, () => false)
        .finally(() => { pending = null })
    }
    return pending
  }
}


export function useRouteDraftGuard(hasUnsavedChanges, confirmDiscard) {
  const confirmDraftLeave = createDraftLeaveGuard(() => hasUnsavedChanges.value, confirmDiscard)
  const unloadGuard = createDraftUnloadGuard(() => hasUnsavedChanges.value)
  watch(hasUnsavedChanges, unloadGuard.sync, { immediate: true })
  onBeforeUnmount(unloadGuard.dispose)
  onBeforeRouteLeave(confirmDraftLeave)
  return confirmDraftLeave
}
