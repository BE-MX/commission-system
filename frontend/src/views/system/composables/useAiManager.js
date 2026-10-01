import { msgSuccessText, confirmAction, alertAction, msgError, msgWarning } from '@/utils/feedback'
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
import { ref, reactive, computed, onMounted, toRef } from 'vue'

import {
  getProviders, createProvider, updateProvider, deleteProvider, testProvider,
  getPresets, createPreset, updatePreset, deletePreset, testPreset,
  getLogs,
} from '@/api/ai'
import { useListPage } from '@/composables/useListPage'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { resolveStatus } from '@/utils/status'
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

const CALL_STATUS = {
  success: { label: '成功', tone: 'success' }, error: { label: '错误', tone: 'danger' },
  timeout: { label: '超时', tone: 'warning' }, pending: { label: '进行中', tone: 'primary' },
}
function statusLabel(status) { return resolveStatus(status, CALL_STATUS).label }
function statusTagType(status) { return resolveStatus(status, CALL_STATUS).tone }

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
  const providerResource = useAsyncResource(async (_, { signal }) => (await getProviders(undefined, { signal, suppressToast: true })).data.items || [], { initialData: [] })
  const { data: providers, loading: providerLoading } = providerResource
  const providerDraft = reactive({ search: '', type: '', status: '' })
  const providerApplied = ref({ ...providerDraft })
  const providerSearch = toRef(providerDraft, 'search'), providerTypeFilter = toRef(providerDraft, 'type'), providerStatusFilter = toRef(providerDraft, 'status')
  const providerPending = computed(() => JSON.stringify(providerDraft) !== JSON.stringify(providerApplied.value))
  function searchProviders() { providerApplied.value = { ...providerDraft } }
  function resetProviders() { Object.assign(providerDraft, { search: '', type: '', status: '' }); searchProviders() }

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
  const presetResource = useAsyncResource(async (_, { signal }) => (await getPresets(undefined, { signal, suppressToast: true })).data.items || [], { initialData: [] })
  const { data: presets, loading: presetLoading } = presetResource
  const presetDraft = reactive({ search: '', provider: '' })
  const presetApplied = ref({ ...presetDraft })
  const presetSearch = toRef(presetDraft, 'search'), presetProviderFilter = toRef(presetDraft, 'provider')
  const presetPending = computed(() => JSON.stringify(presetDraft) !== JSON.stringify(presetApplied.value))
  const providerOptions = computed(() => providers.value.map(p => ({ id: p.id, name: p.name, provider_type: p.provider_type })))
  function searchPresets() { presetApplied.value = { ...presetDraft } }
  function resetPresets() { Object.assign(presetDraft, { search: '', provider: '' }); searchPresets() }

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
  const testImageFile = ref(null)
  const testImageFileList = ref([])
  const testReferenceImageFile = ref(null)
  const testReferenceImageFileList = ref([])
  const testing = ref(false)
  const testResult = ref(null)
  const isCompositePreset = computed(() => testPresetName.value === 'expo_wig_composite')

  // ── Logs ──────────────────────────────────────────────
  const logSummaryData = ref({ tokens_total: 0, success_count: 0, error_count: 0, timeout_count: 0, avg_duration_ms: 0 })
  const logSort = useTableSort()
  const logState = useListPage(async ({ module, status, dates, ...params }, { signal, isCurrent }) => {
    if (module) params.caller_module = module
    if (status) params.status = status
    if (dates?.length === 2) { params.date_from = dates[0]; params.date_to = dates[1] }
    const data = (await getLogs(params, { signal, suppressToast: true })).data
    if (isCurrent()) logSummaryData.value = data.summary || { tokens_total: 0, success_count: 0, error_count: 0, timeout_count: 0, avg_duration_ms: 0 }
    return data
  }, { searchForm: { module: '', status: '', dates: [] }, immediate: false })
  const { list: logsData, loading: logsLoading, page: logPage, pageSize: logPageSize, total: logTotal,
    fetchList: fetchLogs, handleSearch: searchLogs, handleReset: resetLogs, handlePageChange: changeLogPage, handleSizeChange: changeLogSize } = logState
  const logModuleFilter = toRef(logState.searchForm, 'module'), logStatusFilter = toRef(logState.searchForm, 'status'), logDateRange = toRef(logState.searchForm, 'dates')
  function sortLogs(sort) { logSort.onSortChange(sort); return logState.handleSortChange(logSort.sortParams.value) }

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
      const matchSearch = !providerApplied.value.search ||
        p.name.toLowerCase().includes(providerApplied.value.search.toLowerCase()) ||
        p.api_base.toLowerCase().includes(providerApplied.value.search.toLowerCase())
      const matchType = !providerApplied.value.type || p.provider_type === providerApplied.value.type
      const matchStatus = (providerApplied.value.status !== true && providerApplied.value.status !== false) || p.is_enabled === providerApplied.value.status
      return matchSearch && matchType && matchStatus
    })
  })

  const filteredPresets = computed(() => {
    return presets.value.filter(p => {
      const matchSearch = !presetApplied.value.search ||
        p.preset_name.toLowerCase().includes(presetApplied.value.search.toLowerCase()) ||
        (p.description && p.description.toLowerCase().includes(presetApplied.value.search.toLowerCase()))
      const matchProv = !presetApplied.value.provider || p.provider_id === presetApplied.value.provider
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
  function fetchProviders() { return providerResource.load() }

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
        msgSuccessText('更新成功')
      } else {
        await createProvider(payload)
        msgSuccessText('创建成功')
      }
      providerDialogVisible.value = false
      fetchProviders()
    } catch (e) { /* ignore */ }
    providerSaving.value = false
  }

  async function toggleProvider(row) {
    try {
      await updateProvider(row.id, { is_enabled: row.is_enabled })
      msgSuccessText(row.is_enabled ? '已启用' : '已禁用')
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
      await confirmAction(`确定删除提供商「${row.name}」？`, '确认删除', { type: 'warning' })
      await deleteProvider(row.id)
      msgSuccessText('删除成功')
      fetchProviders()
    } catch (e) {
      if (e !== 'cancel') {
        const msg = e.response?.data?.message || e.message
        if (msg?.includes('活跃 Preset')) {
          alertAction(msg, '无法删除', { type: 'warning' })
        } else {
          msgError(msg || '删除失败', e)
        }
      }
    }
  }

  function toggleKey(id) {
    showKeyMap.value[id] = !showKeyMap.value[id]
  }

  // ── Preset methods ────────────────────────────────────
  function fetchPresets() { return presetResource.load() }

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
        msgSuccessText('更新成功')
      } else {
        await createPreset(payload)
        msgSuccessText('创建成功')
      }
      presetDialogVisible.value = false
      fetchPresets()
    } catch (e) { /* ignore */ }
    presetSaving.value = false
  }

  async function handleDeletePreset(row) {
    try {
      await confirmAction(`确定删除预设「${row.preset_name}」？`, '确认删除', { type: 'warning' })
      await deletePreset(row.id)
      msgSuccessText('删除成功')
      fetchPresets()
    } catch (e) {
      if (e !== 'cancel') {
        msgError(e.response?.data?.message || e.message || '删除失败', e)
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
      msgSuccessText('复制成功')
      fetchPresets()
    } catch (e) { /* ignore */ }
  }

  function openTestPreset(row) {
    testPresetId.value = row.id
    testPresetName.value = row.preset_name
    if (row.preset_name === 'expo_face_analysis') {
      testMessage.value = '请分析图片中的人物面容特征，只输出 JSON。'
    } else if (row.preset_name === 'expo_wig_composite') {
      testMessage.value = 'Replace the hair in the first image with the wig shown in the second image. Keep the face, expression, skin tone, lighting and background unchanged. Make the hairline transition natural and photorealistic.'
    } else {
      testMessage.value = ''
    }
    testImageFile.value = null
    testImageFileList.value = []
    testReferenceImageFile.value = null
    testReferenceImageFileList.value = []
    testResult.value = null
    testDialogVisible.value = true
  }

  function setTestImageFile(uploadFile, target) {
    const file = uploadFile.raw
    if (!file) return
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      msgError('请选择 JPG / PNG / WEBP 图片')
      target.file.value = null
      target.list.value = []
      return
    }
    if (file.size > 10 * 1024 * 1024) {
      msgError('测试图片不能超过 10MB')
      target.file.value = null
      target.list.value = []
      return
    }
    target.file.value = file
    target.list.value = [uploadFile]
  }

  function handleTestImageChange(uploadFile) {
    setTestImageFile(uploadFile, { file: testImageFile, list: testImageFileList })
  }

  function handleTestImageExceed(files) {
    const file = files[0]
    handleTestImageChange({ name: file.name, raw: file })
  }

  function clearTestImage() {
    testImageFile.value = null
    testImageFileList.value = []
  }

  function handleTestReferenceImageChange(uploadFile) {
    setTestImageFile(uploadFile, { file: testReferenceImageFile, list: testReferenceImageFileList })
  }

  function handleTestReferenceImageExceed(files) {
    const file = files[0]
    handleTestReferenceImageChange({ name: file.name, raw: file })
  }

  function clearTestReferenceImage() {
    testReferenceImageFile.value = null
    testReferenceImageFileList.value = []
  }

  function isImageResponse(value) {
    return typeof value === 'string' && (
      value.startsWith('data:image/') ||
      /^https?:\/\/.+\.(png|jpe?g|webp)(\?.*)?$/i.test(value)
    )
  }

  async function sendTest() {
    if (!testMessage.value.trim()) return
    if (isCompositePreset.value && (!testImageFile.value || !testReferenceImageFile.value)) {
      msgWarning('请同时上传客户原图和假发参考图')
      return
    }
    testing.value = true
    testResult.value = null
    try {
      const res = await testPreset(
        testPresetId.value,
        testMessage.value,
        testImageFile.value,
        isCompositePreset.value ? testReferenceImageFile.value : null,
      )
      testResult.value = res.data
    } catch (e) { /* ignore */ }
    testing.value = false
  }

  // ── Log methods ───────────────────────────────────────


  function onLogExpand(/* row, expandedRows */) {
    // 展开时可选加载详情
  }



  // ── Lifecycle ─────────────────────────────────────────
  onMounted(() => {
    fetchProviders()
    fetchPresets()
    fetchLogs()
  })

  return {
    providerResource, providerPending, searchProviders, resetProviders, presetResource, presetPending, searchPresets, resetPresets,
    logState, searchLogs, resetLogs, changeLogPage, changeLogSize, sortLogs, activeTab,
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
    testDialogVisible, testPresetName, testPresetId, testMessage,
    testImageFileList, testReferenceImageFileList, testing, testResult, isCompositePreset,
    fetchPresets, openPresetDialog, onPresetProviderChange, submitPreset,
    handleDeletePreset, handleCopyPreset, openTestPreset,
    handleTestImageChange, handleTestImageExceed, clearTestImage,
    handleTestReferenceImageChange, handleTestReferenceImageExceed, clearTestReferenceImage,
    isImageResponse, sendTest,
    filteredPresets,
    // Logs
    logsData, logsLoading, logModuleFilter, logStatusFilter, logDateRange,
    logPage, logPageSize, logTotal, logSummaryData,
    fetchLogs, onLogExpand, logSort,
    logSummary,
    // shared
    stats,
    moduleLabel, statusLabel, statusTagType, formatDuration, formatToken,
  }
}
