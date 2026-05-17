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
    <WaybillSuccessDialog
      v-model="successVisible"
      :result-data="resultData"
      @continue="resetAll"
    />
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { UploadFilled, Document, Warning } from '@element-plus/icons-vue'
import { uploadOCR, checkWaybill, createWaybill } from '@/api/tracking'
import WaybillSuccessDialog from './components/WaybillSuccessDialog.vue'

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
</style>
