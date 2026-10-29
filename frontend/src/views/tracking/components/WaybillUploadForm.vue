<template>
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
          :disabled="mode === 'manual' || ocrLoading || submitting || successVisible"
        >
          <div class="dragger-body">
          <template v-if="previewUrl">
            <div class="preview-wrapper">
              <img :src="previewUrl" class="preview-image" alt="运单预览" />
              <div class="preview-actions">
                <el-button
                  type="danger"
                  plain
                  :disabled="ocrLoading || submitting"
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
                支持 Ctrl+V / ⌘V 粘贴图片<br />
                支持 JPG / PNG / WEBP，最大 10MB
              </div>
            </template>
          </template>
          </div>
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
    <div class="right-panel lg-card is-static">
      <div class="right-panel-title">
        <span>{{ mode === 'ocr' ? 'AI 识别结果' : '运单信息' }}</span>
        <StatusBadge v-if="mode === 'ocr'" type="success" size="small">图片模式</StatusBadge>
        <StatusBadge v-if="mode === 'manual'" type="info" size="small">手录模式</StatusBadge>
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
            <template v-if="linkable && linkBlocked">{{ linkBlocked }}</template>
            <template v-else-if="linkable">
              一张运单可以装多张出库单，确认是同一票货就直接关联。
              <div class="duplicate-actions">
                <GlassButton variant="primary" :loading="linking" @click="$emit('link-existing', duplicateInfo)">
                  关联这张已有运单
                </GlassButton>
              </div>
            </template>
            <template v-else>如需修改请联系管理员。</template>
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
        <el-form label-position="top"
          ref="formRef"
          :model="form"
          :rules="formRules"
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
              class="full-width"
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
              class="full-width"
            />
          </el-form-item>

          <el-form-item>
            <GlassButton
              variant="primary"
              full-width
              :loading="submitting"
              :disabled="!!duplicateInfo || checkingDuplicate"
              @click="handleSubmit"
            >
              {{ submitting ? '提交中...' : submitText }}
            </GlassButton>
          </el-form-item>
        </el-form>
      </template>
    </div>
  </div>
</template>

<script setup>
/**
 * 运单上传表单（图片 OCR / 手录 + 去重 + 提交）：物流跟踪「运单上传」页与验货单「上传物流单」弹框共用。
 * 状态与流程全在 useWaybillUpload，由宿主创建后整体传入 —— 宿主还要用同一份状态驱动成功弹窗。
 */
import { UploadFilled, Document, Warning } from '@element-plus/icons-vue'

const props = defineProps({
  state: { type: Object, required: true },
  // 运单号已存在时允许「关联已有运单」（验货单弹框用）
  linkable: { type: Boolean, default: false },
  linking: { type: Boolean, default: false },
  // 已有运单不能关联时的原因（如不在查看范围内），有值时替代关联按钮
  linkBlocked: { type: String, default: '' },
  submitText: { type: String, default: '确认提交' },
})
defineEmits(['link-existing'])

// state 对象在宿主里一次创建、不会替换，解构出的 ref 在模板里自动解包
const {
  uploadRef, formRef,
  mode, previewUrl, ocrLoading, ocrPartial, ocrError,
  duplicateInfo, checkingDuplicate, submitting, successVisible,
  form, formRules,
  handleBeforeUpload, handleFileChange, clearImage,
  onWaybillFocus, onWaybillBlur, clearManualInput,
  handleSubmit, disableFutureDate,
} = props.state
</script>

<style scoped>
.upload-layout {
  display: flex;
  gap: 24px;
}

.left-panel {
  flex: 0 0 45%;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* 玻璃质感由 .lg-card 提供（渐变磨砂 + 暖金彩色阴影），这里只留布局 */
.right-panel {
  flex: 1;
  padding: 24px;
}

.right-panel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-label {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.duplicate-actions {
  margin-top: 8px;
}

.waybill-uploader {
  width: 100%;
}

/* 拖拽区高度由内容块撑出（拖拽框自带上下 40px 内边距 → 总高约 220px）；禁用态底色由组件 disabled 自带 */
.dragger-body {
  height: 140px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.full-width { width: 100%; }

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
  max-height: 92px;
  object-fit: contain;
  border-radius: 4px;
}

.upload-disabled-mask {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: var(--button-disabled-text);
}

.upload-disabled-mask p {
  margin: 0;
  font-size: 13px;
}

/* 走输入框自身的边框变量，不穿透组件内部结构 */
.field-missing { --el-input-border-color: var(--color-danger); }

@media (max-width: 768px) {
  .upload-layout { flex-direction: column; }
  .left-panel, .right-panel { width: 100%; min-width: 0; box-sizing: border-box; }
  .right-panel { padding: 16px; }
}
</style>
