const ACTIVE_JOB_STATUSES = new Set(['queued', 'running'])
const JOB_STATUS_RANK = {
  queued: 0,
  running: 1,
  succeeded: 2,
  failed: 2,
}
const DIALOG_FOCUS_SELECTOR = [
  'a[href]', 'button:not([disabled])', 'input:not([disabled])', 'select:not([disabled])',
  'textarea:not([disabled])', '[tabindex]:not([tabindex="-1"])',
].join(',')

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

export function reconcileSubmittedDraft(current, snapshot) {
  const sentUploadIds = new Set(snapshot.sentUploadIds)
  return {
    prompt: current.prompt === snapshot.sentPrompt ? '' : current.prompt,
    attachments: current.attachments.filter(item => !sentUploadIds.has(item.uploadId)),
    baseAsset: current.baseAsset?.id === snapshot.sentBaseId ? null : current.baseAsset,
  }
}

export function focusDialog(container) {
  const target = container?.querySelectorAll?.(DIALOG_FOCUS_SELECTOR)?.[0] ?? container
  target?.focus?.()
  return target ?? null
}

export function trapDialogFocus(event, container, activeElement = container?.ownerDocument?.activeElement) {
  if (event.key !== 'Tab') return false
  const focusable = [...(container?.querySelectorAll?.(DIALOG_FOCUS_SELECTOR) ?? [])]
  if (!focusable.length) {
    event.preventDefault()
    container?.focus?.()
    return true
  }
  const first = focusable[0]
  const last = focusable.at(-1)
  const activeIndex = focusable.indexOf(activeElement)
  const target = activeIndex === -1
    ? (event.shiftKey ? last : first)
    : (event.shiftKey && activeElement === first
        ? last
        : (!event.shiftKey && activeElement === last ? first : null))
  if (!target) return false
  event.preventDefault()
  target.focus()
  return true
}

export function restoreDialogFocus(trigger) {
  if (trigger?.isConnected === false) return
  trigger?.focus?.()
}

export function shouldAutoScroll({
  distanceFromBottom = Infinity,
  previousMessages = [],
  nextMessages = [],
  threshold = 96,
} = {}) {
  if (distanceFromBottom <= threshold) return true
  if (!previousMessages.length && nextMessages.length) return true
  const previousIds = new Set(previousMessages.map(message => message.id))
  return nextMessages.some(message => message.role === 'user' && !previousIds.has(message.id))
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

/* 提示词库：模板 content 内的 {key} 占位用所选参数值替换（未选参数保留占位） */
export function composePrompt(template, selections = {}) {
  const content = template?.content ?? ''
  const options = Array.isArray(template?.options) ? template.options : []
  let result = content
  for (const option of options) {
    const value = selections?.[option?.key]
    if (value) result = result.split(`{${option.key}}`).join(value)
  }
  return result
}

/* 提示词库：还缺哪些参数槽未选（空数组 = 可以填入） */
export function missingPromptParams(template, selections = {}) {
  const options = Array.isArray(template?.options) ? template.options : []
  return options.filter(option => !selections?.[option?.key]).map(option => option.key)
}

export function restoreActiveJob(job) {
  return ACTIVE_JOB_STATUSES.has(job?.status) ? { ...job } : null
}

export function restoreActiveJobs(jobs) {
  return (Array.isArray(jobs) ? jobs : []).map(job => restoreActiveJob(job)).filter(Boolean)
}

/* 多任务并发下，取指定会话的进行中任务（会话级仍限一个） */
export function selectSessionActiveJob(activeJobs, sessionId) {
  if (sessionId == null || !activeJobs) return null
  for (const job of activeJobs.values()) {
    if (job.session_id === sessionId && ACTIVE_JOB_STATUSES.has(job.status)) return job
  }
  return null
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
