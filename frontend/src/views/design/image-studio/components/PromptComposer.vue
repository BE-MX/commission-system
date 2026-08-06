<template>
  <section class="prompt-composer">
    <div class="composer-card">
      <div v-if="baseAsset" class="base-chip">
        <img v-if="assetUrl(baseAsset.id)" :src="assetUrl(baseAsset.id)" alt="编辑基准图" />
        <span>基于这张图修改</span>
        <button type="button" :disabled="sending" aria-label="清除基准图" @click="emit('clear-base')"><el-icon><Close /></el-icon></button>
      </div>

      <div v-if="attachments.length" class="attachment-strip">
        <div v-for="item in attachments" :key="item.uploadId" class="attachment-item">
          <img v-if="item.asset && assetUrl(item.asset.id)" :src="assetUrl(item.asset.id)" :alt="item.name" />
          <span v-else class="attachment-loading"><el-icon class="is-loading"><Loading /></el-icon>{{ item.status === 'uploading' ? '上传中' : '处理中' }}</span>
          <button type="button" :disabled="sending || item.status === 'uploading'" :aria-label="`移除 ${item.name}`" @click="emit('remove', item)">
            <el-icon><Close /></el-icon>
          </button>
        </div>
      </div>

      <el-input
        ref="inputRef"
        :model-value="prompt"
        class="composer-input"
        type="textarea"
        :autosize="{ minRows: 2, maxRows: 6 }"
        maxlength="4000"
        resize="none"
        placeholder="描述你想生成或修改的画面…"
        @update:model-value="emit('update:prompt', $event)"
        @keydown="onKeydown"
      />

      <div class="composer-toolbar">
        <div v-permission="'design_image:write'" class="upload-action" :class="{ 'is-disabled': uploadDisabled }">
          <AppUpload
            :model-value="uploadModel"
            :upload-fn="uploadFn"
            accept="image/jpeg,image/png,image/webp"
            :max-size-mb="maxUploadMb"
            :multiple="true"
            :limit="4"
            :show-list="false"
            button-text="添加参考图"
            @update:model-value="uploadModel = []"
          >
            <GlassButton variant="ghost" size="sm" :disabled="uploadDisabled" title="上传 1～4 张参考图">
              <template #left-icon><el-icon><Paperclip /></el-icon></template>
              参考图 {{ attachments.length }}/4
            </GlassButton>
          </AppUpload>
        </div>

        <el-select :model-value="size" class="tool-select" aria-label="图片尺寸" @update:model-value="emit('update:size', $event)">
          <el-option v-for="option in sizes" :key="option" :label="sizeLabel(option)" :value="option" />
        </el-select>
        <el-select :model-value="quality" class="tool-select" aria-label="生成质量" @update:model-value="emit('update:quality', $event)">
          <el-option v-for="option in qualities" :key="option" :label="qualityLabel(option)" :value="option" />
        </el-select>

        <span v-if="prompt.length > 3000" class="char-count">{{ prompt.length }}/4000</span>
        <span class="key-hint" aria-hidden="true">Enter 发送 · Shift+Enter 换行</span>

        <GlassButton
          v-permission="'design_image:write'"
          class="send-button"
          variant="primary"
          radius="full"
          :loading="sending"
          :disabled="!canSend"
          @click="emit('submit')"
        >
          <template #left-icon><el-icon><Promotion /></el-icon></template>
          发送
        </GlassButton>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Close, Loading, Paperclip, Promotion } from '@element-plus/icons-vue'
import AppUpload from '@/components/AppUpload.vue'
import GlassButton from '@/components/GlassButton.vue'

const props = defineProps({
  prompt: { type: String, default: '' },
  attachments: { type: Array, default: () => [] },
  baseAsset: { type: Object, default: null },
  sizes: { type: Array, default: () => [] },
  size: { type: String, default: '1024x1024' },
  qualities: { type: Array, default: () => [] },
  quality: { type: String, default: 'medium' },
  uploadFn: { type: Function, required: true },
  assetUrl: { type: Function, required: true },
  maxUploadBytes: { type: Number, default: 20 * 1024 * 1024 },
  uploadDisabled: { type: Boolean, default: false },
  canSend: { type: Boolean, default: false },
  sending: { type: Boolean, default: false },
})
const emit = defineEmits(['update:prompt', 'update:size', 'update:quality', 'submit', 'remove', 'clear-base'])
const uploadModel = ref([])
const inputRef = ref(null)
const maxUploadMb = computed(() => Math.max(props.maxUploadBytes / (1024 * 1024), 0.01))

const sizeLabels = { '1024x1024': '正方形', '1024x1536': '竖版', '1536x1024': '横版' }
const qualityLabels = { low: '快速', medium: '标准', high: '精细' }
function sizeLabel(value) { return sizeLabels[value] || value }
function qualityLabel(value) { return qualityLabels[value] || value }

/* Enter 发送、Shift+Enter 换行；isComposing 挡住中文输入法选词回车 */
function onKeydown(event) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  if (props.canSend && !props.sending) emit('submit')
}

function focus() {
  inputRef.value?.focus()
}

onMounted(() => {
  if (globalThis.matchMedia?.('(pointer: fine)').matches) focus()
})

defineExpose({ focus })
</script>

<style scoped>
.prompt-composer {
  flex: 0 0 auto; padding: 12px 18px; padding-bottom: max(16px, env(safe-area-inset-bottom));
  border-top: 1px solid var(--border-color); background: rgba(255, 255, 255, 0.4);
}

/* 浮动输入卡：聚焦时金色光环 */
.composer-card {
  max-width: 820px; margin: 0 auto; padding: 6px 6px 8px;
  border: 1px solid var(--border-color); border-radius: 18px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 8px 24px rgba(146, 103, 24, 0.1), inset 0 1px 0 rgba(255, 255, 255, 0.9);
  transition: border-color 200ms cubic-bezier(0.23, 1, 0.32, 1), box-shadow 200ms cubic-bezier(0.23, 1, 0.32, 1);
}
.composer-card:focus-within {
  border-color: var(--color-primary);
  box-shadow: 0 8px 24px rgba(146, 103, 24, 0.12), 0 0 0 4px var(--color-primary-glow);
}

/* 去掉 el-input 默认边框，融进卡片 */
.composer-input :deep(.el-textarea__inner) {
  padding: 10px 12px 2px; border: 0; background: transparent; box-shadow: none;
  color: var(--text-primary); font-family: var(--font-body); font-size: 14px; line-height: 1.6;
}
.composer-input :deep(.el-textarea__inner:focus) { box-shadow: none; }
.composer-input :deep(.el-textarea__inner::placeholder) { color: var(--text-placeholder); }

/* 基准图 chip */
.base-chip {
  display: inline-flex; align-items: center; gap: 8px; margin: 6px 0 2px 8px; padding: 5px 10px 5px 6px;
  border: 1px solid rgba(212, 148, 28, 0.3); border-radius: 999px;
  background: var(--color-gold-soft); color: var(--color-gold-muted); font-size: 12px; font-weight: 600;
}
.base-chip img { width: 28px; height: 28px; border-radius: 50%; object-fit: cover; }
.base-chip button {
  display: grid; width: 18px; height: 18px; place-items: center; border: 0; border-radius: 50%;
  background: rgba(212, 148, 28, 0.14); color: inherit; cursor: pointer; font-size: 11px;
}

/* 参考图条 */
.attachment-strip { display: flex; gap: 8px; padding: 8px 8px 2px; overflow-x: auto; }
.attachment-item {
  position: relative; width: 60px; height: 60px; flex: 0 0 60px; overflow: hidden;
  border: 1px solid var(--border-color); border-radius: 12px; background: var(--toolbar-bg);
}
.attachment-item img { width: 100%; height: 100%; object-fit: cover; }
.attachment-item button {
  position: absolute; top: 3px; right: 3px; display: grid; width: 18px; height: 18px; place-items: center;
  border: 0; border-radius: 50%; background: rgba(30, 27, 24, 0.62); color: var(--text-on-dark); cursor: pointer; font-size: 10px;
}
.attachment-loading {
  display: flex; height: 100%; flex-direction: column; align-items: center; justify-content: center;
  gap: 3px; color: var(--text-muted); font-size: 10px;
}

/* 工具行 */
.composer-toolbar { display: flex; align-items: center; gap: 8px; padding: 4px 6px 0 8px; }
.upload-action.is-disabled { pointer-events: none; opacity: 0.55; }

.tool-select { width: 104px; }
.tool-select :deep(.el-select__wrapper) {
  min-height: 30px; border-radius: 999px; background: var(--toolbar-bg);
  box-shadow: 0 0 0 1px var(--border-color) inset; font-size: 12px;
  transition: box-shadow 160ms cubic-bezier(0.23, 1, 0.32, 1), background-color 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
.tool-select :deep(.el-select__wrapper.is-focused) { box-shadow: 0 0 0 1px var(--color-primary) inset; background: var(--card-bg); }

.char-count { color: var(--text-muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.key-hint { margin-left: auto; color: var(--text-muted); font-size: 11px; letter-spacing: 0.02em; }
.send-button { margin-left: auto; transition: transform 140ms cubic-bezier(0.23, 1, 0.32, 1); }
.key-hint + .send-button { margin-left: 0; }
.send-button:active:not(:disabled) { transform: scale(0.97); }

@media (hover: hover) and (pointer: fine) {
  .attachment-item button:hover { background: var(--color-danger); }
  .base-chip button:hover { background: rgba(192, 57, 43, 0.16); color: var(--color-danger-text); }
  .tool-select :deep(.el-select__wrapper:hover) { box-shadow: 0 0 0 1px var(--border-hover) inset; background: var(--card-bg); }
}
@media (max-width: 640px) {
  .prompt-composer { padding-inline: 10px; }
  .composer-toolbar { flex-wrap: wrap; }
  .key-hint { display: none; }
  .send-button { flex: 1; margin-left: 0; }
  .tool-select { flex: 1; min-width: 92px; }
}
@media (prefers-reduced-motion: reduce) {
  .composer-card, .tool-select :deep(.el-select__wrapper) { transition: none; }
  .send-button { transition: none; }
  .send-button:active:not(:disabled) { transform: none; opacity: 0.85; }
}
</style>
