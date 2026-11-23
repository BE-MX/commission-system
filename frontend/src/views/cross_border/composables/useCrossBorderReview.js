import { refreshShipment } from '@/api/tracking'
import { computed, onMounted, ref } from 'vue'
import { crossBorderApi as api } from '@/api/crossBorder'
import { useListPage } from '@/composables/useListPage'
import { confirmAction, promptAction, isFeedbackCancelled, msgError, msgSuccessText } from '@/utils/feedback'
import { selectable } from '../reviewPresentation.js'

export function useCrossBorderReview() {
  const summary = ref({})
  const suspectedHashes = ref([])
  const knownRows = new Map()
  let selectionScope = null
  const imports = ref([])
  const selected = ref([])
  const detail = ref(null)
  const detailOpen = ref(false)
  const detailLoading = ref(false)
  const detailError = ref('')
  const importOpen = ref(false)
  const importResults = ref([])
  const busy = ref(false)
  const refreshingTracking = ref(false)
  const exportRecord = ref(null)
  const reviewOpen = ref(false)
  const reviewRow = ref(null)
  const reviewAction = ref('')
  const reason = ref('')
  const target = ref(null)
  let detailRequest = 0
  const listPage = useListPage(async (params, context) => {
    const { data } = await api.list(params, { signal: context.signal })
    if (context.isCurrent()) {
      summary.value = data.summary || {}
      suspectedHashes.value = data.suspected_content_hashes || []
      const { page, page_size, view, ...businessScope } = params
      const scope = JSON.stringify(businessScope)
      data.items.forEach(row => knownRows.set(row.content_hash, row))
      if (scope !== selectionScope) {
        selected.value = data.ready_content_hashes || []
        selectionScope = scope
      } else {
        const eligible = new Set(data.ready_content_hashes || [])
        selected.value = selected.value.filter(hash => eligible.has(hash) || (knownRows.get(hash)?.exported && selectable(knownRows.get(hash))))
      }
    }
    return data
  }, { searchForm: { view: 'blocked', q: '', shop: '', logistics: '', issue: '', import_id: '', salesperson: '', bound_date_from: '', bound_date_to: '' } })
  const candidates = computed(() => reviewRow.value?.candidate_tickets || [])
  async function loadImports() {
    try { imports.value = (await api.imports()).data.items }
    catch (error) { msgError('读取导入记录失败，请重试', error) }
  }
  onMounted(loadImports)
  function switchView(view) {
    listPage.searchForm.view = view
    return listPage.handleSearch()
  }
  async function openDetail(row) {
    detailOpen.value = true
    detail.value = null
    detailError.value = ''
    const request = ++detailRequest
    if (row.row_type !== 'declaration') { detailLoading.value = false; detail.value = row; return }
    detailLoading.value = true
    try {
      const { data } = await api.detail(row.content_hash)
      if (request === detailRequest) detail.value = data
    } catch (error) {
      if (request === detailRequest) detailError.value = error.message || '详情加载失败'
    } finally { if (request === detailRequest) detailLoading.value = false }
  }
  function toggleRow(row, checked) {
    if (!selectable(row)) return
    const values = new Set(selected.value)
    checked ? values.add(row.content_hash) : values.delete(row.content_hash)
    selected.value = [...values]
  }
  async function upload(file, progress) {
    if (!/\.xlsx?$/i.test(file.name)) throw new Error('请选择 .xls 或 .xlsx 文件')
    try {
      const { data } = await api.upload(file, progress)
      importResults.value = [...importResults.value, ...data.items]
      selectionScope = null
      await Promise.all([listPage.refreshCreate(), loadImports()])
      return { name: file.name, path: file.name }
    } catch (error) { msgError(error.message || '导入失败', error); throw error }
  }
  async function beginReview(row, action) {
    if (row.row_type !== 'declaration') return
    await openDetail(row)
    if (!detail.value) return
    reviewRow.value = detail.value
    reviewAction.value = action
    reason.value = ''
    target.value = null
    reviewOpen.value = true
  }
  async function submitReview() {
    if (!reason.value.trim() || (reviewAction.value === 'assign_ticket' && !target.value)) return
    busy.value = true
    try {
      await api.review(reviewRow.value.content_hash, { action: reviewAction.value, reason: reason.value.trim(), target: target.value })
      reviewOpen.value = false
      msgSuccessText('核对处理已保存')
      selectionScope = null
      await listPage.refreshUpdate()
      await openDetail(reviewRow.value)
    } catch (error) { msgError(error.message || '保存失败', error) }
    finally { busy.value = false }
  }
  async function refreshTracking(row) {
    if (!row?.ticket?.waybill_no || refreshingTracking.value) return
    refreshingTracking.value = true
    try {
      await refreshShipment(row.ticket.waybill_no)
      await listPage.refreshUpdate()
      const latest = listPage.list.value.find(item => item.row_type === row.row_type && (row.content_hash ? item.content_hash === row.content_hash : item.ticket?.shipment_tracking_id === row.ticket?.shipment_tracking_id))
      await openDetail(latest || row)
      msgSuccessText('物流状态已刷新')
    } catch (error) { msgError('刷新物流失败，请稍后重试', error) }
    finally { refreshingTracking.value = false }
  }
  async function download(kind, exportId = exportRecord.value?.id) {
    try {
      const response = await api.file(exportId, kind)
      const url = URL.createObjectURL(response.data)
      const link = document.createElement('a')
      link.href = url
      link.download = `${kind === 'order' ? '报关订单' : '报关收款单'}-${exportId}.xlsx`
      document.body.appendChild(link)
      link.click()
      link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (error) { msgError('文件下载失败，可点击重新下载', error) }
  }
  async function exportFiles() {
    if (!selected.value.length || busy.value || listPage.loading.value || listPage.error.value) return
    busy.value = true
    try {
      const hashes = [...selected.value]
      const reexport = hashes.some(hash => knownRows.get(hash)?.exported)
      const suspected = hashes.some(hash => suspectedHashes.value.includes(hash))
      let exportReason = ''
      if (suspected) {
        const result = await promptAction('所选订单包含可能已被修改的申报。请核对 DHL 最新数据，填写确认依据后继续导出。', '确认疑似修改订单', { inputType: 'textarea', inputValidator: value => !!value?.trim() && value.trim().length <= 500 || '请填写 1–500 字核对依据', confirmButtonText: '确认已核对' })
        exportReason = result.value.trim()
      }
      await confirmAction(`将导出已选的 ${hashes.length} 条申报，并生成报关订单与报关收款单。${reexport ? '其中包含已导出条目，本次将再次生成，确认重复导出？' : ''}`, reexport ? '确认重复导出' : '确认导出报关文件', { type: 'warning', confirmButtonText: reexport ? '确认重复导出' : '生成两份文件' })
      exportRecord.value = (await api.export({ content_hashes: hashes, confirm_reexport: reexport, confirm_suspected: suspected, reason: exportReason || null })).data
      selectionScope = null
      await listPage.refreshUpdate()
      msgSuccessText('两份报关文件已生成，请分别下载')
    } catch (error) { if (!isFeedbackCancelled(error)) msgError(error.message || '导出失败', error) }
    finally { busy.value = false }
  }
  return { refreshingTracking, refreshTracking, listPage, summary, imports, selected, detail, detailOpen, detailLoading, detailError, importOpen, importResults, busy, exportRecord, reviewOpen, reviewAction, reason, target, candidates, switchView, openDetail, toggleRow, upload, beginReview, submitReview, exportFiles, download }
}
