/**
 * 产品风向标页面状态：窗口/型号/份额范围 → 风向数据；点开某款 → 走势、分布与 AI 解读。
 * 需求：docs/requirements/2026-11-18-product-sales-radar/README.md（P1）
 */
import { computed, reactive, ref } from 'vue'

import { explainRadarItem, getRadar, getRadarItem, getRadarScopes } from '@/api/productSales'
import { errorMessage as toErrorMessage } from '@/utils/errors'

export const WINDOW_OPTIONS = [
  { value: 30, label: '近 30 天' },
  { value: 90, label: '近 90 天' },
  { value: 180, label: '近 180 天' },
]

export function useProductRadar() {
  const filters = reactive({ window: 90, models: [], userId: '', team: '' })
  const radar = ref(null)
  const loading = ref(false)
  const error = ref('')
  const scopes = ref({ teams: [], users: [] })
  let latest = 0

  const scopeParams = () => ({
    ...(filters.userId ? { user_id: filters.userId } : {}),
    ...(!filters.userId && filters.team ? { team: filters.team } : {}),
  })

  async function load() {
    const requestId = ++latest
    loading.value = true
    error.value = ''
    try {
      const data = await getRadar({ window: filters.window, models: filters.models, ...scopeParams() }, { suppressToast: true })
      if (requestId === latest) radar.value = data
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

  const detail = reactive({ visible: false, loading: false, error: '', data: null, dimension: '', key: '' })
  const insight = reactive({ loading: false, error: '', data: null })
  // 每次打开新款都换一个序号；旧请求回来时序号不符，不写入当前款的任何状态
  let detailSeq = 0

  async function openItem(dimension, key) {
    const seq = ++detailSeq
    Object.assign(detail, { visible: true, loading: true, error: '', data: null, dimension, key })
    Object.assign(insight, { loading: false, error: '', data: null })
    try {
      const data = await getRadarItem({ dimension, key, window: filters.window, ...scopeParams() }, { suppressToast: true })
      if (seq === detailSeq) detail.data = data
    } catch (failure) {
      if (seq === detailSeq) detail.error = toErrorMessage(failure)
    } finally {
      if (seq === detailSeq) detail.loading = false
    }
  }

  async function explain() {
    const seq = detailSeq
    const refresh = !!insight.data
    Object.assign(insight, { loading: true, error: '', data: null })
    try {
      const data = await explainRadarItem({ dimension: detail.dimension, key: detail.key, window: filters.window, refresh, ...scopeParams() })
      if (seq === detailSeq) insight.data = data
    } catch (failure) {
      if (seq === detailSeq) insight.error = toErrorMessage(failure, '解读失败，请稍后重试')
    } finally {
      if (seq === detailSeq) insight.loading = false
    }
  }

  return { filters, radar, loading, error, scopes, comparable, detail, insight, load, loadScopes, openItem, explain }
}
