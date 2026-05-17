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
import { useWaybillUpload } from './composables/useWaybillUpload'
import { UploadFilled, Document, Warning } from '@element-plus/icons-vue'
import WaybillSuccessDialog from './components/WaybillSuccessDialog.vue'

const {
  uploadRef, formRef,
  mode, previewUrl, ocrLoading, ocrPartial, ocrError,
  duplicateInfo, checkingDuplicate, submitting, successVisible,
  form, resultData, formRules,
  handleBeforeUpload, handleFileChange, clearImage,
  onWaybillFocus, onWaybillBlur, clearManualInput,
  handleSubmit, resetAll,
  disableFutureDate,
} = useWaybillUpload()
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
