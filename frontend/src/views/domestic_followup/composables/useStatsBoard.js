import { onBeforeUnmount, reactive, ref, toValue } from 'vue'
import { errorMessage } from '../../../utils/errors.js'

function requestState() {
  return reactive({ data: null, loading: false, loaded: false, error: '' })
}

function requestError(error, fallback) {
  const payload = error?.response?.data
  if (error?.response?.status >= 500 && !payload?.detail && !payload?.message) return fallback
  return errorMessage(error, fallback)
}

export function useStatsBoard(api, canReadAll, { pollDelay = 2000, pollAttempts = 300 } = {}) {
  const view = ref('personal'), range = ref('30'), customDates = ref([])
  const person = ref('all'), chart = ref('heat'), aiTab = ref('me'), aiPerson = ref(null)
  const personal = requestState(), team = requestState(), insights = requestState()
  const refreshing = ref(false)
  let personalRun = 0, teamRun = 0, insightRun = 0, disposed = false
  let monitorTimer

  function periodParams() {
    if (range.value === 'custom') {
      const [start, end] = customDates.value || []
      return { range: 'custom', date_from: start, date_to: end }
    }
    return { range: range.value }
  }

  async function loadPersonal() {
    const params = periodParams()
    if (params.range === 'custom' && (!params.date_from || !params.date_to)) return
    const run = ++personalRun
    personal.loading = true
    personal.error = ''
    try {
      const data = await api.personalStats(params)
      if (run !== personalRun || disposed) return
      personal.data = data
      personal.loaded = true
      if (toValue(canReadAll) && (!aiPerson.value || !data.roster.some(user => user.id === aiPerson.value))) {
        aiPerson.value = data.roster[0]?.id || null
      }
    } catch (failure) {
      if (run === personalRun) personal.error = requestError(failure, '个人统计加载失败，请重新加载')
    } finally {
      if (run === personalRun) personal.loading = false
    }
  }

  async function loadTeam() {
    if (!toValue(canReadAll)) return
    const params = periodParams()
    if (params.range === 'custom' && (!params.date_from || !params.date_to)) return
    const run = ++teamRun
    team.loading = true
    team.error = ''
    try {
      const data = await api.teamStats(params)
      if (run !== teamRun || disposed) return
      team.data = data
      team.loaded = true
    } catch (failure) {
      if (run === teamRun) team.error = requestError(failure, '团队统计加载失败，请重新加载')
    } finally {
      if (run === teamRun) team.loading = false
    }
  }

  async function loadInsights() {
    const run = ++insightRun
    const target = toValue(canReadAll) ? aiPerson.value : null
    insights.loading = true
    insights.error = ''
    try {
      const data = await api.insights(target ? { user_id: target } : {})
      if (run !== insightRun || disposed) return false
      insights.data = data
      insights.loaded = true
      clearTimeout(monitorTimer)
      if (data.refresh?.status === 'running' && view.value === 'ai' && !refreshing.value) {
        monitorTimer = setTimeout(() => { if (!disposed) loadInsights() }, 3000)
      }
      return data.refresh?.status !== 'running'
    } catch (failure) {
      if (run === insightRun) insights.error = requestError(failure, 'AI 建议加载失败，请重新加载')
      return true
    } finally {
      if (run === insightRun) insights.loading = false
    }
  }

  async function loadView(key = view.value) {
    if (key === 'personal') return loadPersonal()
    if (key === 'team') return loadTeam()
    return loadInsights()
  }

  function setView(key) {
    if (key === 'team' && !toValue(canReadAll)) return
    view.value = key
    loadView(key)
  }

  function changeRange(value) {
    range.value = value
    if (view.value !== 'ai') loadView()
  }

  function changeCustomDates(dates) {
    customDates.value = dates || []
    range.value = 'custom'
    if (dates?.length === 2 && view.value !== 'ai') loadView()
  }

  function changeAiPerson(value) {
    aiPerson.value = value
    loadInsights()
  }

  async function refreshInsights() {
    if (refreshing.value) return false
    refreshing.value = true
    insights.error = ''
    try {
      const result = await api.refreshInsights(toValue(canReadAll) && aiPerson.value ? { user_id: aiPerson.value } : {})
      for (let attempt = 0; attempt < pollAttempts && !disposed; attempt += 1) {
        await new Promise(resolve => setTimeout(resolve, pollDelay))
        if (disposed) return false
        const jobs = await Promise.all(result.snapshot_ids.map(id => api.insightRefreshStatus(id)))
        if (jobs.some(job => job.status === 'failed')) {
          await loadInsights()
          insights.error = '生成失败，已保留上一份建议。可重新生成。'
          return false
        }
        if (jobs.length && jobs.every(job => job.status === 'done')) {
          await loadInsights()
          return true
        }
      }
      if (!disposed) insights.error = '生成仍在后台进行，请稍后重新加载查看结果。'
      return false
    } catch (failure) {
      insights.error = requestError(failure, '暂时无法查询生成结果，请稍后重新加载；已有建议已保留')
      return false
    } finally {
      if (!disposed) refreshing.value = false
    }
  }

  async function insightFeedback(id, value) {
    await api.insightFeedback(id, value)
    await loadInsights()
  }

  async function insightToTask(id, payload) {
    const result = await api.insightToTask(id, payload)
    await loadInsights()
    return result
  }

  async function adoptInsight(id, note) {
    await api.adoptInsight(id, note)
    await loadInsights()
  }

  onBeforeUnmount(() => {
    disposed = true
    personalRun += 1
    teamRun += 1
    insightRun += 1
    clearTimeout(monitorTimer)
  })

  return {
    view, range, customDates, person, chart, aiTab, aiPerson, personal, team, insights, refreshing,
    periodParams, loadPersonal, loadTeam, loadInsights, loadView, setView, changeRange, changeCustomDates,
    changeAiPerson, refreshInsights, insightFeedback, insightToTask, adoptInsight,
  }
}
