<template>
  <div class="waybill-upload-page">
    <el-page-header content="运单上传" @back="$router.back()" />

    <div class="upload-layout">
      <!-- 左侧：上传区 + 手录运单号 -->
      <div class="left-panel">
        <!-- 图片上传区 -->
        <div class="upload-section">
          <el-upload
            ref="uploadRef"
            class="waybill-uploader"
            :class="{ 'is-disabled': mode === 'manual' }"
            drag
            :auto-upload="false"
            :show-file-list="false"
            accept="image/jpeg,image/png,image/webp"
            :before-upload="handleBeforeUpload"
            :on-change="handleFileChange"
            :disabled="mode === 'manual'"
          >
            <template v-if="previewUrl">
              <div class="preview-wrapper">
                <img :src="previewUrl" class="preview-image" alt="运单预览" />
                <div class="preview-actions">
                  <el-button
                    size="small"
                    type="danger"
                    plain
                    @click.stop="clearImage"
                  >
                    删除图片
                  </el-button>
                </div>
              </div>
            </template>
            <template v-else>
              <div v-if="mode === 'manual'" class="upload-disabled-mask">
                <el-icon :size="40"><Warning /></el-icon>
                <p>手录模式，图片识别不可用</p>
              </div>
              <template v-else>
                <el-icon class="el-icon--upload" :size="48"><UploadFilled /></el-icon>
                <div class="el-upload__text">
                  拖拽图片到此处，或<em>点击上传</em>
                </div>
                <div class="el-upload__tip">
                  支持 JPG / PNG / WEBP，最大 10MB
                </div>
              </template>
            </template>
          </el-upload>
        </div>

        <!-- 手录运单号 -->
        <div class="manual-input-section">
          <div class="section-label">手动录入运单号</div>
          <el-input
            v-model="form.waybill_no"
            placeholder="输入运单号，失焦后自动识别物流商"
            :disabled="mode === 'ocr'"
            clearable
            @focus="onWaybillFocus"
            @blur="onWaybillBlur"
            @clear="clearManualInput"
          >
            <template #prefix>
              <el-icon><Document /></el-icon>
            </template>
          </el-input>
        </div>
      </div>

      <!-- 右侧：AI 识别结果 / 手录表单 -->
      <div class="right-panel">
        <div class="right-panel-title">
          <span>{{ mode === 'ocr' ? 'AI 识别结果' : '运单信息' }}</span>
          <el-tag v-if="mode === 'ocr'" type="success" size="small">图片模式</el-tag>
          <el-tag v-if="mode === 'manual'" type="info" size="small">手录模式</el-tag>
        </div>

        <!-- OCR loading 骨架屏 -->
        <template v-if="ocrLoading">
          <el-skeleton :rows="5" animated style="padding: 16px" />
        </template>

        <template v-else>
          <!-- 去重状态提示 -->
          <el-alert
            v-if="duplicateInfo"
            title="运单号重复"
            type="warning"
            :closable="false"
            show-icon
            style="margin-bottom: 16px"
          >
            <template #default>
              该运单号 <strong>{{ duplicateInfo.waybill_no }}</strong> 已于
              {{ duplicateInfo.created_at }} 由 {{ duplicateInfo.created_by }} 录入，当前状态：{{ duplicateInfo.status }}。
              如需修改请联系管理员。
            </template>
          </el-alert>

          <!-- OCR 部分识别提示 -->
          <el-alert
            v-if="ocrPartial"
            title="识别不完整"
            type="info"
            :closable="false"
            show-icon
            style="margin-bottom: 16px"
          >
            以下字段识别不完整，请手动补全后提交
          </el-alert>

          <!-- OCR 失败提示 -->
          <el-alert
            v-if="ocrError"
            :title="ocrError"
            type="error"
            :closable="true"
            show-icon
            style="margin-bottom: 16px"
            @close="ocrError = ''"
          />

          <!-- 字段表单 -->
          <el-form
            ref="formRef"
            :model="form"
            :rules="formRules"
            label-width="90px"
            :disabled="!!duplicateInfo"
          >
            <el-form-item label="运单号" prop="waybill_no">
              <el-input
                v-model="form.waybill_no"
                :disabled="mode === 'ocr' || !!duplicateInfo"
                placeholder="运单号"
                clearable
              />
            </el-form-item>

            <el-form-item label="物流商" prop="carrier">
              <el-select
                v-model="form.carrier"
                placeholder="请选择或识别物流商"
                style="width: 100%"
              >
                <el-option label="FedEx" value="FedEx" />
                <el-option label="DHL" value="DHL" />
                <el-option label="UPS" value="UPS" />
                <el-option label="未知" value="未知" />
              </el-select>
            </el-form-item>

            <el-form-item label="收件人" prop="recipient_name">
              <el-input
                v-model="form.recipient_name"
                :class="{ 'field-missing': ocrPartial && !form.recipient_name }"
                placeholder="收件人姓名"
              />
            </el-form-item>

            <el-form-item label="收件国家" prop="recipient_country">
              <el-input
                v-model="form.recipient_country"
                :class="{ 'field-missing': ocrPartial && !form.recipient_country }"
                placeholder="如：美国、德国"
              />
            </el-form-item>

            <el-form-item label="发件日期" prop="ship_date">
              <el-date-picker
                v-model="form.ship_date"
                type="date"
                placeholder="选择发件日期"
                format="YYYY-MM-DD"
                value-format="YYYY-MM-DD"
                :disabled-date="disableFutureDate"
                style="width: 100%"
              />
            </el-form-item>

            <el-form-item>
              <el-button
                type="primary"
                :loading="submitting"
                :disabled="!!duplicateInfo || checkingDuplicate"
                @click="handleSubmit"
                style="width: 100%"
              >
                {{ submitting ? '提交中...' : '确认提交' }}
              </el-button>
            </el-form-item>
          </el-form>
        </template>
      </div>
    </div>

    <!-- 提交成功弹窗 -->
    <el-dialog
      v-model="successVisible"
      width="560px"
      :show-close="false"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      align-center
      class="success-dialog"
      destroy-on-close
    >
      <template #header><div /></template>

      <div class="success-content">
        <!-- 动画成功图标 -->
        <div class="success-icon-wrap">
          <div class="success-circle">
            <svg class="checkmark" viewBox="0 0 52 52">
              <circle class="checkmark-circle" cx="26" cy="26" r="25" fill="none" />
              <path class="checkmark-check" fill="none" d="M14.1 27.2l7.1 7.2 16.7-16.8" />
            </svg>
            <div class="ripple ripple-1" />
            <div class="ripple ripple-2" />
            <div class="ripple ripple-3" />
          </div>
          <div class="confetti-wrap">
            <span v-for="n in 12" :key="n" class="confetti" :class="`confetti-${n}`" />
          </div>
        </div>

        <h2 class="success-title">提交成功</h2>
        <p class="success-subtitle">运单信息已成功录入系统</p>

        <div class="gold-divider" />

        <!-- 运单信息卡片 -->
        <div class="info-card">
          <div class="info-row">
            <span class="info-label">
              <el-icon><Document /></el-icon>
              运单号
            </span>
            <span class="info-value">{{ resultData.waybill_no }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">
              <el-icon><Van /></el-icon>
              物流商
            </span>
            <span class="info-value">{{ resultData.carrier }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">
              <el-icon><User /></el-icon>
              收件人
            </span>
            <span class="info-value">{{ resultData.recipient_name }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">
              <el-icon><Location /></el-icon>
              收件国家
            </span>
            <span class="info-value">{{ resultData.recipient_country }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">
              <el-icon><Calendar /></el-icon>
              发件日期
            </span>
            <span class="info-value">{{ resultData.ship_date }}</span>
          </div>
        </div>

        <!-- 物流状态区域 -->
        <div class="copy-section">
          <div class="copy-label">
            <el-icon><Van /></el-icon>
            <span>当前物流状态</span>
          </div>
          <div class="tracking-status-card">
            <div class="tracking-status-row">
              <span
                class="tracking-status-badge"
                :class="`status-${resultData.tracking_status || 'pending'}`"
              >
                {{ resultData.tracking_status_text || '待查询' }}
              </span>
              <span v-if="resultData.last_event_time" class="tracking-status-time">
                {{ resultData.last_event_time }}
              </span>
            </div>
            <div v-if="resultData.estimated_delivery_date" class="tracking-status-delivery">
              预计送达：{{ resultData.estimated_delivery_date }}
            </div>
            <div v-if="resultData.poll_error" class="tracking-status-error">
              轮询失败：{{ resultData.poll_error }}
            </div>
          </div>
        </div>

        <!-- 短链接区域 -->
        <div v-if="resultData.short_link" class="copy-section">
          <div class="copy-label">
            <el-icon><Link /></el-icon>
            <span>查询短链接</span>
          </div>
          <div class="copy-box">
            <span class="copy-text">{{ resultData.short_link }}</span>
            <el-button
              type="primary"
              class="copy-btn"
              :class="{ copied: copiedLink }"
              @click="copyLink"
            >
              <el-icon v-if="!copiedLink"><CopyDocument /></el-icon>
              <el-icon v-else><Check /></el-icon>
              <span>{{ copiedLink ? '已复制' : '复制' }}</span>
            </el-button>
          </div>
        </div>

        <!-- 发货通知模板 -->
        <div class="copy-section">
          <div class="copy-label">
            <el-icon><ChatDotRound /></el-icon>
            <span>发货通知模板</span>
          </div>
          <div class="notify-template">
            <pre class="template-text">{{ resultData.notifyTemplate }}</pre>
            <el-button
              type="primary"
              class="copy-btn template-copy-btn"
              :class="{ copied: copiedTemplate }"
              @click="copyTemplate"
            >
              <el-icon v-if="!copiedTemplate"><CopyDocument /></el-icon>
              <el-icon v-else><Check /></el-icon>
              <span>{{ copiedTemplate ? '已复制' : '复制' }}</span>
            </el-button>
          </div>
        </div>

        <!-- 底部按钮 -->
        <div class="dialog-footer">
          <el-button class="btn-secondary" @click="handleClose">关闭</el-button>
          <el-button type="primary" class="btn-primary" @click="handleContinue">继续上传</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  UploadFilled, Document, Warning, Van, User, Location,
  Calendar, Link, CopyDocument, Check, ChatDotRound
} from '@element-plus/icons-vue'
import { uploadOCR, checkWaybill, createWaybill } from '@/api/tracking'

const router = useRouter()

// -- State --
const mode = ref('')          // '' | 'ocr' | 'manual'
const previewUrl = ref('')    // 图片预览 URL
const ocrLoading = ref(false) // OCR loading
const ocrPartial = ref(false) // OCR partial fields null
const ocrError = ref('')      // OCR error message
const duplicateInfo = ref(null) // Duplicate check result
const checkingDuplicate = ref(false)
const submitting = ref(false)

const uploadRef = ref(null)
const formRef = ref(null)
let currentFile = null

// -- Success dialog --
const successVisible = ref(false)
const copiedLink = ref(false)
const copiedTemplate = ref(false)

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

const form = reactive({
  waybill_no: '',
  carrier: '',
  recipient_name: '',
  recipient_country: '',
  ship_date: '',
  entry_source: 'manual',
})

const formRules = {
  waybill_no: [{ required: true, message: '请填写运单号', trigger: 'blur' }],
  carrier: [{ required: true, message: '请选择物流商', trigger: 'change' }],
  recipient_name: [{ required: true, message: '请填写收件人姓名', trigger: 'blur' }],
  recipient_country: [{ required: true, message: '请填写收件国家', trigger: 'blur' }],
  ship_date: [{ required: true, message: '请选择发件日期', trigger: 'change' }],
}

// -- Carrier detection --
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

// -- Image upload handlers --
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

// -- Manual mode handlers --
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

// -- Duplicate check --
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

// -- Submit --
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

    copiedLink.value = false
    copiedTemplate.value = false
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

// -- Success dialog actions --
async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(textarea)
    return ok
  }
}

async function copyLink() {
  const ok = await copyToClipboard(resultData.short_link)
  if (ok) {
    copiedLink.value = true
    ElMessage.success('短链接已复制')
    setTimeout(() => (copiedLink.value = false), 2500)
  } else {
    ElMessage.error('复制失败')
  }
}

async function copyTemplate() {
  const ok = await copyToClipboard(resultData.notifyTemplate)
  if (ok) {
    copiedTemplate.value = true
    ElMessage.success('通知模板已复制')
    setTimeout(() => (copiedTemplate.value = false), 2500)
  } else {
    ElMessage.error('复制失败')
  }
}

function handleClose() {
  successVisible.value = false
}

function handleContinue() {
  successVisible.value = false
  resetAll()
}

// -- Utils --
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
</script>

<style scoped>
.waybill-upload-page {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
}

.upload-layout {
  display: flex;
  gap: 24px;
  margin-top: 24px;
}

.left-panel {
  flex: 0 0 45%;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.right-panel {
  flex: 1;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 24px;
}

.right-panel-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-label {
  font-size: 13px;
  color: #606266;
  margin-bottom: 8px;
}

.waybill-uploader {
  width: 100%;
}

.waybill-uploader :deep(.el-upload-dragger) {
  width: 100%;
  height: 220px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.waybill-uploader.is-disabled :deep(.el-upload-dragger) {
  cursor: not-allowed;
  background: #f5f7fa;
}

.preview-wrapper {
  width: 100%;
  height: 100%;
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
}

.preview-image {
  max-width: 100%;
  max-height: 170px;
  object-fit: contain;
  border-radius: 4px;
}

.upload-disabled-mask {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: #c0c4cc;
}

.upload-disabled-mask p {
  margin: 0;
  font-size: 13px;
}

.field-missing :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px #f56c6c inset;
}

/* ========== 成功弹窗 ========== */
:deep(.success-dialog) {
  .el-dialog__header {
    display: none;
  }

  .el-dialog__body {
    padding: 0;
  }

  .el-dialog {
    border-radius: 20px;
    overflow: hidden;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.12);
  }
}

.success-content {
  padding: 36px 32px 28px;
  text-align: center;
}

/* ---- 动画成功图标 ---- */
.success-icon-wrap {
  position: relative;
  width: 80px;
  height: 80px;
  margin: 0 auto 20px;
}

.success-circle {
  position: relative;
  width: 80px;
  height: 80px;
  z-index: 2;
}

.checkmark {
  width: 80px;
  height: 80px;
  display: block;
}

.checkmark-circle {
  stroke: #d4af6e;
  stroke-width: 3;
  stroke-dasharray: 166;
  stroke-dashoffset: 166;
  stroke-linecap: round;
  animation: strokeCircle 0.6s cubic-bezier(0.65, 0, 0.45, 1) forwards;
}

.checkmark-check {
  stroke: #d4af6e;
  stroke-width: 3;
  stroke-dasharray: 48;
  stroke-dashoffset: 48;
  stroke-linecap: round;
  stroke-linejoin: round;
  animation: strokeCheck 0.4s cubic-bezier(0.65, 0, 0.45, 1) 0.5s forwards;
}

@keyframes strokeCircle {
  to { stroke-dashoffset: 0; }
}

@keyframes strokeCheck {
  to { stroke-dashoffset: 0; }
}

/* 扩散波纹 */
.ripple {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 80px;
  height: 80px;
  border: 2px solid #d4af6e;
  border-radius: 50%;
  transform: translate(-50%, -50%) scale(0.8);
  opacity: 0;
  pointer-events: none;
}

.ripple-1 {
  animation: rippleAnim 1.5s ease-out 0.8s forwards;
}
.ripple-2 {
  animation: rippleAnim 1.5s ease-out 1.1s forwards;
}
.ripple-3 {
  animation: rippleAnim 1.5s ease-out 1.4s forwards;
}

@keyframes rippleAnim {
  0% {
    transform: translate(-50%, -50%) scale(0.8);
    opacity: 0.5;
  }
  100% {
    transform: translate(-50%, -50%) scale(2);
    opacity: 0;
  }
}

/* 彩纸屑 */
.confetti-wrap {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 0;
  height: 0;
  z-index: 1;
  pointer-events: none;
}

.confetti {
  position: absolute;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  opacity: 0;
}

.confetti-1  { background: #d4af6e; transform: rotate(0deg)   translateX(0); --dx:  60px; --dy: -50px; animation: confettiFly 1.2s ease-out 0.6s forwards; }
.confetti-2  { background: #00d4ff; transform: rotate(30deg)  translateX(0); --dx:  50px; --dy: -60px; animation: confettiFly 1.2s ease-out 0.65s forwards; }
.confetti-3  { background: #54d468; transform: rotate(60deg)  translateX(0); --dx:  55px; --dy: -40px; animation: confettiFly 1.2s ease-out 0.7s forwards; }
.confetti-4  { background: #ff9f43; transform: rotate(90deg)  translateX(0); --dx:  45px; --dy: -55px; animation: confettiFly 1.2s ease-out 0.75s forwards; }
.confetti-5  { background: #d4af6e; transform: rotate(120deg) translateX(0); --dx: -40px; --dy: -50px; animation: confettiFly 1.2s ease-out 0.8s forwards; }
.confetti-6  { background: #ff6b6b; transform: rotate(150deg) translateX(0); --dx: -50px; --dy: -60px; animation: confettiFly 1.2s ease-out 0.85s forwards; }
.confetti-7  { background: #7c5cff; transform: rotate(180deg) translateX(0); --dx: -55px; --dy: -45px; animation: confettiFly 1.2s ease-out 0.9s forwards; }
.confetti-8  { background: #00d4ff; transform: rotate(210deg) translateX(0); --dx: -45px; --dy: -55px; animation: confettiFly 1.2s ease-out 0.95s forwards; }
.confetti-9  { background: #d4af6e; transform: rotate(240deg) translateX(0); --dx: -50px; --dy:  40px; animation: confettiFly 1.2s ease-out 1.0s forwards; }
.confetti-10 { background: #54d468; transform: rotate(270deg) translateX(0); --dx:  40px; --dy:  50px; animation: confettiFly 1.2s ease-out 1.05s forwards; }
.confetti-11 { background: #ff9f43; transform: rotate(300deg) translateX(0); --dx:  55px; --dy:  45px; animation: confettiFly 1.2s ease-out 1.1s forwards; }
.confetti-12 { background: #d4af6e; transform: rotate(330deg) translateX(0); --dx:  45px; --dy:  60px; animation: confettiFly 1.2s ease-out 1.15s forwards; }

@keyframes confettiFly {
  0% {
    opacity: 1;
    transform: translate(-50%, -50%) scale(1);
  }
  100% {
    opacity: 0;
    transform: translate(calc(-50% + var(--dx)), calc(-50% + var(--dy))) scale(0.3);
  }
}

/* ---- 标题区域 ---- */
.success-title {
  font-size: 22px;
  font-weight: 700;
  color: #1a1a2e;
  margin-bottom: 6px;
  animation: fadeInUp 0.5s ease 0.3s both;
}

.success-subtitle {
  font-size: 13px;
  color: #8b95a5;
  margin-bottom: 20px;
  animation: fadeInUp 0.5s ease 0.4s both;
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 金色分割线 */
.gold-divider {
  height: 2px;
  background: linear-gradient(90deg, transparent 0%, #d4af6e 30%, #e8d5a3 50%, #d4af6e 70%, transparent 100%);
  margin: 0 20px 20px;
  animation: fadeIn 0.5s ease 0.5s both;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* ---- 信息卡片 ---- */
.info-card {
  background: #fafbfe;
  border: 1px solid #e8ecf3;
  border-radius: 14px;
  padding: 16px 20px;
  margin-bottom: 20px;
  text-align: left;
  animation: fadeInUp 0.5s ease 0.55s both;
}

.info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px dashed #e8ecf3;
}

.info-row:last-child {
  border-bottom: none;
}

.info-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #8b95a5;
}

.info-label .el-icon {
  font-size: 15px;
  color: #d4af6e;
}

.info-value {
  font-size: 13px;
  font-weight: 600;
  color: #1a1a2e;
  font-family: 'SF Mono', 'Fira Code', monospace;
}

.info-value.highlight {
  color: #059669;
  background: #ecfdf5;
  padding: 2px 10px;
  border-radius: 6px;
}

/* ---- 复制区域 ---- */
.copy-section {
  margin-bottom: 16px;
  text-align: left;
  animation: fadeInUp 0.5s ease 0.65s both;
}

.copy-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 500;
  color: #4a5568;
  margin-bottom: 8px;
}

.copy-label .el-icon {
  font-size: 15px;
  color: #d4af6e;
}

.copy-box {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #fafbfe;
  border: 1px solid #e8ecf3;
  border-radius: 10px;
  padding: 4px 4px 4px 14px;
}

.copy-text {
  flex: 1;
  font-size: 13px;
  color: #2563eb;
  font-family: 'SF Mono', 'Fira Code', monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.copy-btn {
  flex-shrink: 0;
  height: 32px;
  padding: 0 14px;
  background: linear-gradient(135deg, #d4af6e, #c49b52);
  border: none;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  color: #fff;
  transition: all 0.25s ease;
}

.copy-btn:hover {
  background: linear-gradient(135deg, #c49b52, #b08d4f);
  box-shadow: 0 2px 10px rgba(212, 175, 110, 0.3);
}

.copy-btn.copied {
  background: linear-gradient(135deg, #059669, #16a34a);
}

/* 物流状态区域 */
.tracking-status-card {
  background: #fafbfe;
  border: 1px solid #e8ecf3;
  border-radius: 10px;
  padding: 12px 16px;
  text-align: left;
}
.tracking-status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.tracking-status-badge {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
}
.status-pending {
  color: #909399;
  background: #f4f4f5;
}
.status-picked_up {
  color: #409eff;
  background: #ecf5ff;
}
.status-in_transit {
  color: #e6a23c;
  background: #fdf6ec;
}
.status-out_for_delivery {
  color: #e6a23c;
  background: #fdf6ec;
}
.status-customs,
.status-customs_hold {
  color: #f56c6c;
  background: #fef0f0;
}
.status-delivered {
  color: #67c23a;
  background: #f0f9eb;
}
.status-returned {
  color: #909399;
  background: #f4f4f5;
}
.status-exception {
  color: #f56c6c;
  background: #fef0f0;
}
.tracking-status-time {
  font-size: 12px;
  color: #8b95a5;
  font-family: 'SF Mono', 'Fira Code', monospace;
}
.tracking-status-delivery {
  margin-top: 8px;
  font-size: 12px;
  color: #4a5568;
}
.tracking-status-error {
  margin-top: 8px;
  font-size: 12px;
  color: #f56c6c;
}

/* 通知模板区域 */
.notify-template {
  position: relative;
  background: #fafbfe;
  border: 1px solid #e8ecf3;
  border-radius: 10px;
  padding: 14px 16px;
  text-align: left;
}

.template-text {
  font-size: 12px;
  line-height: 1.8;
  color: #4a5568;
  font-family: inherit;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  padding-right: 60px;
}

.template-copy-btn {
  position: absolute;
  top: 10px;
  right: 10px;
}

/* ---- 底部按钮 ---- */
.dialog-footer {
  display: flex;
  justify-content: center;
  gap: 12px;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid #f0f2f7;
  animation: fadeInUp 0.5s ease 0.75s both;
}

.btn-secondary {
  height: 40px;
  padding: 0 28px;
  border-radius: 10px;
  font-size: 14px;
  border: 1px solid #dcdfe6;
  color: #4a5568;
}

.btn-secondary:hover {
  border-color: #d4af6e;
  color: #b08d4f;
}

.btn-primary {
  height: 40px;
  padding: 0 28px;
  background: linear-gradient(135deg, #d4af6e, #c49b52);
  border: none;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 500;
  color: #fff;
}

.btn-primary:hover {
  background: linear-gradient(135deg, #c49b52, #b08d4f);
  box-shadow: 0 4px 14px rgba(212, 175, 110, 0.3);
}

/* 弹窗进入动画 */
:deep(.success-dialog) .el-overlay-dialog {
  animation: overlayFade 0.3s ease;
}

@keyframes overlayFade {
  from { opacity: 0; }
  to { opacity: 1; }
}

:deep(.success-dialog) .el-dialog {
  animation: dialogBounce 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes dialogBounce {
  0% {
    opacity: 0;
    transform: scale(0.7) translateY(30px);
  }
  70% {
    transform: scale(1.02) translateY(-4px);
  }
  100% {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

/* 响应式 */
@media (max-width: 768px) {
  .success-content {
    padding: 24px 16px 20px;
  }
}
</style>
