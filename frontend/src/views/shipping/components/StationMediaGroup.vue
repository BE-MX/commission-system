<template>
  <div class="media-group">
    <div v-if="editable" class="capture-actions">
      <button type="button" :disabled="disabled" @click="photoInput.click()"><Camera :size="19" />拍照上传</button>
      <button type="button" :disabled="disabled" @click="videoInput.click()"><Video :size="19" />拍视频</button>
      <button type="button" :disabled="disabled" @click="albumInput.click()">相册视频</button>
    </div>
    <input ref="photoInput" class="capture-input" type="file" accept="image/*" capture="environment" :disabled="disabled" aria-label="拍摄验货照片" @change="choose($event, 'photos')" />
    <input ref="videoInput" class="capture-input" type="file" accept="video/*" capture="environment" :disabled="disabled" aria-label="拍摄验货视频" @change="choose($event, 'videos')" />
    <input ref="albumInput" class="capture-input" type="file" accept="video/mp4,video/quicktime,video/x-m4v,.mp4,.mov,.m4v" :disabled="disabled" aria-label="选择相册视频" @change="choose($event, 'videos')" />
    <div v-if="feedback?.stage" class="media-feedback" role="status">
      {{ feedback.stage }} · {{ feedback.progress }}%
      <progress :value="feedback.progress" max="100" aria-label="处理进度" />
    </div>
    <div v-if="feedback?.error" class="media-feedback media-error" role="alert">
      <p>{{ feedback.error }}</p>
      <button v-if="feedback.retryLabel" type="button" :disabled="disabled" @click="$emit('retry')">{{ feedback.retryLabel }}</button>
    </div>
    <div v-if="media.length" class="media-grid">
      <StationMediaTile v-for="item in media" :key="sessionId + ':' + item.id" :media="item" :session-id="sessionId" :editable="editable" :disabled="disabled" @remove="$emit('remove', $event)" @error="$emit('error', $event)" />
    </div>
    <p v-else class="media-empty">暂无照片或视频</p>
  </div>
</template>
<script setup>
import { ref } from 'vue'
import { Camera, VideoCamera as Video } from '@element-plus/icons-vue'
import StationMediaTile from './StationMediaTile.vue'
const props = defineProps({ media: { type: Array, default: () => [] }, sessionId: String, itemId: String, editable: Boolean, disabled: Boolean, feedback: Object })
const emit = defineEmits(['upload', 'remove', 'error', 'retry'])
const photoInput = ref(null), videoInput = ref(null), albumInput = ref(null)
function choose(event, type) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (file && props.editable && !props.disabled) emit('upload', file, props.itemId, type)
}
</script>
<style scoped>
.capture-actions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin:14px 0}.capture-actions button{display:flex;gap:8px;justify-content:center;align-items:center;min-height:48px;border:1px solid var(--border-color);border-radius:12px;color:var(--text-primary);background:var(--page-bg);font-size:14px;font-weight:600}.capture-actions button:first-child{border-color:var(--color-primary);background:var(--color-primary-light);color:var(--color-primary-hover)}button:disabled{opacity:.5;cursor:not-allowed}.capture-input{display:none}.media-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.media-empty{color:var(--text-secondary);font-size:13px;margin:16px 0 0}
.capture-actions svg{width:19px;height:19px}
.media-feedback{margin:12px 0;font-size:14px;line-height:1.6;overflow-wrap:anywhere}.media-feedback progress{display:block;width:100%;accent-color:var(--color-primary);margin-top:8px}.media-error{color:var(--color-danger)}.media-error p{margin:0 0 8px}.media-error button{width:100%;min-height:44px;padding:8px 12px;border:1px solid var(--border-color);border-radius:12px;background:var(--card-bg);color:var(--text-primary);font:inherit}
</style>
