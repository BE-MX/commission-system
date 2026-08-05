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
  const jobs = existingIndex === -1
    ? [...state.jobs, { ...job }]
    : state.jobs.map((item, index) => index === existingIndex ? { ...item, ...job } : item)
  return { ...state, activeJobId: job.id, jobs }
}

export function createObjectUrlRegistry(urlApi = URL) {
  const urls = new Map()

  function revoke(key) {
    const url = urls.get(key)
    if (!url) return
    urlApi.revokeObjectURL(url)
    urls.delete(key)
  }

  return {
    create(key, blob) {
      revoke(key)
      const url = urlApi.createObjectURL(blob)
      urls.set(key, url)
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
