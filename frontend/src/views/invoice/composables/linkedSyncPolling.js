// Read-only refreshes. Durable pending intents continue on the server.
export function createLinkedSyncPolling(read, refresh, timers = globalThis) {
  let timer = null
  let stopped = false
  const ready = () => {
    const state = read()
    return state.active && !state.busy && !state.refreshing &&
      ['pending', 'running'].includes(state.operation?.status)
  }
  function update() {
    if (timer !== null) timers.clearTimeout(timer)
    timer = null
    if (stopped || !ready()) return
    timer = timers.setTimeout(() => {
      timer = null
      if (!stopped && ready()) refresh()
      update()
    }, 3000)
  }
  function stop() {
    stopped = true
    if (timer !== null) timers.clearTimeout(timer)
    timer = null
  }
  return { update, stop }
}
