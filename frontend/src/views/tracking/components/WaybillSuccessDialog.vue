<template>
  <el-dialog
    v-model="dialogVisible"
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
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Document, Van, User, Location, Calendar,
  Link, CopyDocument, Check, ChatDotRound,
} from '@element-plus/icons-vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  resultData: { type: Object, required: true },
})

const emit = defineEmits(['update:modelValue', 'continue'])

const dialogVisible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const copiedLink = ref(false)
const copiedTemplate = ref(false)

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
  const ok = await copyToClipboard(props.resultData.short_link)
  if (ok) {
    copiedLink.value = true
    ElMessage.success('短链接已复制')
    setTimeout(() => (copiedLink.value = false), 2500)
  } else {
    ElMessage.error('复制失败')
  }
}

async function copyTemplate() {
  const ok = await copyToClipboard(props.resultData.notifyTemplate)
  if (ok) {
    copiedTemplate.value = true
    ElMessage.success('通知模板已复制')
    setTimeout(() => (copiedTemplate.value = false), 2500)
  } else {
    ElMessage.error('复制失败')
  }
}

function handleClose() {
  emit('update:modelValue', false)
}

function handleContinue() {
  emit('update:modelValue', false)
  emit('continue')
}
</script>

<style scoped>
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

.ripple-1 { animation: rippleAnim 1.5s ease-out 0.8s forwards; }
.ripple-2 { animation: rippleAnim 1.5s ease-out 1.1s forwards; }
.ripple-3 { animation: rippleAnim 1.5s ease-out 1.4s forwards; }

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
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
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

.info-row:last-child { border-bottom: none; }

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
.status-pending          { color: #909399; background: #f4f4f5; }
.status-picked_up        { color: #409eff; background: #ecf5ff; }
.status-in_transit       { color: #e6a23c; background: #fdf6ec; }
.status-out_for_delivery { color: #e6a23c; background: #fdf6ec; }
.status-customs,
.status-customs_hold     { color: #f56c6c; background: #fef0f0; }
.status-delivered        { color: #67c23a; background: #f0f9eb; }
.status-returned         { color: #909399; background: #f4f4f5; }
.status-exception        { color: #f56c6c; background: #fef0f0; }
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

/* 弹窗动画 */
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
  0% { opacity: 0; transform: scale(0.7) translateY(30px); }
  70% { transform: scale(1.02) translateY(-4px); }
  100% { opacity: 1; transform: scale(1) translateY(0); }
}

/* 响应式 */
@media (max-width: 768px) {
  .success-content {
    padding: 24px 16px 20px;
  }
}
</style>
