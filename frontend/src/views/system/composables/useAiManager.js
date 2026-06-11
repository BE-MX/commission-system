/**
 * AI 管理页 — 业务逻辑 composable
 *
 * 集中三个 tab (Provider / Preset / Log) 的 state + 方法:
 *   - Provider CRUD + 启用切换 + 连通性测试
 *   - Preset CRUD + 复制 + 单条测试
 *   - Log 查询 + 摘要 + 模块/状态/日期筛选
 *
 * Preset 依赖 providerOptions (Provider tab 加载后填充),所以三个 tab 共享一个 composable。
 */
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getProviders, createProvider, updateProvider, deleteProvider, testProvider,
  getPresets, createPreset, updatePreset, deletePreset, testPreset,
  getLogs,
} from '@/api/ai'
import { useTableSort } from '@/composables/useTableSort'

const MODULE_LABELS = {
  logistics: '物流跟踪',
  design_booking: '设计预约',
  commission: '提成管理',
  system: '系统管理',
}


// ── 状态/标签 工具函数 ─────────────────────────────────────


function moduleLabel(code) {
  return MODULE_LABELS[code] || code
}

function statusLabel(status) {
  const map = { success: '成功', error: '错误', timeout: '超时', pending: '进行中' }
  return map[status] || status
}

function statusTagType(status) {
  const map = { success: 'success', error: 'danger', timeout: 'warning', pending: 'primary' }
  return map[status] || 'info'
}

function formatDuration(ms) {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${ms}ms`
}

function formatToken(n) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return String(n)
}


// ── composable ──────────────────────────────────────────


export function useAiManager() {
  const activeTab = ref('providers')

  // ── Providers ─────────────────────────────────────────
  const providers = ref([])
  const providerLoading = ref(false)
  const providerSearch = ref('')
  const providerTypeFilter = ref('')
  const providerStatusFilter = ref('')
  const showKeyMap = ref({})
  const testingId = ref(null)
  const testResultVisible = ref(false)
  const testResultData = ref(null)

  const providerDialogVisible = ref(false)
  const providerEditId = ref(null)
  const providerFormRef = ref(null)
  const providerSaving = ref(false)
  const providerForm = ref({
    name: '', provider_type: 'direct', api_base: '', api_key: '', api_type: 'openai', timeout_sec: 60, remark: '',
  })
  const providerRules = {
    name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
    provider_type: [{ required: true, message: '请选择类型', trigger: 'change' }],
    api_base: [
      { required: true, message: '请输入 API Base', trigger: 'blur' },
      { pattern: /^https?:\/\/.+/, message: '必须以 http:// 或 https:// 开头', trigger: 'blur' },
    ],
  }

  // ── Presets ───────────────────────────────────────────
  const presets = ref([])
  const presetLoading = ref(false)
  const presetSearch = ref('')
  const presetProviderFilter = ref('')
  const providerOptions = ref([])

  const presetDialogVisible = ref(false)
  const presetEditId = ref(null)
  const presetFormRef = ref(null)
  const presetSaving = ref(false)
  const presetForm = ref({
    preset_name: '', provider_id: '', model: '', system_prompt: '', parameters: '{}', description: '',
  })
  const presetRules = {
    preset_name: [
      { required: true, message: '请输入预设名称', trigger: 'blur' },
      { pattern: /^[a-zA-Z0-9_]+$/, message: '只允许字母、数字、下划线', trigger: 'blur' },
    ],
    provider_id: [{ required: true, message: '请选择提供商', trigger: 'change' }],
  }
  const isAccioProvider = computed(() => {
    const p = providerOptions.value.find(x => x.id === presetForm.value.provider_id)
    return p?.provider_type === 'accio_work'
  })

  // 单条 Preset 测试 (内嵌 sandbox)
  const testDialogVisible = ref(false)
  const testPresetName = ref('')
  const testPresetId = ref(null)
  const testMessage = ref('')
  const testing = ref(false)
  const testResult = ref(null)

  // ── Logs ──────────────────────────────────────────────
  const logsData = ref([])
  const logsLoading = ref(false)
  const logSearch = ref('')
  const logModuleFilter = ref('')
  const logStatusFilter = ref('')
  const logDateRange = ref([])
  const logPage = ref(1)
  const logPageSize = ref(20)
  const logTotal = ref(0)
  const logSummaryData = ref({ tokens_total: 0, success_count: 0, error_count: 0, timeout_count: 0, avg_duration_ms: 0 })
  const logSort = useTableSort()

  // ── Computed ──────────────────────────────────────────
  const stats = computed(() => {
    const directCount = providers.value.filter(p => p.provider_type === 'direct').length
    const accioCount = providers.value.filter(p => p.provider_type === 'accio_work').length
    const enabledPresets = presets.value.filter(p => p.is_enabled).length
    return [
      { label: '提供商', value: String(providers.value.length), icon: 'Cpu', color: '#2563eb', bg: '#eff6ff10', sub: `${directCount} 直连 + ${accioCount} ACCIO` },
      { label: '调用预设', value: String(presets.value.length), icon: 'Monitor', color: '#7c3aed', bg: '#f5f3ff10', sub: `${enabledPresets} 启用 + ${presets.value.length - enabledPresets} 禁用` },
      { label: '今日调用', value: String(logSummaryData.value.success_count + logSummaryData.value.error_count + logSummaryData.value.timeout_count), icon: 'Lightning', color: '#b08d4f', bg: '#fef7e810', sub: `成功率 ${logTotal.value > 0 ? Math.round((logSummaryData.value.success_count / logTotal.value) * 100) : 0}%` },
      { label: 'Token 消耗', value: formatToken(logSummaryData.value.tokens_total), icon: 'Histogram', color: '#059669', bg: '#ecfdf510', sub: '本月累计' },
    ]
  })

  const filteredProviders = computed(() => {
    return providers.value.filter(p => {
      const matchSearch = !providerSearch.value ||
        p.name.toLowerCase().includes(providerSearch.value.toLowerCase()) ||
        p.api_base.toLowerCase().includes(providerSearch.value.toLowerCase())
      const matchType = !providerTypeFilter.value || p.provider_type === providerTypeFilter.value
      const matchStatus = providerStatusFilter.value === '' || p.is_enabled === providerStatusFilter.value
      return matchSearch && matchType && matchStatus
    })
  })

  const filteredPresets = computed(() => {
    return presets.value.filter(p => {
      const matchSearch = !presetSearch.value ||
        p.preset_name.toLowerCase().includes(presetSearch.value.toLowerCase()) ||
        (p.description && p.description.toLowerCase().includes(presetSearch.value.toLowerCase()))
      const matchProv = !presetProviderFilter.value || p.provider_id === presetProviderFilter.value
      return matchSearch && matchProv
    })
  })

  const logSummary = computed(() => {
    const s = logSummaryData.value
    return [
      { label: '调用次数', value: String(logTotal.value), icon: 'Histogram', color: '#2563eb' },
      { label: '成功', value: String(s.success_count), icon: 'SuccessFilled', color: '#059669' },
      { label: '错误', value: String(s.error_count), icon: 'CircleCloseFilled', color: '#dc2626' },
      { label: '超时', value: String(s.timeout_count), icon: 'WarningFilled', color: '#d97706' },
      { label: '总 Token', value: s.tokens_total.toLocaleString(), icon: 'Histogram', color: '#7c3aed' },
      { label: '平均耗时', value: `${s.avg_duration_ms}ms`, icon: 'Loading', color: '#0891b2' },
    ]
  })

  // ── Provider methods ──────────────────────────────────
  async function fetchProviders() {
    providerLoading.value = true
    try {
      const res = await getProviders()
      providers.value = res.data.items || []
      providerOptions.value = res.data.items.map(p => ({ id: p.id, name: p.name, provider_type: p.provider_type }))
    } catch (e) { /* ignore */ }
    providerLoading.value = false
  }

  function openProviderDialog(row = null) {
    providerEditId.value = row?.id || null
    providerForm.value = row
      ? { ...row, api_key: '' }
      : { name: '', provider_type: 'direct', api_base: '', api_key: '', api_type: 'openai', timeout_sec: 60, remark: '' }
    providerDialogVisible.value = true
  }

  function onProviderTypeChange(type) {
    if (type === 'accio_work') {
      providerForm.value.api_base = 'http://119.28.107.92:3100'
      providerForm.value.api_key = ''
    }
  }

  async function submitProvider() {
    const valid = await providerFormRef.value?.validate().catch(() => false)
    if (!valid) return
    providerSaving.value = true
    try {
      const payload = { ...providerForm.value }
      if (!payload.api_key) delete payload.api_key
      if (providerEditId.value) {
        await updateProvider(providerEditId.value, payload)
        ElMessage.success('更新成功')
      } else {
        await createProvider(payload)
        ElMessage.success('创建成功')
      }
      providerDialogVisible.value = false
      fetchProviders()
    } catch (e) { /* ignore */ }
    providerSaving.value = false
  }

  async function toggleProvider(row) {
    try {
      await updateProvider(row.id, { is_enabled: row.is_enabled })
      ElMessage.success(row.is_enabled ? '已启用' : '已禁用')
    } catch (e) {
      row.is_enabled = !row.is_enabled
    }
  }

  async function handleTestProvider(row) {
    testingId.value = row.id
    try {
      const res = await testProvider(row.id)
      testResultData.value = res.data
      testResultVisible.value = true
    } catch (e) { /* ignore */ }
    testingId.value = null
  }

  async function handleDeleteProvider(row) {
    try {
      await ElMessageBox.confirm(`确定删除提供商「${row.name}」？`, '确认删除', { type: 'warning' })
      await deleteProvider(row.id)
      ElMessage.success('删除成功')
      fetchProviders()
    } catch (e) {
      if (e !== 'cancel') {
        const msg = e.response?.data?.message || e.message
        if (msg?.includes('活跃 Preset')) {
          ElMessageBox.alert(msg, '无法删除', { type: 'warning' })
        } else {
          ElMessage.error(msg || '删除失败')
        }
      }
    }
  }

  function toggleKey(id) {
    showKeyMap.value[id] = !showKeyMap.value[id]
  }

  // ── Preset methods ────────────────────────────────────
  async function fetchPresets() {
    presetLoading.value = true
    try {
      const res = await getPresets()
      presets.value = res.data.items || []
    } catch (e) { /* ignore */ }
    presetLoading.value = false
  }

  function openPresetDialog(row = null) {
    presetEditId.value = row?.id || null
    presetForm.value = row
      ? { ...row, parameters: JSON.stringify(row.parameters || {}) }
      : { preset_name: '', provider_id: providerOptions.value[0]?.id || '', model: '', system_prompt: '', parameters: '{}', description: '' }
    presetDialogVisible.value = true
  }

  function onPresetProviderChange() {
    if (isAccioProvider.value) {
      presetForm.value.model = ''
    }
  }

  async function submitPreset() {
    const valid = await presetFormRef.value?.validate().catch(() => false)
    if (!valid) return
    presetSaving.value = true
    try {
      const payload = { ...presetForm.value }
      try {
        payload.parameters = JSON.parse(payload.parameters)
      } catch {
        payload.parameters = {}
      }
      if (presetEditId.value) {
        await updatePreset(presetEditId.value, payload)
        ElMessage.success('更新成功')
      } else {
        await createPreset(payload)
        ElMessage.success('创建成功')
      }
      presetDialogVisible.value = false
      fetchPresets()
    } catch (e) { /* ignore */ }
    presetSaving.value = false
  }

  async function handleDeletePreset(row) {
    try {
      await ElMessageBox.confirm(`确定删除预设「${row.preset_name}」？`, '确认删除', { type: 'warning' })
      await deletePreset(row.id)
      ElMessage.success('删除成功')
      fetchPresets()
    } catch (e) {
      if (e !== 'cancel') {
        ElMessage.error(e.response?.data?.message || e.message || '删除失败')
      }
    }
  }

  async function handleCopyPreset(row) {
    try {
      const payload = {
        preset_name: `${row.preset_name}_copy`,
        provider_id: row.provider_id,
        model: row.model,
        system_prompt: row.system_prompt,
        parameters: row.parameters,
        description: row.description ? `${row.description} (复制)` : '',
      }
      await createPreset(payload)
      ElMessage.success('复制成功')
      fetchPresets()
    } catch (e) { /* ignore */ }
  }

  function openTestPreset(row) {
    testPresetId.value = row.id
    testPresetName.value = row.preset_name
    testMessage.value = ''
    testResult.value = null
    testDialogVisible.value = true
  }

  async function sendTest() {
    if (!testMessage.value.trim()) return
    testing.value = true
    testResult.value = null
    try {
      const res = await testPreset(testPresetId.value, testMessage.value)
      testResult.value = res.data
    } catch (e) { /* ignore */ }
    testing.value = false
  }

  // ── Log methods ───────────────────────────────────────
  async function fetchLogs() {
    logsLoading.value = true
    try {
      const params = {
        page: logPage.value,
        page_size: logPageSize.value,
        ...logSort.sortParams.value,
      }
      if (logModuleFilter.value) params.caller_module = logModuleFilter.value
      if (logStatusFilter.value) params.status = logStatusFilter.value
      if (logDateRange.value?.length === 2) {
        params.date_from = logDateRange.value[0]
        params.date_to = logDateRange.value[1]
      }
      const res = await getLogs(params)
      logsData.value = res.data.items || []
      logTotal.value = res.data.total || 0
      logSummaryData.value = res.data.summary || { tokens_total: 0, success_count: 0, error_count: 0, timeout_count: 0, avg_duration_ms: 0 }
    } catch (e) { /* ignore */ }
    logsLoading.value = false
  }

  function onLogExpand(/* row, expandedRows */) {
    // 展开时可选加载详情
  }

  // ── Watch ─────────────────────────────────────────────
  watch([providerSearch, providerTypeFilter, providerStatusFilter], () => { /* client-side filter */ })
  watch([presetSearch, presetProviderFilter], () => { /* client-side filter */ })
  watch([logModuleFilter, logStatusFilter, logDateRange, logPage, logPageSize], fetchLogs, { immediate: false })

  // ── Lifecycle ─────────────────────────────────────────
  onMounted(() => {
    fetchProviders()
    fetchPresets()
    fetchLogs()
  })

  return {
    activeTab,
    // Provider
    providers, providerLoading, providerSearch, providerTypeFilter, providerStatusFilter,
    showKeyMap, testingId, testResultVisible, testResultData,
    providerDialogVisible, providerEditId, providerFormRef, providerSaving,
    providerForm, providerRules,
    fetchProviders, openProviderDialog, onProviderTypeChange, submitProvider,
    toggleProvider, handleTestProvider, handleDeleteProvider, toggleKey,
    filteredProviders,
    // Preset
    presets, presetLoading, presetSearch, presetProviderFilter, providerOptions,
    presetDialogVisible, presetEditId, presetFormRef, presetSaving,
    presetForm, presetRules, isAccioProvider,
    testDialogVisible, testPresetName, testPresetId, testMessage, testing, testResult,
    fetchPresets, openPresetDialog, onPresetProviderChange, submitPreset,
    handleDeletePreset, handleCopyPreset, openTestPreset, sendTest,
    filteredPresets,
    // Logs
    logsData, logsLoading, logSearch, logModuleFilter, logStatusFilter, logDateRange,
    logPage, logPageSize, logTotal, logSummaryData,
    fetchLogs, onLogExpand, logSort,
    logSummary,
    // shared
    stats,
    moduleLabel, statusLabel, statusTagType, formatDuration, formatToken,
  }
}
