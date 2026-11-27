import { msgSuccessText, confirmAction, alertAction, msgError, msgWarning } from '@/utils/feedback'
/**
 * AI 管理页 — 业务逻辑 composable
 *
 * 保留 Provider / Preset / Log 既有契约（兼容 aiManagerResources.test.mjs），
 * 并接入 feature_catalog 动态模块标签、预设 feature_key 与日志提供商/费用状态筛选。
 */
import { ref, reactive, computed, onMounted, toRef } from 'vue'

import * as aiApi from '@/api/ai'
import { useListPage } from '@/composables/useListPage'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { resolveStatus } from '@/utils/status'
import { useTableSort } from '@/composables/useTableSort'

const FALLBACK_MODULE_LABELS = {
  logistics: '物流跟踪',
  design_booking: '设计预约',
  commission: '提成管理',
  system: '系统管理',
  ai_preset_test: '预设测试',
}

const CALL_STATUS = {
  success: { label: '成功', tone: 'success' }, error: { label: '错误', tone: 'danger' },
  timeout: { label: '超时', tone: 'warning' }, pending: { label: '进行中', tone: 'primary' },
}
const COST_STATUS = {
  priced: { label: '已计费', tone: 'success' },
  unpriced: { label: '未定价', tone: 'warning' },
  no_usage: { label: '无用量', tone: 'warning' },
  failed: { label: '失败不计费', tone: 'info' },
  not_billed: { label: '不计费', tone: 'info' },
  legacy: { label: '上线前', tone: 'info' },
  test: { label: '测试', tone: 'info' },
}

function statusLabel(status) { return resolveStatus(status, CALL_STATUS).label }
function statusTagType(status) { return resolveStatus(status, CALL_STATUS).tone }
function costStatusLabel(status) { return status ? resolveStatus(status, COST_STATUS).label : '—' }
function costStatusTone(status) { return status ? resolveStatus(status, COST_STATUS).tone : 'info' }

function formatDuration(ms) {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${ms}ms`
}

function formatToken(n) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return String(n)
}

export function useAiManager() {
  const activeTab = ref('subscriptions')

  // ── Feature Catalog ───────────────────────────────────
  const featureCatalog = ref([])
  const dynamicModuleLabels = ref({ ...FALLBACK_MODULE_LABELS })

  function moduleLabel(code) {
    return dynamicModuleLabels.value[code] || FALLBACK_MODULE_LABELS[code] || code
  }

  async function fetchFeatureCatalog() {
    if (typeof aiApi.getFeatureCatalog !== 'function') return
    try {
      const res = await aiApi.getFeatureCatalog()
      featureCatalog.value = res?.data?.items || []
      if (res?.data?.module_labels) {
        dynamicModuleLabels.value = { ...FALLBACK_MODULE_LABELS, ...res.data.module_labels }
      }
    } catch { /* fallback labels remain active */ }
  }

  const featureGroupedOptions = computed(() => {
    const groups = new Map()
    for (const item of featureCatalog.value) {
      const grp = item.nav_group || '其他'
      if (!groups.has(grp)) groups.set(grp, [])
      groups.get(grp).push(item)
    }
    return [...groups.entries()].map(([label, options]) => ({ label, options }))
  })

  // ── Providers ─────────────────────────────────────────
  const providerResource = useAsyncResource(async (_, { signal }) => (await aiApi.getProviders(undefined, { signal, suppressToast: true })).data.items || [], { initialData: [] })
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
    name: '', provider_type: 'direct', api_base: '', api_key: '', api_type: 'openai', timeout_sec: 60, runtime_config: '{}', extra_headers: '{}', remark: '',
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
  const presetResource = useAsyncResource(async (_, { signal }) => (await aiApi.getPresets(undefined, { signal, suppressToast: true })).data.items || [], { initialData: [] })
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
    preset_name: '', provider_id: '', feature_key: '', model: '', system_prompt: '', parameters: '{}', description: '',
  })
  const presetRules = {
    preset_name: [
      { required: true, message: '请输入预设名称', trigger: 'blur' },
      { pattern: /^[a-zA-Z0-9_]+$/, message: '只允许字母、数字、下划线', trigger: 'blur' },
    ],
    provider_id: [{ required: true, message: '请选择提供商', trigger: 'change' }],
    feature_key: [{ required: true, message: '请选择所属功能', trigger: 'change' }],
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
  const isImageTest = computed(() => {
    const preset = presets.value.find(row => row.id === testPresetId.value)
    const params = preset?.parameters || {}
    return params.test_mode ? params.test_mode === 'image' : (params.studio?.enabled || params.api_style || isCompositePreset.value || testPresetName.value.startsWith('design_image_generation'))
  })

  // ── Logs ──────────────────────────────────────────────
  const logSummaryData = ref({ tokens_total: 0, success_count: 0, error_count: 0, timeout_count: 0, avg_duration_ms: 0 })
  const logSort = useTableSort()
  const logState = useListPage(async ({ module, providerId, status, costStatus, dates, ...params }, { signal, isCurrent }) => {
    if (module) params.caller_module = module
    if (providerId) params.provider_id = providerId
    if (status) params.status = status
    if (costStatus) params.cost_status = costStatus
    if (dates?.length === 2) { params.date_from = dates[0]; params.date_to = dates[1] }
    const data = (await aiApi.getLogs(params, { signal, suppressToast: true })).data
    if (isCurrent()) logSummaryData.value = data.summary || { tokens_total: 0, success_count: 0, error_count: 0, timeout_count: 0, avg_duration_ms: 0 }
    return data
  }, { searchForm: { module: '', providerId: '', status: '', costStatus: '', dates: [] }, immediate: false })
  const { list: logsData, loading: logsLoading, page: logPage, pageSize: logPageSize, total: logTotal,
    fetchList: fetchLogs, handleSearch: searchLogs, handleReset: resetLogs, handlePageChange: changeLogPage, handleSizeChange: changeLogSize } = logState
  const logModuleFilter = toRef(logState.searchForm, 'module')
  const logProviderFilter = toRef(logState.searchForm, 'providerId')
  const logStatusFilter = toRef(logState.searchForm, 'status')
  const logCostStatusFilter = toRef(logState.searchForm, 'costStatus')
  const logDateRange = toRef(logState.searchForm, 'dates')
  function sortLogs(sort) { logSort.onSortChange(sort); return logState.handleSortChange(logSort.sortParams.value) }

  function jumpToProviderLogs(providerId) {
    activeTab.value = 'logs'
    logProviderFilter.value = providerId
    searchLogs()
  }

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
      { label: '调用次数', value: String(logTotal.value), icon: 'Histogram', color: 'var(--tag-info-solid)' },
      { label: '成功', value: String(s.success_count), icon: 'SuccessFilled', color: 'var(--tag-success-solid)' },
      { label: '错误', value: String(s.error_count), icon: 'CircleCloseFilled', color: 'var(--tag-danger-solid)' },
      { label: '超时', value: String(s.timeout_count), icon: 'WarningFilled', color: 'var(--tag-warning-solid)' },
      { label: '总 Token', value: s.tokens_total.toLocaleString(), icon: 'Histogram', color: 'var(--metric-violet-ink)' },
      { label: '平均耗时', value: `${s.avg_duration_ms}ms`, icon: 'Loading', color: 'var(--tag-info-text)' },
    ]
  })

  // ── Provider methods ──────────────────────────────────
  function fetchProviders() { return providerResource.load() }

  function openProviderDialog(row = null) {
    providerEditId.value = row?.id || null
    providerForm.value = row
      ? { ...row, api_key: '', runtime_config: JSON.stringify(row.runtime_config || {}, null, 2), extra_headers: JSON.stringify(row.extra_headers || {}, null, 2) }
      : { name: '', provider_type: 'direct', api_base: '', api_key: '', api_type: 'openai', timeout_sec: 60, runtime_config: '{}', extra_headers: '{}', remark: '' }
    providerDialogVisible.value = true
  }

  function onProviderTypeChange() {}

  async function submitProvider() {
    const valid = await providerFormRef.value?.validate().catch(() => false)
    if (!valid) return
    providerSaving.value = true
    try {
      const payload = { ...providerForm.value }
      for (const key of ['runtime_config', 'extra_headers']) {
        try {
          const parsed = JSON.parse(payload[key] || '{}')
          if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('object required')
          payload[key] = parsed
        } catch {
          msgError(`${key === 'runtime_config' ? '运行配置' : '附加请求头'}必须是有效的 JSON 对象；原配置尚未修改`)
          return
        }
      }
      if (!payload.api_key) delete payload.api_key
      if (providerEditId.value) {
        await aiApi.updateProvider(providerEditId.value, payload)
        msgSuccessText('更新成功')
      } else {
        await aiApi.createProvider(payload)
        msgSuccessText('创建成功')
      }
      providerDialogVisible.value = false
      fetchProviders()
    } catch (e) { /* API feedback is handled by the shared client. */ }
    finally { providerSaving.value = false }
  }

  async function toggleProvider(row, nextVal = null) {
    const target = nextVal !== null ? nextVal : !row.is_enabled
    const prev = row.is_enabled
    row.is_enabled = target
    try {
      await aiApi.updateProvider(row.id, { is_enabled: target })
      msgSuccessText(target ? '已启用' : '已禁用')
      return true
    } catch (e) {
      row.is_enabled = prev
      return false
    }
  }

  async function handleTestProvider(row) {
    testingId.value = row.id
    try {
      const res = await aiApi.testProvider(row.id)
      testResultData.value = res.data
      testResultVisible.value = true
    } catch (e) { /* ignore */ }
    testingId.value = null
  }

  async function handleDeleteProvider(row) {
    try {
      await confirmAction(`确定删除提供商「${row.name}」？软删除后历史调用消费仍保留在总账。`, '确认删除', { type: 'warning' })
      await aiApi.deleteProvider(row.id)
      msgSuccessText('删除成功')
      fetchProviders()
      return true
    } catch (e) {
      if (e !== 'cancel') {
        const msg = e.response?.data?.message || e.message
        if (msg?.includes('活跃 Preset')) {
          alertAction(msg, '无法删除', { type: 'warning' })
        } else {
          msgError(msg || '删除失败', e)
        }
      }
      return false
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
      ? { ...row, feature_key: row.feature_key || '', parameters: JSON.stringify(row.parameters || {}) }
      : { preset_name: '', provider_id: providerOptions.value[0]?.id || '', feature_key: '', model: '', system_prompt: '', parameters: '{}', description: '' }
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
        if (!payload.parameters || Array.isArray(payload.parameters) || typeof payload.parameters !== 'object') {
          throw new Error('调用参数必须是 JSON 对象')
        }
      } catch {
        msgError('调用参数格式有误，请输入有效的 JSON 对象；原配置尚未修改')
        return
      }
      if (!payload.feature_key) delete payload.feature_key
      if (presetEditId.value) {
        await aiApi.updatePreset(presetEditId.value, payload)
        msgSuccessText('更新成功')
      } else {
        await aiApi.createPreset(payload)
        msgSuccessText('创建成功')
      }
      presetDialogVisible.value = false
      fetchPresets()
    } catch (e) { /* API feedback is handled by the shared client. */ }
    finally { presetSaving.value = false }
  }

  async function togglePreset(row) {
    try {
      const next = !row.is_enabled
      await aiApi.updatePreset(row.id, { is_enabled: next })
      msgSuccessText(next ? '预设已启用' : '预设已停用')
      fetchPresets()
      return true
    } catch { return false }
  }

  async function handleDeletePreset(row) {
    try {
      await confirmAction(`确定删除预设「${row.preset_name}」？`, '确认删除', { type: 'warning' })
      await aiApi.deletePreset(row.id)
      msgSuccessText('删除成功')
      fetchPresets()
      return true
    } catch (e) {
      if (e !== 'cancel') {
        msgError(e.response?.data?.message || e.message || '删除失败', e)
      }
      return false
    }
  }

  async function handleCopyPreset(row) {
    if (!row.feature_key) {
      msgWarning('该存量预设尚未设置所属功能，请先编辑归属后再复制')
      return
    }
    try {
      const payload = {
        preset_name: `${row.preset_name}_copy`,
        provider_id: row.provider_id,
        feature_key: row.feature_key,
        model: row.model,
        system_prompt: row.system_prompt,
        parameters: row.parameters,
        description: row.description ? `${row.description} (复制)` : '',
      }
      await aiApi.createPreset(payload)
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

  function handleTestImageChange(uploadFile) { setTestImageFile(uploadFile, { file: testImageFile, list: testImageFileList }) }
  function handleTestImageExceed(files) { const file = files[0]; handleTestImageChange({ name: file.name, raw: file }) }
  function clearTestImage() { testImageFile.value = null; testImageFileList.value = [] }
  function handleTestReferenceImageChange(uploadFile) { setTestImageFile(uploadFile, { file: testReferenceImageFile, list: testReferenceImageFileList }) }
  function handleTestReferenceImageExceed(files) { const file = files[0]; handleTestReferenceImageChange({ name: file.name, raw: file }) }
  function clearTestReferenceImage() { testReferenceImageFile.value = null; testReferenceImageFileList.value = [] }

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
      const res = await aiApi.testPreset(
        testPresetId.value,
        testMessage.value,
        testImageFile.value,
        isImageTest.value ? testReferenceImageFile.value : null,
      )
      testResult.value = res.data
    } catch (e) { /* ignore */ }
    testing.value = false
  }

  function onLogExpand() {}

  onMounted(() => {
    fetchFeatureCatalog()
    fetchProviders()
    fetchPresets()
    fetchLogs()
  })

  return {
    providerResource, providerPending, searchProviders, resetProviders, presetResource, presetPending, searchPresets, resetPresets,
    logState, searchLogs, resetLogs, changeLogPage, changeLogSize, sortLogs, activeTab,
    featureCatalog, featureGroupedOptions, dynamicModuleLabels, fetchFeatureCatalog,
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
    testImageFileList, testReferenceImageFileList, testing, testResult, isCompositePreset, isImageTest,
    fetchPresets, openPresetDialog, onPresetProviderChange, submitPreset, togglePreset,
    handleDeletePreset, handleCopyPreset, openTestPreset,
    handleTestImageChange, handleTestImageExceed, clearTestImage,
    handleTestReferenceImageChange, handleTestReferenceImageExceed, clearTestReferenceImage,
    isImageResponse, sendTest,
    filteredPresets,
    // Logs
    logsData, logsLoading, logModuleFilter, logProviderFilter, logStatusFilter, logCostStatusFilter, logDateRange,
    logPage, logPageSize, logTotal, logSummaryData,
    fetchLogs, onLogExpand, logSort, jumpToProviderLogs,
    logSummary,
    // shared
    stats,
    moduleLabel, statusLabel, statusTagType, costStatusLabel, costStatusTone, formatDuration, formatToken,
  }
}
