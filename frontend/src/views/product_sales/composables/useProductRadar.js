/**
 * 产品风向标页面状态：大类标签（B1 / B3 / 50%幅度）× 窗口 × 维度组合 → 排行与涨跌；
 * 大类级 AI 分析；点开某一行看 12 个月走势与其余维度分布。
 * 需求：docs/requirements/2026-11-18-product-sales-radar/README.md（第 8 节）
 */
import { computed, reactive, ref, watch } from 'vue'

import { explainRadarGrade, getRadar, getRadarItem, getRadarScopes } from '@/api/productSales'
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
// 视图预设：前四个是常用视角，「组合」让用户自己勾选维度
export const VIEW_OPTIONS = [
  { value: 'sku', label: '全部 SKU', dims: ['spec', 'color', 'size'] },
  { value: 'color', label: '颜色', dims: ['color'] },
  { value: 'size', label: '尺寸', dims: ['size'] },
  { value: 'spec', label: '规格', dims: ['spec'] },
  { value: 'custom', label: '自定义组合', dims: null },
]

export function useProductRadar() {
  const filters = reactive({
    grade: 'B1', window: 90, view: 'sku', customDims: ['color', 'size'], userId: '', team: '',
  })
  const radar = ref(null)
  const loading = ref(false)
  const error = ref('')
  const scopes = ref({ teams: [], users: [] })
  const table = reactive({ keyword: '', page: 1, pageSize: 20, sortProp: 'kg', sortOrder: 'descending' })
  let latest = 0

  const dims = computed(() => VIEW_OPTIONS.find(v => v.value === filters.view)?.dims || filters.customDims)

  const scopeParams = () => ({
    ...(filters.userId ? { user_id: filters.userId } : {}),
    ...(!filters.userId && filters.team ? { team: filters.team } : {}),
  })

  async function load() {
    if (!dims.value.length) return
    const requestId = ++latest
    loading.value = true
    error.value = ''
    try {
      const data = await getRadar({ grade: filters.grade, window: filters.window, dims: dims.value, ...scopeParams() }, { suppressToast: true })
      if (requestId === latest) {
        const switched = !radar.value || radar.value.grade !== data.grade || radar.value.window.days !== data.window.days
        radar.value = data
        table.page = 1
        // 只在换了大类或窗口时同步服务端已有的分析；切视角、切份额不动页面上的分析和报错
        if (switched && !insight.loading) Object.assign(insight, { data: data.insight || null, error: '' })
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
    } catch { scopes.value = { teams: [], users: [] } }
  }

  const comparable = computed(() => !!radar.value?.credibility?.comparable)

  const filteredRows = computed(() => {
    const keyword = table.keyword.trim().toLowerCase()
    const rows = (radar.value?.rows || []).filter(row => !keyword || row.key.toLowerCase().includes(keyword))
    const { sortProp, sortOrder } = table
    if (!sortProp || !sortOrder) return rows
    const sign = sortOrder === 'ascending' ? 1 : -1
    // 「新出现」的增长率为空，排序时放到最后
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
    Object.assign(table, { sortProp: prop, sortOrder: order, page: 1 })
  }

  const detail = reactive({ visible: false, loading: false, error: '', data: null, values: null })
  // 每次打开新行都换一个序号；旧请求回来时序号不符，不写入当前行的任何状态
  let detailSeq = 0

  async function openItem(row) {
    const seq = ++detailSeq
    Object.assign(detail, { visible: true, loading: true, error: '', data: null, values: row.values })
    try {
      const data = await getRadarItem({ grade: radar.value.grade, window: radar.value.window.days, ...row.values, ...scopeParams() }, { suppressToast: true })
      if (seq === detailSeq) detail.data = data
    } catch (failure) {
      if (seq === detailSeq) detail.error = toErrorMessage(failure)
    } finally {
      if (seq === detailSeq) detail.loading = false
    }
  }

  const insight = reactive({ loading: false, error: '', data: null })
  let insightSeq = 0

  async function explain() {
    const seq = ++insightSeq
    if (!radar.value) return
    // 以页面上正在显示的数据为准，而不是还没加载回来的筛选值
    const target = { grade: radar.value.grade, window: radar.value.window.days }
    const refresh = !!insight.data
    Object.assign(insight, { loading: true, error: '' })
    try {
      const data = await explainRadarGrade({ ...target, refresh })
      // 生成期间切了大类或窗口，结果不属于当前视图，丢弃
      if (seq === insightSeq && target.grade === radar.value?.grade && target.window === radar.value?.window.days) insight.data = data
    } catch (failure) {
      if (seq === insightSeq) insight.error = toErrorMessage(failure, '分析失败，请稍后重试')
    } finally {
      if (seq === insightSeq) insight.loading = false
    }
  }

  // 换大类或窗口：先撤下旧数据，避免新数据回来前（或加载失败时）按旧大类的行去点详情、生成分析
  // 头部信息在切换期间保留：标签 kg 带上所属窗口，窗口不一致时不显示；份额选择器不因重新加载而消失
  const tabs = ref({ days: null, items: [] })
  const canReadAll = ref(false)
  watch(radar, value => {
    if (!value) return
    tabs.value = { days: value.window.days, items: value.tabs }
    canReadAll.value = !!value.share_scope?.can_read_all
  })

  function switchScope() {
    insightSeq += 1
    Object.assign(insight, { loading: false, error: '', data: null })
    radar.value = null
    detail.visible = false
  }

  return {
    filters, dims, radar, tabs, canReadAll, loading, error, scopes, comparable,
    table, filteredRows, pagedRows, onSort,
    detail, insight, load, loadScopes, openItem, explain, switchScope,
  }
}
