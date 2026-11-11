// Debounce edits and serialize expensive quote requests. A queued edit replaces
// earlier queued edits while the current request finishes.
export function createShipmentQuoteScheduler(run, delay = 600) {
  let timer, running, queued = false, disposed = false
  async function flush() {
    clearTimeout(timer)
    if (disposed) return
    queued = true
    if (running) return running
    running = (async () => {
      while (queued && !disposed) {
        queued = false
        await run()
      }
    })()
    try { await running } finally { running = null }
  }
  return {
    schedule() {
      clearTimeout(timer)
      queued = false
      timer = setTimeout(() => { void flush() }, delay)
    },
    flush,
    dispose() { disposed = true; queued = false; clearTimeout(timer) },
  }
}
