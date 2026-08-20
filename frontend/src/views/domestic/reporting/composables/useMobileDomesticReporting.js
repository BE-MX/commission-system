import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import {
  fetchMobileReportingImage,
  getMobileReportingHistory,
  newRequestId,
  revokeMobileDomesticReport,
  scanMobileDomesticCode,
  submitMobileDomesticReport,
} from '@/api/domestic'
import { confirmDanger } from '@/utils/feedback'
import {
  BLOCK_MESSAGES,
  REPORTING_PENDING_KEY,
  buildMobileReportPayload,
  collectRequirementImagePaths,
  httpStatus,
  isDefinitiveSubmitFailure,
  isReportingAuthError,
  parseDomesticReportingCode,
  reportingPendingStorageKey,
  reportingErrorMessage,
} from '../reportingState'

const AUTO_UNIT_KEY = 'ark_mobile_domestic_auto_unit'

function readPending(ownerId) {
  if (ownerId == null) return null
  try {
    const storageKey = reportingPendingStorageKey(ownerId)
    let raw = localStorage.getItem(storageKey)
    if (!raw) {
      const legacy = JSON.parse(localStorage.getItem(REPORTING_PENDING_KEY) || 'null')
      if (legacy?.ownerId != null && String(legacy.ownerId) === String(ownerId)) {
        raw = JSON.stringify(legacy)
        localStorage.setItem(storageKey, raw)
        localStorage.removeItem(REPORTING_PENDING_KEY)
      }
    }
    const value = JSON.parse(raw || 'null')
    if (!value?.requestId || !value?.scan || !value?.code || !(value?.qty > 0)) return null
    return value
  } catch {
    return null
  }
}

function readAutoUnit() {
  try { return localStorage.getItem(AUTO_UNIT_KEY) !== '0' } catch { return true }
}

function pulse(success) {
  try { navigator.vibrate?.(success ? [55] : [100, 70, 100]) } catch { /* optional feedback */ }
  try {
    const AudioContext = globalThis.AudioContext || globalThis.webkitAudioContext
    if (!AudioContext) return
    const context = new AudioContext()
    const oscillator = context.createOscillator()
    const gain = context.createGain()
    oscillator.frequency.value = success ? 880 : 220
    gain.gain.value = 0.08
    oscillator.connect(gain)
    gain.connect(context.destination)
    oscillator.start()
    oscillator.stop(context.currentTime + (success ? 0.12 : 0.22))
    oscillator.addEventListener('ended', () => context.close())
  } catch { /* browser autoplay policy may block sound */ }
}

export function useMobileDomesticReporting() {
  const auth = useAuthStore()
  const busy = ref(false)
  const scanned = ref(null)
  const scannedCode = ref(null)
  const images = ref([])
  const todayRecords = ref([])
  const todayCount = ref(0)
  const todayQty = ref(0)
  const pending = ref(readPending(auth.user?.id ?? null))
  const autoUnit = ref(readAutoUnit())
  const status = ref({ tone: 'ready', title: '准备扫码', detail: '打开摄像头或按下扫描枪按键' })
  let historyGeneration = 0
  let imageGeneration = 0

  const userName = computed(() => (
    auth.user?.real_name || auth.user?.name || auth.user?.username || '当前用户'
  ))
  const userId = computed(() => auth.user?.id ?? null)
  const pendingOwnerMismatch = computed(() => (
    pending.value?.ownerId != null && String(pending.value.ownerId) !== String(userId.value)
  ))

  watch(autoUnit, value => {
    try { localStorage.setItem(AUTO_UNIT_KEY, value ? '1' : '0') } catch { /* optional preference */ }
  })

  function setStatus(tone, title, detail) {
    status.value = { tone, title, detail }
  }

  function redirectExpired() {
    window.location.href = `/login?redirect=${encodeURIComponent('/domestic/reporting')}`
  }

  function clearImageUrls() {
    images.value.forEach(item => URL.revokeObjectURL(item.url))
    images.value = []
  }

  async function loadImage(index) {
    const target = images.value[index]
    if (!target || target.loading) return
    const generation = ++imageGeneration
    images.value.forEach((item, itemIndex) => {
      if (itemIndex !== index && item.url) URL.revokeObjectURL(item.url)
    })
    images.value = images.value.map((item, itemIndex) => ({
      ...item,
      url: itemIndex === index ? item.url : null,
      loading: itemIndex === index,
      error: false,
    }))
    try {
      const url = await fetchMobileReportingImage(target.path)
      if (generation !== imageGeneration) {
        URL.revokeObjectURL(url)
        return
      }
      images.value[index] = { ...images.value[index], url, loading: false }
      images.value = [...images.value]
    } catch {
      if (generation !== imageGeneration) return
      images.value[index] = { ...images.value[index], loading: false, error: true }
      images.value = [...images.value]
    }
  }

  function loadImages(scan) {
    imageGeneration += 1
    clearImageUrls()
    images.value = collectRequirementImagePaths(scan).map(path => ({
      path, url: null, loading: false, error: false,
    }))
    if (images.value.length) loadImage(0)
  }

  async function loadHistory() {
    const generation = ++historyGeneration
    try {
      const data = await getMobileReportingHistory()
      if (generation !== historyGeneration) return
      todayRecords.value = data.records || []
      todayCount.value = data.today_count || 0
      todayQty.value = data.today_qty || 0
    } catch (error) {
      if (generation === historyGeneration && isReportingAuthError(error)) redirectExpired()
    }
  }

  function persistPending(value) {
    localStorage.setItem(reportingPendingStorageKey(value.ownerId), JSON.stringify(value))
    pending.value = value
  }

  function clearPending(requestId) {
    if (pending.value?.requestId !== requestId) return
    try {
      localStorage.removeItem(reportingPendingStorageKey(pending.value.ownerId))
    } catch { /* stale value will replay safely */ }
    pending.value = null
  }

  async function submit(scan, code, qty, requestId) {
    if (pending.value && pending.value.requestId !== requestId) {
      setStatus('error', '存在待确认提交', '请重试上一笔，不能生成新的幂等号')
      pulse(false)
      return
    }
    if (userId.value == null) {
      setStatus('error', '登录状态不完整', '请重新登录后再提交报工')
      redirectExpired()
      return
    }
    const transaction = { scan, code, qty, requestId, ownerId: userId.value }
    try {
      persistPending(transaction)
    } catch {
      busy.value = false
      setStatus('error', '无法安全提交', '浏览器存储不可用，无法保存幂等请求，请检查隐私模式或存储空间')
      pulse(false)
      return
    }

    busy.value = true
    setStatus('loading', '正在提交报工', `${scan.product_name || '产品'} · ${scan.next_step?.process_name || '工序'}`)
    try {
      const result = await submitMobileDomesticReport(buildMobileReportPayload(scan, code, qty, requestId))
      clearPending(requestId)
      const unitCodes = (result.unit_codes || []).join('、')
      const suffix = unitCodes ? ` · ${unitCodes}` : ''
      const replayed = result.replayed ? '（已去重）' : ''
      setStatus('success', result.replayed ? '这笔已经报过了' : '报工成功',
        `${result.process_name || '工序'} · ${result.reported_qty || qty} 件${suffix}${replayed}`)
      scanned.value = null
      scannedCode.value = null
      imageGeneration += 1
      clearImageUrls()
      pulse(true)
      await loadHistory()
    } catch (error) {
      if (isReportingAuthError(error)) {
        redirectExpired()
      } else if (isDefinitiveSubmitFailure(error)) {
        clearPending(requestId)
        setStatus('error', '报工失败', reportingErrorMessage(error, '服务端拒绝了这次报工'))
        pulse(false)
      } else {
        setStatus('error', '提交结果未知', '网络可能在响应前中断，请重试同一笔；系统会沿用幂等号，不会重复累计')
        pulse(false)
      }
    } finally {
      busy.value = false
    }
  }

  async function handleCode(raw, source = 'manual') {
    if (busy.value || scanned.value) {
      setStatus('error', '上一笔尚未完成', '请先确认或取消当前报工')
      pulse(false)
      return false
    }
    if (pending.value) {
      setStatus('error', '存在待确认提交', '请先重试上一笔，确认结果后再继续扫码')
      pulse(false)
      return false
    }
    const code = parseDomesticReportingCode(raw)
    if (!code) {
      setStatus('error', '二维码无效', String(raw || '').trim().startsWith('ARK-P:')
        ? '这是外贸流转卡，本页面只处理内贸报工'
        : BLOCK_MESSAGES.SIGN_INVALID)
      pulse(false)
      return false
    }

    busy.value = true
    setStatus('loading', '二维码已读取', '正在校验订单与当前工序')
    try {
      const result = await scanMobileDomesticCode(code)
      if (!result.can_submit) {
        setStatus('error', '暂时不能报工', result.block_message || BLOCK_MESSAGES[result.block_reason] || '请联系跟单')
        pulse(false)
        return false
      }
      scanned.value = result
      scannedCode.value = code
      loadImages(result)
      if (result.report_mode === 'unit' && source === 'keyboard' && autoUnit.value) {
        await submit(result, code, 1, newRequestId())
      } else {
        setStatus('ready', '信息已校验', '确认产品、工序和数量后提交')
      }
      return true
    } catch (error) {
      if (isReportingAuthError(error)) redirectExpired()
      else {
        setStatus('error', '扫码失败', reportingErrorMessage(error, '请检查网络后重试'))
        pulse(false)
      }
      return false
    } finally {
      busy.value = false
    }
  }

  function cancelConfirmation() {
    if (busy.value) return
    scanned.value = null
    scannedCode.value = null
    imageGeneration += 1
    clearImageUrls()
    if (pending.value) {
      setStatus('error', '有一笔提交结果待确认', '请使用页面上的“重试同一笔”，系统不会重复累计')
    } else {
      setStatus('ready', '准备扫码', '打开摄像头或按下扫描枪按键')
    }
  }

  function confirmSubmission(qty) {
    if (!scanned.value || !scannedCode.value || busy.value || pending.value) return
    submit(scanned.value, scannedCode.value, qty, newRequestId())
  }

  function retryPending() {
    if (!pending.value || busy.value || pendingOwnerMismatch.value) return
    submit(pending.value.scan, pending.value.code, pending.value.qty, pending.value.requestId)
  }

  async function revoke(record) {
    if (busy.value || pending.value) {
      setStatus('error', '暂不能撤销', '请先处理待确认提交')
      return
    }
    try {
      await confirmDanger('撤销', `${record.process_name} × ${record.report_qty} 件`, '撤销后本道累计数量会相应减少。')
    } catch {
      return
    }
    busy.value = true
    try {
      await revokeMobileDomesticReport(record.log_id)
      setStatus('success', '撤销成功', `${record.process_name} · ${record.report_qty} 件`)
      pulse(true)
      await loadHistory()
    } catch (error) {
      if (isReportingAuthError(error)) redirectExpired()
      else {
        setStatus('error', '撤销失败', reportingErrorMessage(error, '请稍后重试'))
        pulse(false)
      }
    } finally {
      busy.value = false
    }
  }

  async function logout() {
    await auth.logout(`/login?redirect=${encodeURIComponent('/domestic/reporting')}`)
  }

  onMounted(() => {
    loadHistory()
    if (pending.value) {
      setStatus('error', '发现待确认提交', pendingOwnerMismatch.value
        ? '这笔属于另一账号，请切换回原账号处理'
        : '请重试同一笔，后端会按幂等号返回首次结果')
    }
  })
  onBeforeUnmount(() => {
    historyGeneration += 1
    imageGeneration += 1
    clearImageUrls()
  })

  return {
    autoUnit, busy, images, pending, pendingOwnerMismatch, scanned, status,
    todayCount, todayQty, todayRecords, userName,
    cancelConfirmation, confirmSubmission, handleCode, loadHistory, loadImage, logout, retryPending, revoke,
  }
}
