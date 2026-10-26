// Images each recheck live authority twice. Bound concurrency to avoid a burst
// of thumbnails exhausting the server's shared authorization lock wait budget.
export function createImageQueue(limit = 2) {
  let running = 0
  const waiting = []
  function drain() {
    while (running < limit && waiting.length) {
      const item = waiting.shift()
      if (item.signal?.aborted) { item.resolve(null); continue }
      running++
      Promise.resolve().then(() => item.task()).then(item.resolve, item.reject).finally(() => { running--; drain() })
    }
  }
  return (task, { signal, priority = 0 } = {}) => new Promise((resolve, reject) => {
    waiting.push({ task, signal, priority, resolve, reject })
    waiting.sort((a, b) => b.priority - a.priority)
    queueMicrotask(drain)
  })
}
export const queueImage = createImageQueue()
