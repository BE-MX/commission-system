import { ref, computed, onBeforeUnmount, onMounted } from 'vue'
import { stationApi } from '@/api/shippingStation'
import { compressInspectionVideo, prepareInspectionVideo } from './compressInspectionVideo'
import { confirmDanger } from '@/utils/feedback'

const requestId = () => crypto.randomUUID()
export function useShippingStation(api = stationApi) {
  const operators = ref([]), selected = ref(null), view = ref(null), remark = ref('')
  const busy = ref(false), loading = ref(false), scannerOpen = ref(false), error = ref('')
  const invalid = ref(false), loginRequired = ref(false), prompt = ref('请选择本次操作人')
  const selectionVersion = ref(0), receipt = ref(null), progress = ref(0), pendingUpload = ref(null), pendingSubmit = ref(null)
  const uploadStage = ref('')
  const uploadItemId = ref(undefined), uploadError = ref(''), pendingCompression = ref(null)
  const awaitingVideoActivation = ref(false)
  let compressionController
  let preparedVideo
  let promptTimer, idleTimer, lastActive = Date.now(), alive = true, scanIntent = null
  const sessionId = computed(() => view.value?.session_id)
  const operator = computed(() => view.value?.operator || selected.value)
  const submitted = computed(() => view.value?.inspection?.status === 'submitted')
  const photos = computed(() => view.value?.photos || [])
  const videos = computed(() => view.value?.videos || [])
  const canWrite = computed(() => !!sessionId.value && !busy.value && !invalid.value && !submitted.value && !pendingSubmit.value)
  const editVersion = () => view.value?.inspection?.edit_version || 0
  const dirty = computed(() => !!view.value && remark.value !== (view.value.inspection?.remark || ''))

  async function fail(e) {
    let detail = e.response?.data
    if (detail instanceof Blob) {
      try { detail = JSON.parse(await detail.text()) } catch { detail = null }
    }
    detail = detail?.detail || detail
    error.value = detail?.message || (typeof detail === 'string' ? detail : '网络异常，操作结果未确认，请核对后重试')
    if (e.response?.status === 401) { loginRequired.value = true; invalid.value = true }
    if (['OPERATOR_INVALID', 'STATION_FORBIDDEN', 'SESSION_EXPIRED', 'SESSION_ENDED', 'SESSION_NOT_FOUND'].includes(detail?.code)) {
      invalid.value = true
      scannerOpen.value = false
      selected.value = null
    }
  }
  async function loadOperators() {
    loading.value = true
    try { operators.value = (await api.operators()).data; error.value = '' }
    catch (e) { operators.value = []; await fail(e) }
    finally { loading.value = false }
  }
  function choose(person) {
    if (busy.value || scannerOpen.value || view.value || loading.value || loginRequired.value) return
    if (selected.value?.id === person.id) return
    prompt.value = selected.value ? '已切换为' : '已选择'
    selected.value = person
    selectionVersion.value++
    receipt.value = null
    invalid.value = false
    error.value = ''
    scanIntent = null
    clearTimeout(promptTimer)
    promptTimer = setTimeout(() => { prompt.value = '当前操作人' }, 1500)
  }
  function startScan() {
    if (busy.value || loading.value || invalid.value) return
    if (!selected.value) {
      error.value = '请先点击下方姓名，选择本次操作人'
      selectionVersion.value++
      return false
    }
    error.value = ''
    scannerOpen.value = true
    return true
  }
  function accept(payload, keepRemark = false) {
    view.value = payload
    if (!keepRemark) remark.value = payload.inspection?.remark || ''
    lastActive = Date.now()
    invalid.value = false
  }
  async function decoded(raw) {
    if (busy.value || !selected.value || view.value) return
    scannerOpen.value = false
    if (!String(raw).startsWith('ARK-I:')) { error.value = '请扫描出库单右上角二维码'; return }
    busy.value = true
    if (!scanIntent || scanIntent.qr_raw !== raw || scanIntent.operator_id !== selected.value.id) {
      scanIntent = { qr_raw: raw, operator_id: selected.value.id, request_id: requestId() }
    }
    try { const result = await api.scan(scanIntent); if (alive) { accept(result.data); error.value = '' } }
    catch (e) { await fail(e) }
    finally { busy.value = false }
  }
  async function refresh() {
    if (busy.value || invalid.value || pendingSubmit.value || !sessionId.value) return
    busy.value = true
    try { accept((await api.refresh(sessionId.value)).data, true); error.value = '' }
    catch (e) { await fail(e) }
    finally { busy.value = false }
  }
  function cancelVideoPreparation() {
    preparedVideo?.dispose(); preparedVideo = null
  }
  function prepareVideo() {
    if (!canWrite.value || pendingCompression.value) return
    cancelVideoPreparation()
    try { preparedVideo = prepareInspectionVideo() }
    catch (e) { console.warn('Video preparation unavailable; compression will report capability errors', e) }
  }
  async function upload(file, itemId, type, retry = false, resumeCompression = false) {
    if (!canWrite.value || !file) return
    if (pendingCompression.value && !resumeCompression) return
    busy.value = true; progress.value = 0; error.value = ''
    uploadItemId.value = itemId || null; uploadError.value = ''
    awaitingVideoActivation.value = false
    let intent
    try {
      if (!retry && type === 'videos') {
        pendingCompression.value = { file, itemId, type }
        uploadStage.value = '正在压缩视频，请保持页面在前台'
        compressionController = new AbortController()
        const prepared = preparedVideo; preparedVideo = null
        file = await compressInspectionVideo(file, { prepared, signal: compressionController.signal, onProgress: value => { progress.value = value } })
        if (!alive) return
      }
      pendingCompression.value = null
      const limit = type === 'videos' ? 100 : 20
      if (file.size > limit * 1024 * 1024) throw new Error(`文件不能超过 ${limit}MB`)
      if (!retry) pendingUpload.value = { file, itemId, type, request_id: requestId(), edit_version: editVersion() }
      intent = pendingUpload.value
    } catch (e) {
      if (e.code === 'VIDEO_ACTIVATION_REQUIRED' && alive) {
        awaitingVideoActivation.value = true
        return
      }
      error.value = e.message || '视频压缩失败，请重新选择视频'
      uploadError.value = error.value
      return
    } finally {
      compressionController = null
      if (!intent) { busy.value = false; uploadStage.value = '' }
    }
    uploadStage.value = '正在上传'; progress.value = 0
    const form = new FormData()
    form.append('file', intent.file)
    form.append('edit_version', intent.edit_version)
    form.append('request_id', intent.request_id)
    if (intent.itemId) form.append('item_id', intent.itemId)
    try {
      await api.upload(sessionId.value, intent.type, form, event => {
        if (event.total) progress.value = Math.round(event.loaded / event.total * 100)
      })
      pendingUpload.value = null
      accept((await api.refresh(sessionId.value)).data, true)
    } catch (e) { await fail(e); uploadError.value = error.value }
    finally { busy.value = false; uploadStage.value = '' }
  }
  function retryCompression() {
    const p = pendingCompression.value
    if (p) return upload(p.file, p.itemId, p.type, false, true)
  }
  async function discardCompression() {
    if (!canWrite.value || !pendingCompression.value) return
    busy.value = true
    try {
      await confirmDanger('放弃这段未上传的视频', '', '这段视频尚未保存到验货单，放弃后需要重新拍摄或选择。')
      pendingCompression.value = null; awaitingVideoActivation.value = false
      uploadItemId.value = undefined; uploadError.value = ''; error.value = ''
    } catch { /* Keep the selected file when dismissal is cancelled. */ }
    finally { busy.value = false }
  }
  function retryUpload() {
    const p = pendingUpload.value
    if (p) return upload(p.file, p.itemId, p.type, true)
  }
  async function remove(media) {
    if (!canWrite.value) return
    busy.value = true
    try { await confirmDanger('删除', media.media_type === 'video' ? '这段视频' : '这张照片') }
    catch { busy.value = false; return }
    try {
      await api.delete(sessionId.value, media.id, { edit_version: editVersion(), request_id: requestId() })
      accept((await api.refresh(sessionId.value)).data, true)
    } catch (e) { await fail(e) }
    finally { busy.value = false }
  }
  async function submit() {
    if (busy.value || invalid.value || (!canWrite.value && !pendingSubmit.value)) return
    if (pendingCompression.value) { error.value = '已选择的视频尚未上传，请先完成视频上传'; return }
    if (!photos.value.length) { error.value = '每张出库单至少上传一张照片'; return }
    busy.value = true
    pendingSubmit.value ||= { edit_version: editVersion(), request_id: requestId(), remark: remark.value }
    try {
      receipt.value = (await api.submit(sessionId.value, pendingSubmit.value)).data
      clearSession()
      await loadOperators()
    } catch (e) {
      const status = e.response?.status
      if (status >= 400 && status < 500 && ![408, 429].includes(status)) pendingSubmit.value = null
      await fail(e)
    }
    finally { busy.value = false }
  }
  function clearSession() {
    cancelVideoPreparation()
    view.value = null; selected.value = null; remark.value = ''; error.value = ''; invalid.value = false
    pendingUpload.value = null; pendingSubmit.value = null; scanIntent = null; prompt.value = '请选择本次操作人'
    pendingCompression.value = null; uploadItemId.value = undefined; uploadError.value = ''
    awaitingVideoActivation.value = false
    clearTimeout(promptTimer)
  }
  async function end() {
    if (busy.value) return
    busy.value = true
    if (dirty.value || pendingUpload.value || pendingSubmit.value || pendingCompression.value) {
      try { await confirmDanger('结束本次操作', '', '已上传文件保留；未上传视频和未提交备注不会保存。未确认请求可由接手人扫码核对。') }
      catch { busy.value = false; return }
    }
    try {
      if (sessionId.value && !invalid.value) await api.end(sessionId.value)
      clearSession()
      await loadOperators()
    } catch (e) { await fail(e) }
    finally { busy.value = false }
  }
  const warnLeave = event => { if (dirty.value || busy.value || pendingCompression.value) { event.preventDefault(); event.returnValue = '' } }
  onMounted(() => {
    loadOperators()
    window.addEventListener('beforeunload', warnLeave)
    idleTimer = setInterval(() => {
      if (sessionId.value && !busy.value && !pendingSubmit.value && Date.now() - lastActive >= (view.value.idle_minutes || 15) * 60000) {
        invalid.value = true; error.value = '操作身份已超时，请结束本次操作后重新选择人员扫码'
      }
    }, 5000)
  })
  onBeforeUnmount(() => {
    cancelVideoPreparation()
    alive = false; compressionController?.abort(); clearTimeout(promptTimer); clearInterval(idleTimer)
    pendingCompression.value = null
    window.removeEventListener('beforeunload', warnLeave)
  })
  return { operators, selected, operator, view, remark, busy, loading, scannerOpen, error, invalid, loginRequired,
    prompt, selectionVersion, receipt, progress, uploadStage, photos, videos, submitted, canWrite, sessionId, dirty, pendingUpload, pendingSubmit,
    uploadItemId, uploadError, pendingCompression, retryCompression, awaitingVideoActivation, discardCompression, prepareVideo, cancelVideoPreparation,
    choose, startScan, decoded, refresh, upload, retryUpload, remove, submit, end, loadOperators, fail }
}
