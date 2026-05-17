/**
 * 运单上传 — 业务逻辑 composable
 *
 * 集中:
 *   - 表单 state (form / mode / previewUrl / OCR 状态 / 提交状态)
 *   - 文件 OCR 上传流程 (handleFileChange + handleBeforeUpload + clearImage)
 *   - 手录模式 (onWaybillFocus / onWaybillBlur / clearManualInput + 自动识别 carrier)
 *   - 去重检查 (checkDuplicate)
 *   - 提交入库 (handleSubmit + 错误映射)
 *   - 重置 (resetAll / resetRightPanel)
 *
 * 返回的 ref 直接绑定到 template 即可,主页面只负责布局。
 */
import { ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { uploadOCR, checkWaybill, createWaybill } from '@/api/tracking'


// 物流商运单号格式识别
function detectCarrier(waybillNo) {
  if (!waybillNo || typeof waybillNo !== 'string') return '未知'
  const no = waybillNo.trim().replace(/\s+/g, '')

  const UPS_REGEX = /^1Z[0-9A-Z]{6}[0-9]{2}[0-9]{8}$/i
  const FEDEX_REGEX = /^((\d{12})|(\d{15})|(\d{20})|(\d{22})|(96\d{20})|(92\d{20}))$/
  const DHL_REGEX = /^(\d{10,11}|[A-Z]{2}\d{8,9}[A-Z]{2}|JJD\d{16,22}|GM\d{16,22})$/i

  if (UPS_REGEX.test(no)) return 'UPS'
  if (FEDEX_REGEX.test(no)) return 'FedEx'
  if (DHL_REGEX.test(no)) return 'DHL'
  return '未知'
}


export function useWaybillUpload() {
  // ── State ──────────────────────────────────────────
  const mode = ref('')          // '' | 'ocr' | 'manual'
  const previewUrl = ref('')
  const ocrLoading = ref(false)
  const ocrPartial = ref(false)
  const ocrError = ref('')
  const duplicateInfo = ref(null)
  const checkingDuplicate = ref(false)
  const submitting = ref(false)
  const successVisible = ref(false)

  const uploadRef = ref(null)
  const formRef = ref(null)
  let currentFile = null

  const form = reactive({
    waybill_no: '',
    carrier: '',
    recipient_name: '',
    recipient_country: '',
    ship_date: '',
    entry_source: 'manual',
  })

  const resultData = reactive({
    waybill_no: '',
    carrier: '',
    recipient_name: '',
    recipient_country: '',
    ship_date: '',
    short_link: '',
    notifyTemplate: '',
    tracking_status: '',
    tracking_status_text: '',
    estimated_delivery_date: '',
    last_event_time: '',
    poll_ok: false,
    poll_error: '',
  })

  const formRules = {
    waybill_no: [{ required: true, message: '请填写运单号', trigger: 'blur' }],
    carrier: [{ required: true, message: '请选择物流商', trigger: 'change' }],
    recipient_name: [{ required: true, message: '请填写收件人姓名', trigger: 'blur' }],
    recipient_country: [{ required: true, message: '请填写收件国家', trigger: 'blur' }],
    ship_date: [{ required: true, message: '请选择发件日期', trigger: 'change' }],
  }

  // ── Helpers ────────────────────────────────────────
  function disableFutureDate(date) {
    return date > new Date()
  }

  function resetRightPanel() {
    ocrLoading.value = false
    ocrPartial.value = false
    ocrError.value = ''
    duplicateInfo.value = null
  }

  function resetAll() {
    mode.value = ''
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
    currentFile = null
    uploadRef.value?.clearFiles()
    formRef.value?.resetFields()
    Object.assign(form, {
      waybill_no: '',
      carrier: '',
      recipient_name: '',
      recipient_country: '',
      ship_date: '',
      entry_source: 'manual',
    })
    resetRightPanel()
  }

  // ── Image upload + OCR ─────────────────────────────
  function handleBeforeUpload(file) {
    const allowedTypes = ['image/jpeg', 'image/png', 'image/webp']
    if (!allowedTypes.includes(file.type)) {
      ElMessage.error('格式不支持，仅接受 JPG / PNG / WEBP')
      return false
    }
    if (file.size > 10 * 1024 * 1024) {
      ElMessage.error('文件不能超过 10MB')
      return false
    }
    return true
  }

  async function handleFileChange(uploadFile) {
    const file = uploadFile.raw
    if (!handleBeforeUpload(file)) return

    currentFile = file
    mode.value = 'ocr'
    form.entry_source = 'ocr'

    previewUrl.value = URL.createObjectURL(file)
    resetRightPanel()
    ocrLoading.value = true

    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await uploadOCR(formData)
      const data = res.data
      if (!data) throw new Error('响应数据为空')

      form.waybill_no = (data.waybill_no || '').trim().replace(/\s+/g, '')
      form.carrier = data.carrier || detectCarrier(data.waybill_no) || ''
      form.recipient_name = data.recipient_name || ''
      form.recipient_country = data.recipient_country || ''
      form.ship_date = data.ship_date || ''

      if (data.ocr_confidence === 'failed') {
        ocrError.value = '未能识别运单信息，请确认图片清晰度或手动录入'
      } else if (data.ocr_confidence === 'partial') {
        ocrPartial.value = true
      }

      if (form.waybill_no) {
        await checkDuplicate(form.waybill_no)
      }
    } catch (err) {
      const status = err.response?.status
      if (status === 504) {
        ocrError.value = 'AI 识别超时，请重试或切换至手动录入'
      } else if (status === 422) {
        ocrError.value = '文件格式不支持或超过大小限制'
      } else if (err.code === 'ERR_NETWORK' || err.message?.includes('Network')) {
        ocrError.value = '网络异常，请检查网络连接后重试'
      } else {
        ocrError.value = 'AI 识别服务暂时不可用，请稍后重试或手动录入'
      }
    } finally {
      ocrLoading.value = false
    }
  }

  function clearImage() {
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
    currentFile = null
    mode.value = ''
    form.entry_source = 'manual'
    uploadRef.value?.clearFiles()
    resetAll()
  }

  // ── Manual input ───────────────────────────────────
  function onWaybillFocus() {
    if (mode.value === 'ocr') return
    if (form.waybill_no) {
      mode.value = 'manual'
    }
  }

  function onWaybillBlur() {
    if (!form.waybill_no) return
    form.waybill_no = form.waybill_no.trim().replace(/\s+/g, '')
    mode.value = 'manual'

    const detected = detectCarrier(form.waybill_no)
    if (!form.carrier) {
      form.carrier = detected
    }
    checkDuplicate(form.waybill_no)
  }

  function clearManualInput() {
    if (mode.value === 'manual') {
      mode.value = ''
      duplicateInfo.value = null
      form.carrier = ''
    }
  }

  // ── Duplicate ──────────────────────────────────────
  async function checkDuplicate(waybillNo) {
    if (!waybillNo) return
    checkingDuplicate.value = true
    duplicateInfo.value = null

    try {
      const res = await checkWaybill(waybillNo)
      if (res.exists) {
        duplicateInfo.value = res.data
      }
    } catch (err) {
      console.warn('去重检查失败:', err.message)
    } finally {
      checkingDuplicate.value = false
    }
  }

  // ── Submit ─────────────────────────────────────────
  async function handleSubmit() {
    if (!formRef.value) return

    const valid = await formRef.value.validate().catch(() => false)
    if (!valid) return

    form.waybill_no = form.waybill_no.trim().replace(/\s+/g, '')
    submitting.value = true

    try {
      const res = await createWaybill({
        waybill_no: form.waybill_no,
        carrier: form.carrier,
        recipient_name: form.recipient_name,
        recipient_country: form.recipient_country,
        ship_date: form.ship_date,
        entry_source: form.entry_source,
      })

      const data = res.data
      resultData.waybill_no = data.waybill_no || form.waybill_no
      resultData.carrier = data.carrier || form.carrier
      resultData.recipient_name = data.recipient_name || form.recipient_name
      resultData.recipient_country = data.recipient_country || form.recipient_country
      resultData.ship_date = data.ship_date || form.ship_date
      resultData.short_link = data.short_link || ''
      resultData.tracking_status = data.tracking_status || 'pending'
      resultData.tracking_status_text = data.tracking_status_text || ''
      resultData.estimated_delivery_date = data.estimated_delivery_date || ''
      resultData.last_event_time = data.last_event_time || ''
      resultData.poll_ok = data.poll_ok || false
      resultData.poll_error = data.poll_error || ''
      const estText = resultData.estimated_delivery_date || 'TBD'
      resultData.notifyTemplate =
        `Hi ${resultData.recipient_name}, great news! Your order has been picked up by ${resultData.carrier}. Tracking#: ${resultData.waybill_no}. Expected delivery: ${estText}. I'll keep an eye on it for you!`

      successVisible.value = true
      ElMessage.success('运单录入成功')
    } catch (err) {
      const status = err.response?.status
      const detail = err.response?.data?.detail

      if (status === 409) {
        duplicateInfo.value = detail?.data || null
        ElMessage.warning('运单号已存在，不允许重复录入')
      } else if (status === 422) {
        const errors = detail?.data?.errors || []
        if (errors.length > 0) {
          ElMessage.error(errors.map(e => e.message).join('；'))
        } else {
          ElMessage.error('字段校验失败，请检查输入内容')
        }
      } else {
        ElMessage.error('提交失败，请稍后重试')
      }
    } finally {
      submitting.value = false
    }
  }

  return {
    // refs (DOM)
    uploadRef, formRef,
    // state
    mode, previewUrl, ocrLoading, ocrPartial, ocrError,
    duplicateInfo, checkingDuplicate, submitting, successVisible,
    form, resultData, formRules,
    // methods
    handleBeforeUpload, handleFileChange, clearImage,
    onWaybillFocus, onWaybillBlur, clearManualInput,
    handleSubmit, resetAll,
    disableFutureDate,
  }
}
