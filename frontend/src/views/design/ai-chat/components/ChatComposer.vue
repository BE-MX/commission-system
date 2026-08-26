<template>
  <footer class="chat-composer">
    <slot name="mode" />
    <div v-if="attachments.length" class="attachment-strip" aria-label="待发送附件">
      <span v-for="attachment in attachments" :key="attachment.id" class="attachment-chip">
        <el-icon aria-hidden="true"><Document /></el-icon>
        <span>{{ attachment.original_name || attachment.name }}</span>
        <em v-if="attachment.optimistic">上传中</em>
        <button
          type="button"
          :aria-label="`移除 ${attachment.original_name || attachment.name}`"
          :disabled="streaming || attachment.optimistic"
          @click="emit('remove', attachment.id)"
        >
          <el-icon><Close /></el-icon>
        </button>
      </span>
    </div>

    <div class="composer-surface">
      <el-input
        ref="inputRef"
        :model-value="prompt"
        type="textarea"
        :autosize="{ minRows: 2, maxRows: 7 }"
        resize="none"
        :disabled="!canWrite"
        :placeholder="canWrite ? placeholder : '你只有查看权限，无法发送消息'"
        aria-label="方案对话输入"
        @update:model-value="emit('update:prompt', $event)"
        @keydown="handleKeydown"
      />

      <div class="composer-actions">
        <div class="composer-tools">
          <AppUpload
            v-if="canWrite && !streaming && attachments.length < 5"
            :model-value="attachments"
            :upload-fn="uploadFn"
            :accept="accept"
            :max-size-mb="4"
            :limit="5"
            :multiple="true"
            :show-list="false"
          >
            <button type="button" class="attach-button" :disabled="uploading">
              <el-icon aria-hidden="true"><Paperclip /></el-icon>
              添加附件
            </button>
          </AppUpload>
          <span v-else-if="canWrite && attachments.length >= 5" class="attachment-limit">已达 5 个附件上限</span>
        </div>

        <button
          v-if="streaming"
          type="button"
          class="stop-button"
          @click="emit('stop')"
        >
          <el-icon aria-hidden="true"><VideoPause /></el-icon>
          停止
        </button>
        <button
          v-else
          type="button"
          class="send-button"
          :disabled="!canWrite || !canSubmit"
          @click="emit('send')"
        >
          <el-icon aria-hidden="true"><Promotion /></el-icon>
          {{ sendLabel }}
        </button>
      </div>
    </div>

    <div class="composer-footnote">
      <span><el-icon aria-hidden="true"><Lock /></el-icon> 仅自己可见</span>
      <span v-if="canWrite">Enter 发送 · Shift+Enter 换行</span>
      <span v-else>当前为只读模式</span>
    </div>
  </footer>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Close, Document, Lock, Paperclip, Promotion, VideoPause } from '@element-plus/icons-vue'
import AppUpload from '@/components/AppUpload.vue'
import { isComposerSubmit } from '../state'

const props = defineProps({
  prompt: { type: String, default: '' },
  attachments: { type: Array, default: () => [] },
  uploadFn: { type: Function, required: true },
  canWrite: { type: Boolean, default: false },
  canSubmit: { type: Boolean, default: false },
  streaming: { type: Boolean, default: false },
  placeholder: { type: String, default: '描述你的问题、目标和约束…' },
  sendLabel: { type: String, default: '发送' },
})
const emit = defineEmits(['update:prompt', 'remove', 'send', 'stop'])
const inputRef = ref(null)
const uploading = computed(() => props.attachments.some(item => item.optimistic))
const accept = '.jpg,.jpeg,.png,.webp,.pdf,.docx,.xlsx,.pptx,.txt,.md'

function handleKeydown(event) {
  if (!props.canWrite || props.streaming || !props.canSubmit) return
  if (!isComposerSubmit(event)) return
  event.preventDefault()
  emit('send')
}

function focus() {
  inputRef.value?.focus()
}

defineExpose({ focus })
</script>

<style scoped>
.chat-composer {
  flex: 0 0 auto;
  padding: 10px clamp(14px, 4vw, 46px) 14px;
  background: linear-gradient(180deg, transparent, var(--dash-glass-bg-strong) 34%);
}

.attachment-strip {
  display: flex;
  width: min(100%, 820px);
  flex-wrap: wrap;
  gap: 7px;
  margin: 0 auto 8px;
}

.attachment-chip {
  display: inline-flex;
  max-width: 260px;
  min-height: 32px;
  align-items: center;
  gap: 6px;
  padding: 0 7px 0 10px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: var(--dash-glass-bg-strong);
  color: var(--text-secondary);
  font-size: 11px;
}

.attachment-chip > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.attachment-chip em { color: var(--color-warning-text); font-size: 10px; font-style: normal; }
.attachment-chip button {
  display: grid;
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  place-items: center;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--text-muted-blue);
  cursor: pointer;
}
.attachment-chip button:disabled { cursor: not-allowed; opacity: 0.45; }

.composer-surface {
  box-sizing: border-box;
  width: min(100%, 820px);
  margin: 0 auto;
  padding: 12px;
  border: 1px solid var(--dash-glass-border);
  border-radius: 18px;
  background: var(--dash-glass-bg-strong);
  box-shadow: var(--dash-glass-highlight), var(--dash-glass-shadow);
  transition:
    border-color 200ms var(--ease-out-strong),
    box-shadow 200ms var(--ease-out-strong);
}

.composer-surface:focus-within {
  border-color: var(--color-primary);
  box-shadow: var(--dash-glass-highlight), var(--dash-glass-shadow-hover);
}

.composer-surface :deep(.el-textarea__inner) {
  min-height: 52px !important;
  padding: 3px 4px 10px;
  border: 0;
  background: transparent;
  box-shadow: none;
  color: var(--text-primary);
  font-family: var(--font-body);
  font-size: 14px;
  line-height: 1.6;
}

.composer-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.composer-tools { min-width: 0; }
.attach-button,
.send-button,
.stop-button {
  display: inline-flex;
  min-height: 36px;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border-radius: 11px;
  cursor: pointer;
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 700;
  transition:
    transform 160ms var(--ease-out-strong),
    box-shadow 200ms var(--ease-out-strong),
    border-color 200ms ease,
    background-color 200ms ease,
    color 200ms ease,
    opacity 200ms ease,
    filter 200ms ease;
}

.attach-button {
  padding: 0 11px;
  border: 1px solid var(--border-color);
  background: transparent;
  color: var(--text-secondary);
}

.send-button,
.stop-button { min-width: 82px; padding: 0 14px; }
.send-button {
  border: 1px solid var(--color-primary);
  background: linear-gradient(135deg, var(--color-primary), var(--color-primary-hover));
  box-shadow: var(--card-shadow);
  color: var(--text-on-dark);
}
.send-button:disabled { cursor: not-allowed; filter: grayscale(0.5); opacity: 0.45; }
.stop-button { border: 1px solid var(--border-color); background: var(--toolbar-bg); color: var(--text-primary); }
.attachment-limit { color: var(--text-muted); font-size: 11px; }

.composer-footnote {
  display: flex;
  width: min(100%, 820px);
  justify-content: space-between;
  gap: 12px;
  margin: 7px auto 0;
  color: var(--text-muted-blue);
  font-size: 10px;
}
.composer-footnote span { display: inline-flex; align-items: center; gap: 4px; }

.attach-button:focus-visible,
.send-button:focus-visible,
.stop-button:focus-visible,
.attachment-chip button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }

.attach-button:active,
.stop-button:active { transform: scale(0.96); }
.send-button:not(:disabled):active { transform: scale(0.94); }

.attachment-chip { animation: chip-in 220ms var(--ease-out-strong) backwards; }
.attachment-chip button { transition: background-color 180ms ease, color 180ms ease; }

@keyframes chip-in {
  from { opacity: 0; transform: scale(0.92); }
}

@media (hover: hover) and (pointer: fine) {
  .attach-button:hover,
  .stop-button:hover { border-color: var(--border-hover); box-shadow: var(--card-shadow); color: var(--text-primary); transform: translateY(-1px); }
  .send-button:not(:disabled):hover { box-shadow: var(--dash-glass-shadow-hover); transform: translateY(-1px); }
  .attachment-chip button:not(:disabled):hover { background: var(--color-danger-bg); color: var(--color-danger-text); }
}

@media (prefers-reduced-motion: reduce) {
  .attachment-chip { animation: none; }
  .attach-button:active,
  .stop-button:active,
  .send-button:not(:disabled):active,
  .attach-button:hover,
  .stop-button:hover,
  .send-button:not(:disabled):hover { transform: none; }
}

@media (max-width: 640px) {
  .chat-composer { padding: 8px 10px calc(10px + env(safe-area-inset-bottom)); }
  .composer-surface { padding: 10px; border-radius: 16px; }
  .composer-footnote span:last-child { display: none; }
}
</style>
