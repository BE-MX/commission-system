import { onBeforeUnmount, ref } from 'vue'
import {
  getRadarHealth, getRadarJob, getRadarSettings, ingestRadar,
  listRadarSubscriptions, selectRadarCandidates,
} from '@/api/projectRadar'
import { useListPage } from '@/composables/useListPage'
import { msgError, msgSuccess } from '@/utils/feedback'

export function useProjectRadar() {
  const counts = ref({ all: 0, updates: 0, inbox: 0, trying: 0, adopted: 0, dropped: 0 })
  const health = ref(null)
  const settings = ref(null)
  const pendingJobs = ref([])
  const candidateJob = ref(null)
  const selectedCandidates = ref([])
  const initialViewResolved = ref(false)
  let pollTimer = null

  const listState = useListPage(async ({ page, page_size, ...form }, { signal, isCurrent }) => {
    const params = { page, page_size }
    for (const key of ['view', 'keyword', 'item_type', 'module', 'read_state']) {
      if (form[key]) params[key] = form[key]
    }
    const response = await listRadarSubscriptions(params, { signal, suppressToast: true })
    const data = response.data || {}
    if (!isCurrent()) return data
    counts.value = data.counts || counts.value
    if (!initialViewResolved.value) {
      initialViewResolved.value = true
      if (listState.searchForm.view === 'updates' && !counts.value.updates) {
        listState.searchForm.view = 'all'
        queueMicrotask(listState.handleSearch)
      }
    }
    return data
  }, {
    searchForm: { view: 'updates', keyword: '', item_type: '', module: '', read_state: '' },
    pageSize: 20,
  })

  async function loadAuxiliary() {
    const [healthResponse, settingsResponse] = await Promise.all([getRadarHealth(), getRadarSettings()])
    health.value = healthResponse.data
    settings.value = settingsResponse.data
  }

  async function refresh() {
    await Promise.all([listState.fetchList(), loadAuxiliary()])
  }

  function stopPolling() {
    if (pollTimer) clearTimeout(pollTimer)
    pollTimer = null
  }

  function schedulePoll() {
    stopPolling()
    if (!pendingJobs.value.length) return
    pollTimer = setTimeout(pollJobs, 1800)
  }

  async function pollJobs() {
    const active = [...pendingJobs.value]
    await Promise.all(active.map(async pending => {
      try {
        const response = await getRadarJob(pending.id)
        const job = response.data
        if (['completed', 'partial', 'failed', 'awaiting_choice'].includes(job.status)) {
          pendingJobs.value = pendingJobs.value.filter(item => item.id !== job.id)
          if (job.status === 'awaiting_choice') {
            candidateJob.value = job
            selectedCandidates.value = (job.candidates || []).map((item, index) => item.confirmed ? index + 1 : null).filter(Boolean)
          }
          if (job.status === 'failed') msgError(job.error || '收录失败，可稍后重试')
          await refresh()
        }
      } catch {
        return
      }
    }))
    schedulePoll()
  }

  async function capture(rawInput) {
    const text = rawInput.trim()
    if (!text) return
    try {
      const response = await ingestRadar(text)
      const job = response.data
      pendingJobs.value = [{ ...job, raw_input: text }, ...pendingJobs.value]
      listState.searchForm.view = 'all'
      await listState.handleSearch()
      schedulePoll()
    } catch {
      return
    }
  }

  async function chooseCandidates() {
    if (!candidateJob.value || !selectedCandidates.value.length) return
    const selection = selectedCandidates.value.join(' ')
    await selectRadarCandidates(candidateJob.value.id, selection)
    candidateJob.value = null
    msgSuccess('选中的项目已收录')
    await refresh()
  }

  function cancelCandidates() {
    candidateJob.value = null
  }

  onBeforeUnmount(stopPolling)

  return {
    listState, counts, health, settings, pendingJobs, candidateJob, selectedCandidates,
    refresh, loadAuxiliary, capture, chooseCandidates, cancelCandidates,
  }
}
