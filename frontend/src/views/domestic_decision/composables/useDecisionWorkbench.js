import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { domesticDecisionApi as api } from '@/api/domesticDecision'
import { currentBeijingDate } from '@/utils/datetime'
import { msgError, msgSuccessText, msgWarning } from '@/utils/feedback'
import { cleanQuery, defaultQuery, latestRequestGate, validateQuery } from '../state'

export function useDecisionWorkbench() {
  const options = ref({ dimensions: {}, customers: [], owners: [], permissions: {} })
  const query = reactive(defaultQuery(currentBeijingDate()))
  const applied = ref(null), analysis = ref(null), loading = ref(false), error = ref('')
  const tab = ref('overview'), views = ref([])
  const profile = reactive({ open: false, loading: false, error: '', kind: '', data: null })
  const drill = reactive({ open: false, loading: false, error: '', title: '', kind: 'orders', page: 1, page_size: 20, sort_field: '', sort_order: '', total: 0, items: [], params: {} })
  const qualityOpen = ref(false)
  const gates = { filters: latestRequestGate(), analysis: latestRequestGate(), profile: latestRequestGate(), drill: latestRequestGate() }
  const permissions = computed(() => options.value.permissions || {})
  const tabs = computed(() => [['overview', '经营总览'], ['products', '订单与产品'], ...(permissions.value.finance ? [['finance', '充值与资金']] : []), ['customers', '客户经营'], ['people', '业务员画像'], ['trends', '需求趋势'], ['actions', '行动与简报']])
  function failure(cause) {
    const status = cause.response?.status
    if (status === 409) return '数据或版本已变化，请刷新完整分析后重试'
    if (status === 403) return '当前权限或客户归属已变化，请刷新权限与分析'
    const detail = cause.response?.data?.detail || cause.message
    return typeof detail === 'string' ? detail : '请求失败，请稍后重试'
  }
  async function analyze() {
    const body = cleanQuery(query, options.value), invalid = validateQuery(body)
    if (invalid) { msgWarning(invalid); return }
    const token = gates.analysis.next()
    gates.profile.invalidate(); gates.drill.invalidate(); profile.open = false; drill.open = false
    loading.value = true; error.value = ''; analysis.value = null
    try {
      const data = await api.analyze(body)
      if (!gates.analysis.isCurrent(token)) return
      analysis.value = data; applied.value = JSON.parse(JSON.stringify(body))
    } catch (cause) { if (gates.analysis.isCurrent(token)) error.value = failure(cause) }
    finally { if (gates.analysis.isCurrent(token)) loading.value = false }
  }
  async function refresh() {
    const token = gates.filters.next()
    gates.analysis.invalidate(); gates.profile.invalidate(); gates.drill.invalidate()
    analysis.value = null; profile.open = false; drill.open = false; loading.value = true; error.value = ''
    try {
      const nextOptions = await api.filters()
      if (!gates.filters.isCurrent(token)) return
      options.value = nextOptions
      Object.assign(query, cleanQuery(query, options.value))
      if (tab.value === 'finance' && !permissions.value.finance) tab.value = 'overview'
      await analyze()
    } catch (cause) { if (gates.filters.isCurrent(token)) { error.value = failure(cause); loading.value = false; if (cause.response?.status === 403) options.value = { dimensions: {}, customers: [], owners: [], permissions: {} } } }
  }
  async function loadViews() {
    try { views.value = await api.views() } catch (cause) { msgError(failure(cause), cause) }
  }
  async function openProfile(kind, id) {
    if (!id) { msgWarning('未分配负责人，暂不能打开人员画像'); return }
    const token = gates.profile.next()
    Object.assign(profile, { open: true, kind, loading: true, error: '', data: null })
    try {
      const data = await api[kind](id, { start_date: applied.value.start_date, end_date: applied.value.end_date })
      if (gates.profile.isCurrent(token) && profile.open) profile.data = data
    } catch (cause) { if (gates.profile.isCurrent(token)) profile.error = failure(cause) }
    finally { if (gates.profile.isCurrent(token)) profile.loading = false }
  }
  async function loadRows() {
    const token = gates.drill.next(); drill.loading = true; drill.error = ''
    try {
      const data = await api.rows(analysis.value.meta.run_id, { kind: drill.kind, page: drill.page, page_size: drill.page_size, ...drill.params, ...(drill.sort_field && drill.sort_order ? { sort_field: drill.sort_field, sort_order: drill.sort_order } : {}) })
      if (!gates.drill.isCurrent(token) || !drill.open) return
      drill.items = data.items; drill.total = data.total
    } catch (cause) { if (gates.drill.isCurrent(token)) drill.error = failure(cause) }
    finally { if (gates.drill.isCurrent(token)) drill.loading = false }
  }
  function openRows(kind = 'orders', params = {}, title = '分析明细') {
    Object.assign(drill, { open: true, kind, page: 1, sort_field: '', sort_order: '', items: [], total: 0, params, title }); loadRows()
  }
  async function mutate(work, success) {
    try { const result = await work(); if (success) msgSuccessText(success); return result }
    catch (cause) { msgError(failure(cause), cause); if ([403, 409].includes(cause.response?.status)) await refresh(); throw cause }
  }
  onBeforeUnmount(() => Object.values(gates).forEach(gate => gate.invalidate()))
  return { options, query, applied, analysis, loading, error, tab, tabs, permissions, views, profile, drill, qualityOpen, analyze, refresh, loadViews, openProfile, openRows, loadRows, mutate, failure }
}
