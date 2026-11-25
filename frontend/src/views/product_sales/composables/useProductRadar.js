/**
 * 产品风向标页面状态：大类标签（B1 / B3 / 50%幅度）× 窗口 × 维度组合 → 排行与涨跌；
 * 大类级 AI 分析（带冷却期感知）；点开某一行看 12 个月走势、下钻维度与上下项切换。
 * 需求：docs/requirements/2026-11-18-product-sales-radar/README.md（第 8 节）
 */
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { explainRadarGrade, getRadar, getRadarItem, getRadarScopes } from '@/api/productSales'
import { parseApiDateTime } from '@/utils/datetime'
import { errorMessage as toErrorMessage } from '@/utils/errors'

export const WINDOW_OPTIONS = [30, 60, 90, 180].map(value => ({ value, label: `近 ${value} 天` }))
export const GRADE_OPTIONS = [
  { value: 'B1', label: 'B1' },
  { value: 'B3', label: 'B3' },
  { value: '50', label: '50%幅度' },
]
export const DIMENSIONS = [
  { value: 'spec', label: '规格' },
  { value: 'color', label: '颜色' },
  { value: 'size', label: '尺寸' },
]
// 视图预设：前四个是常用视角，「自定义组合」让用户自由勾选维度
export const VIEW_OPTIONS = [
  { value: 'sku', label: '全部 SKU', dims: ['spec', 'color', 'size'] },
  { value: 'color', label: '颜色', dims: ['color'] },
  { value: 'size', label: '尺寸', dims: ['size'] },
  { value: 'spec', label: '规格', dims: ['spec'] },
  { value: 'custom', label: '自定义组合', dims: null },
]
export const QUICK_FILTERS = [
  { value: 'all', label: '全部' },
  { value: 'up', label: '上涨' },
  { value: 'down', label: '下跌' },
  { value: 'new', label: '新上榜' },
  { value: 'opportunity', label: '我未卖过' },
]

const VALID_GRADES = new Set(GRADE_OPTIONS.map(g => g.value))
const VALID_WINDOWS = new Set(WINDOW_OPTIONS.map(w => w.value))
const VALID_DIMS = new Set(DIMENSIONS.map(d => d.value))
const VALID_VIEWS = new Set(VIEW_OPTIONS.map(v => v.value))

export function matchPresetView(selectedDims) {
  const key = [...selectedDims].sort().join(',')
  const preset = VIEW_OPTIONS.find(v => v.dims && [...v.dims].sort().join(',') === key)
  return preset ? preset.value : 'custom'
}

export function isNewAppearance(row) {
  return row && Number(row.kg) > 0 && Number(row.prev_kg || 0) <= 0
}

function readInitialFilters(query) {
  const grade = VALID_GRADES.has(String(query?.grade || '')) ? String(query.grade) : 'B1'
  const rawWindow = Number(query?.window)
  const window = VALID_WINDOWS.has(rawWindow) ? rawWindow : 90
  const rawView = String(query?.view || '')
  let view = VALID_VIEWS.has(rawView) ? rawView : 'sku'
  let customDims = ['color', 'size']
  if (query?.dims) {
    const parsed = String(query.dims).split(',').filter(d => VALID_DIMS.has(d))
    if (parsed.length) {
      customDims = parsed
      const matched = matchPresetView(parsed)
      view = matched
    }
  }
  return { grade, window, view, customDims }
}

export function useProductRadar() {
  const route = useRoute()
  const router = useRouter()
  const initial = readInitialFilters(route?.query)
  const filters = reactive({
    grade: initial.grade,
    window: initial.window,
    view: initial.view,
    customDims: initial.customDims,
    // 统一单选份额值：''=我 / 'team:<name>' / 'user:<id>'
    scopeKey: '',
  })

  const radar = ref(null)
  const loading = ref(false)
  const loadingKind = ref('scope') // 'scope' | 'view'
  const error = ref('')
  const scopes = ref({ teams: [], users: [] })
  const table = reactive({
    keyword: '',
    quickFilter: 'all',
    page: 1,
    pageSize: 20,
    sortProp: 'kg',
    sortOrder: 'descending',
  })
  let latest = 0

  const scopeLoading = computed(() => loading.value && loadingKind.value === 'scope')
  const viewLoading = computed(() => loading.value && loadingKind.value === 'view')
  const dims = computed(() => VIEW_OPTIONS.find(v => v.value === filters.view)?.dims || filters.customDims)

  const scopeParams = () => {
    const key = String(filters.scopeKey || '')
    if (key.startsWith('user:')) return { user_id: key.slice(5) }
    if (key.startsWith('team:')) return { team: key.slice(5) }
    return {}
  }

  function syncUrl() {
    if (!router || !route || route.path !== '/customer-hub/product-radar') return
    const next = {
      grade: filters.grade,
      window: String(filters.window),
      view: filters.view,
      ...(filters.view === 'custom' ? { dims: filters.customDims.join(',') } : {}),
    }
    const cur = route.query || {}
    const same = cur.grade === next.grade && cur.window === next.window
      && cur.view === next.view && (cur.dims || undefined) === next.dims
    if (!same) router.replace({ query: next }).catch(() => {})
  }

  function onCustomDimsChange() {
    if (!filters.customDims.length) return
    const matched = matchPresetView(filters.customDims)
    if (matched !== 'custom') filters.view = matched
    load('view')
  }

  async function load(kind = 'scope') {
    if (!dims.value.length) return
    syncUrl()
    const requestId = ++latest
    loadingKind.value = kind
    loading.value = true
    error.value = ''
    try {
      const data = await getRadar({ grade: filters.grade, window: filters.window, dims: dims.value, ...scopeParams() }, { suppressToast: true })
      if (requestId === latest) {
        const switched = !radar.value || radar.value.grade !== data.grade || radar.value.window.days !== data.window.days
        radar.value = data
        table.page = 1
        // 切视角且原先排序列不在新列中时回归默认 kg 降序
        if (table.sortProp?.startsWith('dim:') && !data.dims.includes(table.sortProp.slice(4))) {
          table.sortProp = 'kg'
          table.sortOrder = 'descending'
        }
        // 未绑定份额且开启了「我未卖过」时回退为全部
        if (data.summary?.my_kg === null && table.quickFilter === 'opportunity') {
          table.quickFilter = 'all'
        }
        // 只在换了大类或窗口时同步服务端已有的分析；切视角、切份额不动页面上的分析和报错
        if (switched && !insight.loading) {
          Object.assign(insight, { data: data.insight || null, error: '' })
        }
      }
    } catch (failure) {
      if (requestId === latest) error.value = toErrorMessage(failure)
    } finally {
      if (requestId === latest) loading.value = false
    }
  }

  async function loadScopes() {
    try {
      scopes.value = await getRadarScopes({ window: filters.window }, { suppressToast: true })
      // 切换时间窗口后，若原先选中的团队/业务员在新窗口无销量，自动回退到「我」避免无效口径
      if (filters.scopeKey) {
        const validTeam = filters.scopeKey.startsWith('team:') && scopes.value.teams.includes(filters.scopeKey.slice(5))
        const validUser = filters.scopeKey.startsWith('user:') && scopes.value.users.some(u => String(u.user_id) === filters.scopeKey.slice(5))
        if (!validTeam && !validUser) {
          filters.scopeKey = ''
          load('scope')
        }
      }
    } catch { scopes.value = { teams: [], users: [] } }
  }

  const comparable = computed(() => !!radar.value?.credibility?.comparable)

  const quickFilterCounts = computed(() => {
    const all = radar.value?.rows || []
    let up = 0; let down = 0; let fresh = 0; let opportunity = 0
    for (const row of all) {
      if (row.delta_kg > 0) up += 1
      else if (row.delta_kg < 0) down += 1
      if (row.rank && !row.prev_rank) fresh += 1
      if (row.kg > 0 && row.my_kg === 0) opportunity += 1
    }
    return { all: all.length, up, down, new: fresh, opportunity }
  })

  const filteredRows = computed(() => {
    const keyword = table.keyword.trim().toLowerCase()
    const qf = table.quickFilter
    const rows = (radar.value?.rows || []).filter(row => {
      if (keyword && !row.key.toLowerCase().includes(keyword)) return false
      if (qf === 'up') return row.delta_kg > 0
      if (qf === 'down') return row.delta_kg < 0
      if (qf === 'new') return Boolean(row.rank && !row.prev_rank)
      if (qf === 'opportunity') return row.kg > 0 && row.my_kg === 0
      return true
    })
    const { sortProp, sortOrder } = table
    if (!sortProp || !sortOrder) return rows
    const sign = sortOrder === 'ascending' ? 1 : -1
    if (sortProp.startsWith('dim:')) {
      const dim = sortProp.slice(4)
      return [...rows].sort((a, b) => {
        const left = a.values?.[dim] ?? ''
        const right = b.values?.[dim] ?? ''
        if (!left && !right) return 0
        if (!left) return 1
        if (!right) return -1
        return String(left).localeCompare(String(right), 'zh-CN', { numeric: true }) * sign
      })
    }
    // 「新出现」的增长率或本期无排名项为空，排序时始终置末
    const value = row => (row[sortProp] === null || row[sortProp] === undefined ? null : row[sortProp])
    return [...rows].sort((a, b) => {
      const left = value(a)
      const right = value(b)
      if (left === right) return 0
      if (left === null) return 1
      if (right === null) return -1
      return (left - right) * sign
    })
  })

  const pagedRows = computed(() => filteredRows.value.slice((table.page - 1) * table.pageSize, table.page * table.pageSize))

  function onSort({ prop, order }) {
    if (!order) {
      Object.assign(table, { sortProp: 'kg', sortOrder: 'descending', page: 1 })
      return
    }
    Object.assign(table, { sortProp: prop, sortOrder: order, page: 1 })
  }

  function resetTableFilters() {
    table.keyword = ''
    table.quickFilter = 'all'
    table.page = 1
  }

  // 详情抽屉：支持下钻栈（点击「主要规格/颜色/尺寸」进入子组合）与列表上一项/下一项切换
  const detail = reactive({
    visible: false,
    loading: false,
    error: '',
    data: null,
    values: null,
    history: [],
    navList: [],
    navIndex: -1,
  })
  // 每次打开新行都换一个序号；旧请求回来时序号不符，不写入当前行的任何状态
  let detailSeq = 0

  async function fetchDetail(values, { preserveData = false } = {}) {
    if (!radar.value) return
    const seq = ++detailSeq
    Object.assign(detail, {
      visible: true,
      loading: true,
      error: '',
      values,
      ...(preserveData ? {} : { data: null }),
    })
    try {
      const data = await getRadarItem({ grade: radar.value.grade, window: radar.value.window.days, ...values, ...scopeParams() }, { suppressToast: true })
      if (seq === detailSeq) detail.data = data
    } catch (failure) {
      if (seq === detailSeq) detail.error = toErrorMessage(failure)
    } finally {
      if (seq === detailSeq) detail.loading = false
    }
  }

  async function openItem(row, navList = null) {
    // 加载中（含切换大类或窗口后）的行属于旧数据，不允许点开
    if (loading.value || !radar.value) return
    const seq = ++detailSeq
    const list = Array.isArray(navList) ? navList : filteredRows.value
    const idx = row.key ? list.findIndex(item => item.key === row.key) : -1
    Object.assign(detail, {
      visible: true,
      loading: true,
      error: '',
      data: null,
      values: row.values,
      history: [],
      navList: list,
      navIndex: idx,
    })
    try {
      const data = await getRadarItem({ grade: radar.value.grade, window: radar.value.window.days, ...row.values, ...scopeParams() }, { suppressToast: true })
      if (seq === detailSeq) detail.data = data
    } catch (failure) {
      if (seq === detailSeq) detail.error = toErrorMessage(failure)
    } finally {
      if (seq === detailSeq) detail.loading = false
    }
  }

  function drillDown(dim, name) {
    if (!detail.values || !radar.value) return
    detail.history = [...detail.history, detail.values]
    const nextValues = { ...detail.values, [dim]: name }
    fetchDetail(nextValues, { preserveData: true })
  }

  function drillBack() {
    if (!detail.history.length) return
    const prev = detail.history[detail.history.length - 1]
    detail.history = detail.history.slice(0, -1)
    fetchDetail(prev, { preserveData: true })
  }

  function stepDetail(delta) {
    if (detail.history.length || detail.navIndex < 0) return
    const nextIdx = detail.navIndex + delta
    if (nextIdx < 0 || nextIdx >= detail.navList.length) return
    detail.navIndex = nextIdx
    fetchDetail(detail.navList[nextIdx].values, { preserveData: true })
  }

  function pivotToSpecFilter() {
    if (!detail.values) return
    const nonSpec = Object.entries(detail.values).filter(([k]) => k !== 'spec')
    const nextDims = ['spec', ...nonSpec.map(([k]) => k)]
    const matched = matchPresetView(nextDims)
    filters.customDims = nextDims
    filters.view = matched
    table.keyword = nonSpec.map(([, v]) => v).join(' ')
    table.quickFilter = 'all'
    detail.visible = false
    load('view')
  }

  const insight = reactive({ loading: false, error: '', data: null, expanded: true })
  let insightSeq = 0

  // 实时跟踪冷却剩余秒数，到期自动解禁刷新按钮
  const nowTick = ref(Date.now())
  const tickTimer = setInterval(() => { nowTick.value = Date.now() }, 15000)
  onBeforeUnmount(() => clearInterval(tickTimer))

  const cooldownRemainingSeconds = computed(() => {
    const until = parseApiDateTime(insight.data?.cooldown_until)
    if (!until) return 0
    return Math.max(0, Math.ceil((until.getTime() - nowTick.value) / 1000))
  })
  const inCooldown = computed(() => cooldownRemainingSeconds.value > 0)

  async function explain() {
    if (loading.value || !radar.value) return
    if (insight.data && inCooldown.value) return
    const seq = ++insightSeq
    // 以页面上正在显示的数据为准，而不是还没加载回来的筛选值
    const target = { grade: radar.value.grade, window: radar.value.window.days }
    const refresh = !!insight.data
    Object.assign(insight, { loading: true, error: '', expanded: true })
    try {
      const data = await explainRadarGrade({ ...target, refresh })
      // 生成期间切了大类或窗口，结果不属于当前视图，丢弃
      if (seq === insightSeq && target.grade === radar.value?.grade && target.window === radar.value?.window.days) {
        insight.data = data
        nowTick.value = Date.now()
      }
    } catch (failure) {
      if (seq === insightSeq) insight.error = toErrorMessage(failure, '分析失败，请稍后重试')
    } finally {
      if (seq === insightSeq) insight.loading = false
    }
  }

  // 换大类或窗口：旧内容保留并淡出（不整页清空，避免跳动），加载期间禁止点行和生成分析，
  // 防止新数据回来前按旧大类的行去点详情、生成分析
  // 标签 kg 带上所属窗口，窗口不一致时仍保留旧值淡化防抖动；份额选择器不因重新加载而消失
  const tabs = ref({ days: null, items: [] })
  const canReadAll = ref(false)
  watch(radar, value => {
    if (!value) return
    tabs.value = { days: value.window.days, items: value.tabs }
    canReadAll.value = !!value.share_scope?.can_read_all
  })

  function switchScope() {
    insightSeq += 1
    Object.assign(insight, { loading: false, error: '' })
    detail.visible = false
  }

  return {
    filters, dims, radar, tabs, canReadAll, loading, scopeLoading, viewLoading, error, scopes, comparable,
    table, quickFilterCounts, filteredRows, pagedRows, onSort, resetTableFilters, onCustomDimsChange,
    detail, insight, inCooldown, cooldownRemainingSeconds,
    load, loadScopes, openItem, drillDown, drillBack, stepDetail, pivotToSpecFilter, explain, switchScope,
  }
}
