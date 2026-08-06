import { onBeforeUnmount, ref } from 'vue'
import { getActiveJobs } from '@/api/designImage'

/* 集合式轮询：单循环拉取当前用户全部进行中任务（多对话并发），
   由调用方在 onTick 里 merge、识别终态并决定是否继续。 */
export function useJobPolling({ fetchActiveJobs = getActiveJobs, intervalMs = 2500 } = {}) {
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
    return snapshot.generation === pollGeneration.value && activeSnapshot === snapshot
  }

  function schedule(snapshot) {
    clearTimer()
    timer = setTimeout(() => poll(snapshot), intervalMs)
  }

  async function poll(snapshot) {
    if (!snapshotIsCurrent(snapshot) || pollBusy.value) return
    pollBusy.value = true
    try {
      const response = await fetchActiveJobs()
      if (!snapshotIsCurrent(snapshot)) return
      const jobs = response?.data?.jobs ?? []
      const keepPolling = await snapshot.onTick(jobs)
      if (!snapshotIsCurrent(snapshot)) return
      if (keepPolling !== false) schedule(snapshot)
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

  function startPolling({ onTick, onError }) {
    // 已在轮询则复用：onTick 闭包共享响应式状态，新任务并入无需重启循环
    if (activeSnapshot) return
    const snapshot = {
      generation: pollGeneration.value,
      onTick,
      onError,
    }
    activeSnapshot = snapshot
    schedule(snapshot)
  }

  onBeforeUnmount(stopPolling)

  return { pollBusy, pollGeneration, startPolling, stopPolling }
}
