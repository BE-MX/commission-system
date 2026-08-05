const ACTIVE_JOB_STATUSES = new Set(['queued', 'running'])
const JOB_STATUS_RANK = {
  queued: 0,
  running: 1,
  succeeded: 2,
  failed: 2,
}

export function advanceJob(current, incoming) {
  if (!incoming) return current ?? null
  if (!current) return { ...incoming }
  if (current.id !== incoming.id) return current

  const currentRank = JOB_STATUS_RANK[current.status]
  const incomingRank = JOB_STATUS_RANK[incoming.status]
  if (currentRank === undefined || incomingRank === undefined) return current
  if (currentRank === 2 || incomingRank < currentRank) return current
  return { ...current, ...incoming }
}

export function acceptConversationResponse(activeGeneration, responseGeneration) {
  return activeGeneration === responseGeneration
}

export function nextConversationGeneration(currentGeneration, { internalRefresh = false } = {}) {
  return internalRefresh ? currentGeneration : currentGeneration + 1
}

export function createSessionSingleFlight() {
  let pending = null
  let mode = null

  return {
    get pending() {
      return pending
    },
    get mode() {
      return mode
    },
    run(requestedMode, operation) {
      if (pending) return pending
      mode = requestedMode
      let result
      try {
        result = operation()
      } catch (error) {
        result = Promise.reject(error)
      }
      const tracked = Promise.resolve(result).finally(() => {
        if (pending !== tracked) return
        pending = null
        mode = null
      })
      pending = tracked
      return tracked
    },
  }
}

export function canStartSend({ sendInFlight, uploadInFlight, activeJob } = {}) {
  return !sendInFlight && !uploadInFlight && !ACTIVE_JOB_STATUSES.has(activeJob?.status)
}

export function canStartUpload({ uploadInFlight, sendInFlight } = {}) {
  return !uploadInFlight && !sendInFlight
}

export function upsertAttachment(items, uploadId, patch) {
  const index = items.findIndex(item => item.uploadId === uploadId)
  if (index === -1) return [...items, { uploadId, ...patch }]
  return items.map((item, itemIndex) => (
    itemIndex === index ? { ...item, ...patch, uploadId } : item
  ))
}

export function selectBaseAsset(asset) {
  return asset?.id ?? null
}

export function restoreActiveJob(job) {
  return ACTIVE_JOB_STATUSES.has(job?.status) ? { ...job } : null
}

export function replaceActiveJob(state, job) {
  const existingIndex = state.jobs.findIndex(item => item.id === job.id)
  const nextJob = existingIndex === -1
    ? { ...job }
    : advanceJob(state.jobs[existingIndex], job)
  const jobs = existingIndex === -1
    ? [...state.jobs, nextJob]
    : state.jobs.map((item, index) => index === existingIndex ? nextJob : item)
  let activeJobId = existingIndex === -1 ? null : state.activeJobId
  if (ACTIVE_JOB_STATUSES.has(nextJob.status)) activeJobId = nextJob.id
  else if (activeJobId === nextJob.id) activeJobId = null
  return { ...state, activeJobId, jobs }
}

export function createObjectUrlRegistry(urlApi = URL) {
  const urls = new Map()

  function release(url) {
    try {
      urlApi.revokeObjectURL(url)
    } catch {
      // The registry must still forget stale browser resources during cleanup.
    }
  }

  function revoke(key) {
    const url = urls.get(key)
    if (!url) return
    urls.delete(key)
    release(url)
  }

  return {
    create(key, blob) {
      const url = urlApi.createObjectURL(blob)
      const previous = urls.get(key)
      urls.set(key, url)
      if (previous) release(previous)
      return url
    },
    get(key) {
      return urls.get(key) ?? null
    },
    revoke,
    revokeAll() {
      for (const key of [...urls.keys()]) revoke(key)
    },
  }
}
