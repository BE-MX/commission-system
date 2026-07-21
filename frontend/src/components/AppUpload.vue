<template>
  <div class="app-upload">
    <el-upload
      :accept="accept"
      :multiple="multiple"
      :limit="limit"
      :show-file-list="false"
      :http-request="doUpload"
      :before-upload="beforeUpload"
    >
      <slot>
        <el-button :loading="uploading">{{ uploading ? `上传中 ${inflight.length} 个…` : buttonText }}</el-button>
      </slot>
    </el-upload>

    <div v-if="inflight.length" class="progress-list">
      <div v-for="it in inflight" :key="it.uid" class="progress-item">
        <span class="progress-name">{{ it.name }}</span>
        <el-progress
          :percentage="Math.min(it.percent, 100)"
          :indeterminate="it.percent === 0"
          :stroke-width="6"
          class="progress-bar"
        />
        <span v-if="it.percent >= 100" class="progress-hint">服务器处理中…</span>
      </div>
    </div>

    <div v-if="showList && modelValue.length" class="file-list">
      <div v-for="(file, i) in modelValue" :key="file.path || i" class="file-item">
        <el-image
          v-if="isImage(file)"
          :src="file.url"
          :preview-src-list="imageUrls"
          fit="cover"
          class="thumb"
        />
        <span v-else class="file-name">{{ file.name || file.path }}</span>
        <el-icon class="remove" @click="remove(i)"><Close /></el-icon>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * 通用上传组件（2026-07-03 治理 F-6）。
 * 上传实现由调用方注入（uploadFn: async (File, onProgress?) => ({ path, url })），
 * 组件只管选择/校验/进度/列表/预览/移除——新页面统一用它，不再各写 el-upload。
 * onProgress(percent 0~100) 由 uploadFn 自行接到 axios onUploadProgress，不接则进度条走 indeterminate。
 * show-list=false 时调用方自渲染已传文件列表（如培训速递的类型标签+备注富列表），组件只管选择与进度。
 */
import { computed, reactive, ref } from 'vue'
import { Close } from '@element-plus/icons-vue'
import { msgError } from '@/utils/feedback'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },   // [{ path, url, name }]
  uploadFn: { type: Function, required: true },
  accept: { type: String, default: 'image/*' },
  maxSizeMb: { type: Number, default: 10 },
  multiple: { type: Boolean, default: false },
  limit: { type: Number, default: 9 },
  buttonText: { type: String, default: '选择文件' },
  showList: { type: Boolean, default: true },
})
const emit = defineEmits(['update:modelValue'])

const inflight = ref([])   // [{ uid, name, percent }]
let uidSeq = 0
const uploading = computed(() => inflight.value.length > 0)
const imageUrls = computed(() => props.modelValue.filter(isImage).map(f => f.url))

function isImage(file) {
  return /\.(png|jpe?g|gif|webp)$/i.test(file.path || file.url || '') || (file.url || '').startsWith('data:image')
}

function beforeUpload(file) {
  if (file.size > props.maxSizeMb * 1024 * 1024) {
    msgError(`文件超过 ${props.maxSizeMb}MB 限制`)
    return false
  }
  if (props.modelValue.length + inflight.value.length >= props.limit) {
    msgError(`最多上传 ${props.limit} 个文件`)
    return false
  }
  return true
}

async function doUpload({ file }) {
  const item = reactive({ uid: ++uidSeq, name: file.name, percent: 0 })
  inflight.value.push(item)
  try {
    const result = await props.uploadFn(file, p => { item.percent = p })
    emit('update:modelValue', [...props.modelValue, { ...result, name: file.name }])
  } finally {
    inflight.value = inflight.value.filter(i => i.uid !== item.uid)
  }
}

function remove(index) {
  const next = [...props.modelValue]
  next.splice(index, 1)
  emit('update:modelValue', next)
}
</script>

<style scoped>
.progress-list { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; width: 100%; }
.progress-item { display: flex; align-items: center; gap: 10px; }
.progress-name { font-size: 12px; color: var(--text-secondary); max-width: 200px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex-shrink: 0; }
.progress-bar { flex: 1; min-width: 120px; }
.progress-hint { font-size: 12px; color: var(--text-muted); flex-shrink: 0; }
.file-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.file-item {
  position: relative; display: flex; align-items: center; gap: 6px;
  border: 1px solid var(--border-color); border-radius: var(--radius-md, 8px);
  padding: 4px; background: var(--card-bg);
}
.thumb { width: 56px; height: 56px; border-radius: 6px; display: block; }
.file-name { font-size: 12px; color: var(--text-secondary); padding: 6px 4px; max-width: 180px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.remove {
  position: absolute; top: -6px; right: -6px; cursor: pointer;
  background: var(--color-danger); color: #fff; border-radius: 50%; padding: 2px; font-size: 10px;
}
</style>
