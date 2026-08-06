import { onBeforeUnmount, ref } from 'vue'
import { getJob } from '@/api/designImage'

const ACTIVE_STATUSES = new Set(['queued', 'running'])

export function useJobPolling({ pollJob = getJob, intervalMs = 2500 } = {}) {
  const pollBusy = ref(false)
  const pollGeneration = ref(0)
  let timer = null
  let activeSnapshot = null

  function clearTimer() {
    if (timer !== null) clearTimeout(timer)
    timer = null
  }

  function stopPolling() {
    clearTimer()
    pollGeneration.value += 1
    activeSnapshot = null
    pollBusy.value = false
  }

  function snapshotIsCurrent(snapshot) {
    return snapshot.generation === pollGeneration.value
      && snapshot.sessionIdSnapshot === activeSnapshot?.sessionIdSnapshot
      && snapshot.jobIdSnapshot === activeSnapshot?.jobIdSnapshot
  }

  function schedule(snapshot) {
    clearTimer()
    timer = setTimeout(() => poll(snapshot), intervalMs)
  }

  async function poll(snapshot) {
    if (!snapshotIsCurrent(snapshot) || pollBusy.value) return
    pollBusy.value = true
    try {
      const response = await pollJob(snapshot.jobIdSnapshot)
      if (!snapshotIsCurrent(snapshot)) return
      const job = response?.data ?? null
      if (!job) return
      const appliedJob = await snapshot.onUpdate(job, snapshot) ?? job
      if (snapshotIsCurrent(snapshot) && ACTIVE_STATUSES.has(appliedJob.status)) schedule(snapshot)
      else stopPolling()
    } catch (error) {
      if (snapshotIsCurrent(snapshot)) {
        snapshot.onError?.(error)
        schedule(snapshot)
      }
    } finally {
      if (snapshot.generation === pollGeneration.value) pollBusy.value = false
    }
  }

  function startPolling({ sessionId, jobId, onUpdate, onError }) {
    stopPolling()
    const snapshot = {
      generation: pollGeneration.value,
      sessionIdSnapshot: sessionId,
      jobIdSnapshot: jobId,
      onUpdate,
      onError,
    }
    activeSnapshot = snapshot
    schedule(snapshot)
  }

  onBeforeUnmount(stopPolling)

  return { pollBusy, pollGeneration, startPolling, stopPolling }
}
