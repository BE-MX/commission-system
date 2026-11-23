import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { currentBeijingDate } from '@/utils/datetime'
import { msgSuccessText, confirmAction } from '@/utils/feedback'
import { bindInspectionShipment, createInspectionShipment, listMobileWaybillQueue, uploadInspectionWaybillPhoto, previewInspectionShipment } from '@/api/shipping'
import { canSubmitPreview, previewFingerprint } from './mobileWaybillState.js'

function errorText(failure, fallback) {
  const data = failure.response?.data
  return data?.message || (typeof data?.detail === 'string' ? data.detail : data?.detail?.message) || fallback
}

export function useMobileWaybills() {
  const auth = useAuthStore()
  const allowed = computed(() => auth.hasPermission('tracking:write'))
  const tab = ref('pending'), keyword = ref(''), includeOlder = ref(false)
  const nextInspectionId = ref(null)
  const page = ref(1), total = ref(0), hasMore = ref(false)
  const rows = ref([]), loading = ref(false), queueError = ref(''), selected = ref(null)
  const step = ref('list'), busy = ref(''), error = ref(''), notice = ref(''), imageUrl = ref('')
  const form = reactive({ waybill_no: '', carrier: '', recipient_name: '', recipient_country: '', ship_date: '' })
  const numberSource = ref('manual'), photoToken = ref(''), preview = ref(null), confirmations = ref([])
  const countryOpen = ref(false), snapshot = ref('')
  let queueRequest = 0, operation = 0, syncRequest = 0, searchTimer
  let capture = null, queueContext = null, changingTab = false
  const locked = computed(() => !!busy.value)
  const canSubmit = computed(() => !locked.value && allowed.value && canSubmitPreview(preview.value, snapshot.value, form, photoToken.value, confirmations.value))
  const inferredDhl = computed(() => /^\d{10}$/.test(form.waybill_no.trim()))
  const submitLabel = computed(() => preview.value?.existing?.exists ? '关联已有运单' : preview.value?.sync_result === 'failed' ? '仍然提交' : '确认提交')
  function invalidatePreview() { syncRequest++; preview.value = null; snapshot.value = ''; confirmations.value = [] }
  watch(() => previewFingerprint(form), invalidatePreview, { flush: 'sync' })
  const loadQueue = () => fetchQueue(false)
  const loadMore = () => fetchQueue(true)
  async function fetchQueue(append, retainPages = 1) {
    const request = ++queueRequest
    const nextPage = append ? page.value + 1 : 1
    loading.value = true; queueError.value = ''
    try {
      const params = { tab: tab.value, keyword: keyword.value, include_older: includeOlder.value }
      const refreshed = []
      let data, loadedPage = nextPage
      for (let currentPage = nextPage; currentPage <= (append ? nextPage : retainPages); currentPage++) {
        const response = await listMobileWaybillQueue({ ...params, page: currentPage })
        if (request !== queueRequest) return false
        data = response.data; loadedPage = currentPage; refreshed.push(...data.items)
        if (!data.has_more) break
      }
      rows.value = append ? [...rows.value, ...refreshed] : refreshed
      total.value = data.total; hasMore.value = data.has_more; page.value = loadedPage
      return true
    } catch (failure) { if (request === queueRequest) queueError.value = errorText(failure, '列表加载失败，请重试') }
    finally { if (request === queueRequest) loading.value = false }
  }
  watch([tab, includeOlder], () => { nextInspectionId.value = null; if (!changingTab) loadQueue() }, { flush: 'sync' })
  watch(keyword, () => { clearTimeout(searchTimer); searchTimer = setTimeout(loadQueue, 300) })
  function releaseImage() { if (imageUrl.value) URL.revokeObjectURL(imageUrl.value); imageUrl.value = '' }
  async function begin(row) {
    if (!allowed.value || locked.value) return
    if (tab.value === 'done') {
      try { await confirmAction('更换后旧照片仍会保留。请确认手里的包裹属于这张验货单。', '更换物流单', { confirmButtonText: '继续拍摄', cancelButtonText: '取消' }) }
      catch { return }
    }
    clearTimeout(searchTimer); queueRequest++; loading.value = false; nextInspectionId.value = null
    const index = rows.value.findIndex(item => item.id === row.id)
    queueContext = { tab: tab.value, pages: page.value, index, successors: rows.value.slice(index + 1).map(item => item.id), hadMore: hasMore.value }
    operation++; selected.value = row; capture = null; releaseImage()
    Object.assign(form, { waybill_no: '', carrier: '', recipient_name: row.recipient_name || '', recipient_country: row.recipient_country || '', ship_date: currentBeijingDate() })
    numberSource.value = 'manual'; photoToken.value = ''; error.value = ''; notice.value = ''; invalidatePreview()
    step.value = 'camera'
  }
  function leaveCapture() {
    operation++; syncRequest++; busy.value = ''; step.value = 'list'; selected.value = null; capture = null; releaseImage()
  }
  function back() {
    if (busy.value === 'submit') return
    leaveCapture(); loadQueue()
  }
  async function continueQueue() {
    const context = queueContext
    leaveCapture(); busy.value = 'queue'
    const current = operation
    changingTab = true; tab.value = 'pending'; changingTab = false
    const refreshed = await fetchQueue(false, context?.tab === 'pending' ? context.pages : 1)
    if (!refreshed || current !== operation || tab.value !== 'pending') return
    busy.value = ''
    if (context?.tab !== 'pending') nextInspectionId.value = rows.value[0]?.id ?? null
    else {
      const next = context.successors.find(id => rows.value.some(item => item.id === id))
      nextInspectionId.value = next ?? (context.hadMore ? rows.value[Math.max(0, context.index)]?.id : null) ?? null
    }
  }
  function retake() { if (!locked.value) { operation++; photoToken.value = ''; invalidatePreview(); step.value = 'camera' } }
  async function captured(value) {
    capture = value; releaseImage(); imageUrl.value = URL.createObjectURL(value.scan)
    photoToken.value = ''; invalidatePreview(); step.value = 'review'
    if (value.barcode) { form.waybill_no = value.barcode; numberSource.value = 'barcode'; if (/^\d{10}$/.test(value.barcode)) form.carrier = 'DHL' }
    await upload()
  }
  async function upload() {
    if (!capture || locked.value) return
    const request = ++operation
    busy.value = 'photo'; error.value = ''; notice.value = ''
    const body = new FormData()
    body.append('rectified', capture.scan, 'waybill.jpg'); body.append('original', capture.original, 'original.jpg')
    body.append('barcode', capture.barcode || '')
    try {
      const { data } = await uploadInspectionWaybillPhoto(selected.value.id, body)
      if (request !== operation) return
      photoToken.value = data.photo_token
      form.waybill_no = data.waybill_no || capture.barcode || ''
      form.carrier = /^\d{10}$/.test(form.waybill_no) ? 'DHL' : data.carrier || ''
      form.recipient_country = data.recipient_country || selected.value.recipient_country || ''
      form.recipient_name = data.recipient_name || selected.value.recipient_name || ''
      numberSource.value = data.number_source || (capture.barcode ? 'barcode' : form.waybill_no ? 'ocr' : 'manual')
      countryOpen.value = !form.recipient_country
      notice.value = data.barcode_conflict ? `AI 识别为 ${data.barcode_conflict}，已按条码填写` : data.recognition_error ? 'AI 识别暂不可用，请核对条码或手动输入。' : !form.waybill_no ? '没读出运单号，请重拍或手动输入' : ''
    } catch (failure) { if (request === operation) error.value = errorText(failure, '照片保存失败，请重试上传；尚未提交物流单。') }
    finally { if (request === operation) busy.value = '' }
  }
  function editNumber() { numberSource.value = 'manual'; if (inferredDhl.value) form.carrier = 'DHL' }
  async function sync() {
    if (locked.value) return
    form.waybill_no = form.waybill_no.trim().replace(/\s/g, '').toUpperCase()
    if (locked.value || !photoToken.value || !form.waybill_no.trim() || !form.carrier || !form.recipient_country.trim()) {
      countryOpen.value = !form.recipient_country; error.value = '请先保存照片，并填写运单号、承运商和收件国家。'; return
    }
    invalidatePreview()
    const request = syncRequest, key = previewFingerprint(form), current = operation
    busy.value = 'sync'; error.value = ''
    try {
      const { data } = await previewInspectionShipment(selected.value.id, { ...form, photo_token: photoToken.value, edit_version: selected.value.edit_version, shipment_version: selected.value.shipment_version })
      if (request !== syncRequest || current !== operation || key !== previewFingerprint(form)) return
      preview.value = data; snapshot.value = previewFingerprint(form)
    } catch (failure) { if (current === operation && request === syncRequest) await handleFailure(failure, '同步失败，请重试。') }
    finally { if (current === operation) busy.value = '' }
  }
  async function handleFailure(failure, fallback) {
    const status = failure.response?.status, data = failure.response?.data
    if (status === 409 && /version|changed|撤回|变化/i.test(JSON.stringify(data))) {
      msgSuccessText('验货单已变化，已刷新'); back(); return
    }
    error.value = errorText(failure, fallback)
    if (/照片已过期/.test(error.value)) { photoToken.value = ''; invalidatePreview() }
    else if (/同步结果已过期|先同步物流信息/.test(error.value)) invalidatePreview()
  }
  async function submit() {
    if (!canSubmit.value) return
    busy.value = 'submit'; error.value = ''
    try {
      const action = preview.value.existing?.exists ? bindInspectionShipment : createInspectionShipment
      await action(selected.value.id, { ...form, edit_version: selected.value.edit_version, shipment_version: selected.value.shipment_version,
        source: 'mobile', entry_source: numberSource.value, number_source: numberSource.value, photo_token: photoToken.value,
        preview_token: preview.value.preview_token, confirmed_warnings: confirmations.value, sync_result: preview.value.sync_result })
      const number = form.waybill_no; msgSuccessText(`已录入 · ${number}`); await continueQueue()
    } catch (failure) {
      busy.value = ''
      await handleFailure(failure, '提交结果尚未确认，请保留本页并重试；重复提交不会重复关联。')
    } finally { busy.value = '' }
  }
  onMounted(loadQueue)
  onBeforeUnmount(() => { operation++; queueRequest++; syncRequest++; clearTimeout(searchTimer); releaseImage() })
  return { nextInspectionId, total, hasMore, loadMore, allowed, tab, keyword, includeOlder, rows, loading, queueError, selected, step, busy, error, notice, imageUrl, form, numberSource, photoToken, preview, confirmations, countryOpen, locked, canSubmit, inferredDhl, submitLabel, loadQueue, begin, back, retake, captured, upload, editNumber, sync, submit }
}
