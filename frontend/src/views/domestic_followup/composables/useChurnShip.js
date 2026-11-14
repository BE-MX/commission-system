// 客户流失态势：数据加载、时间偏移（回放 / 推演）、筛选与侧栏清单。渲染层（2D / 3D）只读这里的状态。
import { computed, reactive, ref, shallowRef } from 'vue'
import { apiError } from '@/api/domesticFollowup'
import { buildModel, kpisAt, layoutAt, PROJECTION_DAYS, REPLAY_DAYS } from '../components/stats/churn/shipLayout'

const EMPTY = { regions: [], customers: [], fallen: [], kpis: { critical: 0, within_14: 0, fallen_30: 0 }, rule: {}, owners: [] }

export function useChurnShip(api) {
  const data = shallowRef(null)
  const model = shallowRef(buildModel(EMPTY))
  const state = reactive({ loading: false, error: '', t: 0, version: 0, focus: null, onlySA: false, onlyCritical: false, playing: null })
  const userId = ref(null)
  let run = 0, baseline = null, summary = null, play = null

  async function load(nextUserId = userId.value) {
    userId.value = nextUserId
    const current = ++run
    state.loading = true
    state.error = ''
    try {
      const response = await api.churnMap(nextUserId ? { user_id: nextUserId } : {})
      if (current !== run) return
      data.value = response
      model.value = buildModel(response)
      baseline = layoutAt(model.value, 0)
      setTime(state.t)
    } catch (error) {
      if (current === run) state.error = apiError(error, '客户流失态势加载失败')
    } finally {
      if (current === run) state.loading = false
    }
  }

  function setTime(t) {
    state.t = Math.max(-REPLAY_DAYS, Math.min(PROJECTION_DAYS, t))
    summary = layoutAt(model.value, state.t)
    state.version += 1
  }

  const kpis = computed(() => {
    state.version
    const server = data.value?.kpis || EMPTY.kpis
    if (!data.value) return { critical: 0, within14: 0, fallen: 0 }
    // 今天直接用后端的数；偏移时在后端数上叠加本地推演出的变化
    const now = kpisAt(model.value, state.t), base = kpisAt(model.value, 0)
    return {
      critical: server.critical + now.critical - base.critical,
      within14: server.within_14 + now.within14 - base.within14,
      fallen: server.fallen_30 + now.fallen - base.fallen,
    }
  })

  const regionLabels = computed(() => {
    state.version
    return model.value.regions.map(region => {
      const now = summary?.get(region.key) || { owned: 0, critical: 0, warning: 0, fallen: 0 }, base = baseline?.get(region.key) || now
      return {
        key: region.key, xc: region.xc,
        owned: region.owned + now.owned - base.owned, critical: now.critical,
        publicTotal: region.public_total + now.fallen - base.fallen, fallenRecent: region.fallen_recent + now.fallen - base.fallen,
      }
    })
  })

  const filter = computed(() => {
    if (!state.onlySA && !state.onlyCritical) return null
    return item => (!state.onlySA || item.level === 'S级' || item.level === 'A级') && (!state.onlyCritical || item.tier === 'critical')
  })

  const lists = computed(() => {
    state.version
    const inFocus = item => !state.focus || item.region === state.focus
    const keep = filter.value || (() => true)
    const open = model.value.items.filter(item => item.tier !== 'fallen' && item.tier !== 'stable' && inFocus(item) && keep(item))
      .sort((a, b) => a.remaining - b.remaining)
    return {
      critical: open.filter(item => item.tier === 'critical'),
      warning: open.filter(item => item.tier === 'warning'),
      fallen: model.value.items.filter(item => item.tier === 'fallen' && inFocus(item))
        .sort((a, b) => b.remaining - a.remaining).slice(0, 20),
    }
  })

  const mode = computed(() => (Math.round(state.t) === 0 ? 'live' : state.t < 0 ? 'replay' : 'projection'))

  function startPlay(kind, onFrame) {
    stopPlay()
    if (kind === 'replay') setTime(-REPLAY_DAYS)
    else if (kind === 'projection' && Math.round(state.t) !== 0) setTime(0)
    const target = kind === 'projection' ? PROJECTION_DAYS : 0 // replay / intro 都播到今天
    play = { kind, target, last: performance.now(), frame: 0 }
    state.playing = kind
    const step = now => {
      if (!play) return
      const dt = Math.min((now - play.last) / 1000, 0.05)
      play.last = now
      const next = state.t + dt * 2.1
      setTime(next >= target ? target : next)
      onFrame?.()
      if (next >= target) { play = null; state.playing = null; return }
      play.frame = requestAnimationFrame(step)
    }
    play.frame = requestAnimationFrame(step)
  }
  function stopPlay() {
    if (play) cancelAnimationFrame(play.frame)
    play = null
    state.playing = null
  }

  return { data, model, state, userId, kpis, regionLabels, lists, filter, mode, load, setTime, startPlay, stopPlay }
}
