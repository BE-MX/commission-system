import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useAsyncResource } from '@/composables/useAsyncResource.js'
import { currentBeijingDate } from '@/utils/datetime.js'
import { devlogApi } from '@/api/devlog.js'
import { rangeFor } from '../devlogPresentation.js'

export function useDevlogBoard() {
  const today = currentBeijingDate()
  const filters = reactive({ range: 'week', custom: [], type: '', module: '', agent: '' })
  const tab = ref('board')
  const focus = ref('')
  const showStale = ref(false)
  const drawer = reactive({ open: false, id: null })
  const period = computed(() => filters.range === 'custom' && filters.custom?.length === 2
    ? { start: filters.custom[0], end: filters.custom[1] }
    : rangeFor(filters.range === 'custom' ? 'week' : filters.range, today))
  const summary = useAsyncResource((params, { signal }) => devlogApi.summary(params, { signal }).then(r => r.data),
    { initialData: { kpis: {}, columns: { dev: [], committed: [], released: [] }, timeline: [] } })
  const health = useAsyncResource((_, { signal }) => devlogApi.health({ signal }).then(r => r.data))
  const pending = useAsyncResource((_, { signal }) => devlogApi.pending({ signal }).then(r => r.data.items), { initialData: [] })
  const detail = useAsyncResource((id, { signal }) => devlogApi.item(id, { signal }).then(r => r.data))
  // 只有健康信息真正加载成功才判断过期；加载中或请求失败不冒充「开发机未上报」
  const syncState = computed(() => {
    if (health.error.value) return 'unknown'
    if (!health.hasLoaded.value) return 'loading'
    if (!health.data.value?.last_sync_at) return 'never'
    return health.data.value.is_stale ? 'stale' : 'fresh'
  })
  const stale = computed(() => syncState.value === 'stale' || syncState.value === 'never' || syncState.value === 'unknown' || !!health.data.value?.ledger_pending_check || summary.isStale.value || pending.isStale.value)
  const pendingReleaseCount = computed(() => filteredPending.value.filter(item => item.status === 'pending_release').length)

  function load() {
    summary.load({ ...period.value, type: filters.type, module: filters.module, agent: filters.agent })
  }
  function openItem(id) {
    drawer.id = id; drawer.open = true
    detail.load(id, { clear: true })
  }
  function pickKpi(key) {
    focus.value = focus.value === key ? '' : key
    tab.value = key === 'pending_release' ? 'pending' : 'board'
  }
  const focusMatch = item => {
    if (focus.value === 'features') return item.status === 'released' && ['feature', 'improve'].includes(item.type)
    if (focus.value === 'bugs') return item.status === 'released' && item.type === 'bug'
    if (focus.value === 'data') return item.status === 'released' && item.type === 'data'
    if (focus.value === 'dev') return item.status === 'dev'
    return true
  }
  const visibleColumns = computed(() => Object.fromEntries(['dev', 'committed', 'released'].map(key => [key,
    (summary.data.value.columns[key] || []).filter(focusMatch)])))
  const staleColumns = computed(() => Object.fromEntries(['dev', 'committed', 'released'].map(key => [key,
    (summary.data.value.stale_columns?.[key] || []).filter(focusMatch)])))
  const filteredPending = computed(() => pending.data.value.filter(item =>
    (!filters.type || item.type === filters.type) && (!filters.module || item.module === filters.module)
    && (!filters.agent || item.agent === filters.agent)))
  watch(() => [filters.type, filters.module, filters.agent], () => { focus.value = '' })
  watch(() => [period.value.start, period.value.end, filters.type, filters.module, filters.agent], load)
  const refreshing = computed(() => summary.loading.value || health.loading.value || pending.loading.value)
  function refresh() { load(); health.load(); pending.load() }
  onMounted(refresh)
  return { today, filters, tab, focus, showStale, visibleColumns, staleColumns, filteredPending, drawer, period, summary, health, pending, detail, stale, syncState, pendingReleaseCount, openItem, pickKpi, load, refresh, refreshing }
}
