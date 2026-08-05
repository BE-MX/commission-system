<template>
  <section class="prompt-composer">
    <div v-if="baseAsset" class="base-chip">
      <img v-if="assetUrl(baseAsset.id)" :src="assetUrl(baseAsset.id)" alt="编辑基准图" />
      <span>基于这张图修改</span>
      <button type="button" aria-label="清除基准图" @click="emit('clear-base')"><el-icon><Close /></el-icon></button>
    </div>

    <div v-if="attachments.length" class="attachment-strip">
      <div v-for="item in attachments" :key="item.uploadId" class="attachment-item">
        <img v-if="item.asset && assetUrl(item.asset.id)" :src="assetUrl(item.asset.id)" :alt="item.name" />
        <span v-else class="attachment-loading">{{ item.status === 'uploading' ? '上传中' : '处理中' }}</span>
        <button type="button" :disabled="item.status === 'uploading'" :aria-label="`移除 ${item.name}`" @click="emit('remove', item)">
          <el-icon><Close /></el-icon>
        </button>
      </div>
    </div>

    <el-input
      :model-value="prompt"
      type="textarea"
      :autosize="{ minRows: 2, maxRows: 5 }"
      maxlength="4000"
      resize="none"
      placeholder="输入你想生成或修改的内容…"
      @update:model-value="emit('update:prompt', $event)"
    />

    <div class="composer-toolbar">
      <div v-permission="'design_image:write'" class="upload-action" :class="{ 'is-disabled': uploadDisabled }">
        <AppUpload
          :model-value="uploadModel"
          :upload-fn="uploadFn"
          accept="image/jpeg,image/png,image/webp"
          :max-size-mb="20"
          :multiple="true"
          :limit="4"
          :show-list="false"
          button-text="添加参考图"
          @update:model-value="uploadModel = []"
        >
          <GlassButton variant="ghost" size="sm" :disabled="uploadDisabled">
            <template #left-icon><el-icon><Paperclip /></el-icon></template>
            参考图 {{ attachments.length }}/4
          </GlassButton>
        </AppUpload>
      </div>

      <el-select :model-value="size" class="size-select" aria-label="图片尺寸" @update:model-value="emit('update:size', $event)">
        <el-option v-for="option in sizes" :key="option" :label="sizeLabel(option)" :value="option" />
      </el-select>
      <el-select :model-value="quality" class="quality-select" aria-label="生成质量" @update:model-value="emit('update:quality', $event)">
        <el-option v-for="option in qualities" :key="option" :label="qualityLabel(option)" :value="option" />
      </el-select>

      <GlassButton
        v-permission="'design_image:write'"
        class="send-button"
        variant="primary"
        :loading="sending"
        :disabled="!canSend"
        @click="emit('submit')"
      >发送</GlassButton>
    </div>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import { Close, Paperclip } from '@element-plus/icons-vue'
import AppUpload from '@/components/AppUpload.vue'
import GlassButton from '@/components/GlassButton.vue'

defineProps({
  prompt: { type: String, default: '' },
  attachments: { type: Array, default: () => [] },
  baseAsset: { type: Object, default: null },
  sizes: { type: Array, default: () => [] },
  size: { type: String, default: '1024x1024' },
  qualities: { type: Array, default: () => [] },
  quality: { type: String, default: 'medium' },
  uploadFn: { type: Function, required: true },
  assetUrl: { type: Function, required: true },
  uploadDisabled: { type: Boolean, default: false },
  canSend: { type: Boolean, default: false },
  sending: { type: Boolean, default: false },
})
const emit = defineEmits(['update:prompt', 'update:size', 'update:quality', 'submit', 'remove', 'clear-base'])
const uploadModel = ref([])

const sizeLabels = { '1024x1024': '正方形', '1024x1536': '竖版', '1536x1024': '横版' }
const qualityLabels = { low: '快速', medium: '标准', high: '精细' }
function sizeLabel(value) { return sizeLabels[value] || value }
function qualityLabel(value) { return qualityLabels[value] || value }
</script>

<style scoped>
.prompt-composer {
  flex: 0 0 auto; border-top: 1px solid var(--border-color); background: var(--dash-glass-bg-strong);
  padding: 12px 18px; padding-bottom: max(16px, env(safe-area-inset-bottom));
}
.base-chip { display: inline-flex; align-items: center; gap: 8px; margin-bottom: 10px; padding: 5px 8px; border-radius: var(--radius-md, 8px); background: var(--color-primary-light); color: var(--color-gold-muted); font-size: 12px; }
.base-chip img { width: 34px; height: 34px; border-radius: 6px; object-fit: cover; }
.base-chip button, .attachment-item button { display: grid; place-items: center; border: 0; background: transparent; color: inherit; cursor: pointer; }
.attachment-strip { display: flex; gap: 8px; margin-bottom: 10px; overflow-x: auto; }
.attachment-item { position: relative; width: 62px; height: 62px; flex: 0 0 62px; overflow: hidden; border: 1px solid var(--border-color); border-radius: var(--radius-md, 8px); background: var(--toolbar-bg); }
.attachment-item img { width: 100%; height: 100%; object-fit: cover; }
.attachment-item button { position: absolute; top: 2px; right: 2px; width: 20px; height: 20px; border-radius: 50%; background: var(--dash-glass-bg-strong); color: var(--text-primary); }
.attachment-loading { display: grid; height: 100%; place-items: center; color: var(--text-muted); font-size: 11px; }
.composer-toolbar { display: flex; align-items: center; gap: 8px; margin-top: 10px; }
.upload-action.is-disabled { pointer-events: none; opacity: 0.55; }
.size-select { width: 112px; }
.quality-select { width: 94px; }
.send-button { margin-left: auto; transition: transform 140ms cubic-bezier(0.23, 1, 0.32, 1); }
.send-button:active:not(:disabled) { transform: scale(0.97); }
@media (hover: hover) and (pointer: fine) {
  .attachment-item button:hover, .base-chip button:hover { color: var(--color-danger-text); }
}
@media (max-width: 640px) {
  .prompt-composer { padding-inline: 12px; }
  .composer-toolbar { flex-wrap: wrap; }
  .send-button { margin-left: 0; flex: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .send-button { transition: opacity 140ms linear; }
  .send-button:active:not(:disabled) { transform: none; opacity: 0.8; }
}
</style>
